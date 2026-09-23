#!/usr/bin/env python3
"""Mechanically inspect video metadata and an optional SRT; no perceptual claims."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

PROBE_TIMEOUT = 30.0
DURATION_TOLERANCE_SECONDS = 0.1
SRT_BOUNDARY_TOLERANCE_SECONDS = 0.001
TIME_RE = re.compile(r"^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$")


def positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Expected a positive finite number")
    return number


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return number


def finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def timestamp_ms(value: str) -> int:
    match = TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("Expected a nonnegative HH:MM:SS,mmm timestamp")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def validate_srt(text: str, video_duration: float | None) -> dict[str, Any]:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    errors: list[dict[str, Any]] = []
    if not text.strip():
        return {"status": "failed", "cue_count": 0,
                "errors": [{"code": "empty_srt", "message": "SRT has no cues"}]}
    blocks = re.split(r"\n[ \t]*\n+", text.strip())
    previous_start = previous_end = None
    previous_index = None
    valid_cues = 0
    for position, block in enumerate(blocks, 1):
        lines = block.splitlines()
        def error(code: str, message: str) -> None:
            errors.append({"cue_position": position, "code": code, "message": message})
        if len(lines) < 2 or not re.fullmatch(r"\d+", lines[0].strip()):
            error("invalid_index", "Cue must begin with a positive integer index")
            continue
        index = int(lines[0].strip())
        if index <= 0 or (previous_index is not None and index <= previous_index):
            error("index_order", "Cue indexes must be positive and strictly increasing")
        previous_index = index
        times = lines[1].split("-->")
        try:
            if len(times) != 2:
                raise ValueError("Cue must contain one start --> end timestamp pair")
            start, end = [timestamp_ms(t) for t in times]
        except ValueError as exc:
            error("invalid_time", str(exc))
            continue
        visible_text = re.sub(r"<[^>]*>", "", "\n".join(lines[2:])).strip()
        if not visible_text or "\x00" in visible_text:
            error("empty_or_invalid_text", "Cue must have nonempty subtitle text without NUL bytes")
        if end <= start:
            error("invalid_duration", "Cue end must be later than its start")
        if previous_start is not None and start < previous_start:
            error("time_order", "Cue start times must be chronological")
        if previous_end is not None and start < previous_end:
            error("overlap", "Cue begins before the previous cue ends")
        if video_duration is not None and end / 1000 > video_duration + SRT_BOUNDARY_TOLERANCE_SECONDS:
            error("out_of_bounds", "Cue extends beyond the selected video timeline")
        previous_start, previous_end = start, end
        valid_cues += 1
    if video_duration is None:
        errors.append({"code": "unknown_video_duration",
                       "message": "Cannot validate SRT timeline bounds without a video duration"})
    return {"status": "failed" if errors else "ok", "cue_count": len(blocks),
            "parsed_cue_count": valid_cues, "errors": errors,
            "boundary_tolerance_seconds": SRT_BOUNDARY_TOLERANCE_SECONDS}


def verify(video: str | Path, srt: str | Path | None = None,
           ffprobe: str | None = None, expect_duration: float | None = None,
           expect_width: int | None = None, expect_height: int | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1, "status": "ok", "video": str(video), "checks": [],
        "limitations": [
            "Mechanical metadata and optional SRT checks only; full-file decoding was not tested.",
            "Visual appearance, color quality, audio/video synchronization, and listening were not verified.",
            "A valid SRT does not prove subtitles are burned into this video or aligned with the singing.",
            "Dimension expectations refer to encoded dimensions, before display rotation.",
        ],
    }
    def check(name: str, passed: bool, **details: Any) -> None:
        report["checks"].append({"name": name, "status": "ok" if passed else "failed", **details})
        if not passed:
            report["status"] = "failed"
    video_path = Path(video)
    try:
        input_exists = video_path.is_file() and video_path.stat().st_size > 0
    except OSError:
        input_exists = False
    check("video_input", input_exists)
    requested = ffprobe or os.environ.get("BAND_STUDIO_FFPROBE") or "ffprobe"
    probe_path = shutil.which(requested)
    check("ffprobe_available", probe_path is not None, requested=requested, path=probe_path)
    metadata = None
    if input_exists and probe_path:
        try:
            result = subprocess.run([probe_path, "-v", "error", "-show_format", "-show_streams",
                                     "-of", "json", str(video_path.resolve())],
                                    capture_output=True, text=True, timeout=PROBE_TIMEOUT, check=False)
            if result.returncode:
                check("ffprobe_execution", False, returncode=result.returncode,
                      error=(result.stderr or "FFprobe failed")[-1200:])
            else:
                try:
                    metadata = json.loads(result.stdout)
                    if not isinstance(metadata, dict) or not isinstance(metadata.get("streams"), list):
                        raise ValueError("Expected an FFprobe object with a streams array")
                    check("ffprobe_execution", True)
                except (ValueError, TypeError) as exc:
                    metadata = None
                    check("ffprobe_json", False, error=str(exc)[:1200])
        except subprocess.TimeoutExpired:
            check("ffprobe_execution", False, error="FFprobe timed out", timeout_seconds=PROBE_TIMEOUT)
        except (OSError, UnicodeError) as exc:
            check("ffprobe_execution", False, error=str(exc)[:1200])
    video_duration = None
    if metadata is not None:
        streams = [s for s in metadata["streams"] if isinstance(s, dict)]
        videos = [s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") if isinstance(s.get("disposition"), dict) else {}).get("attached_pic")]
        check("video_stream", bool(videos))
        format_info = metadata.get("format") if isinstance(metadata.get("format"), dict) else {}
        container_duration = finite_positive(format_info.get("duration"))
        if videos:
            selected = videos[0]
            video_duration = finite_positive(selected.get("duration")) or container_duration
            duration = container_duration or video_duration
            width, height = selected.get("width"), selected.get("height")
            dimensions_ok = (isinstance(width, int) and not isinstance(width, bool) and width > 0
                             and isinstance(height, int) and not isinstance(height, bool) and height > 0)
            check("dimensions_present", dimensions_ok)
            check("duration_present", duration is not None)
            report["media"] = {"duration_seconds": duration, "video_duration_seconds": video_duration,
                               "width": width, "height": height, "codec": selected.get("codec_name"),
                               "pixel_format": selected.get("pix_fmt"), "stream_index": selected.get("index"),
                               "audio_stream_count": sum(s.get("codec_type") == "audio" for s in streams)}
            if expect_duration is not None:
                valid_expected = finite_positive(expect_duration)
                check("expected_duration", bool(valid_expected is not None and duration is not None
                                                and abs(duration - valid_expected) <= DURATION_TOLERANCE_SECONDS + 1e-9),
                      expected=expect_duration, actual=duration,
                      tolerance_seconds=DURATION_TOLERANCE_SECONDS)
            for axis, expected, actual in (("width", expect_width, width), ("height", expect_height, height)):
                if expected is not None:
                    check("expected_" + axis, isinstance(expected, int) and expected > 0 and actual == expected,
                          expected=expected, actual=actual)
    if srt is not None:
        try:
            text = Path(srt).read_text(encoding="utf-8-sig")
            report["srt"] = {"file": str(srt), **validate_srt(text, video_duration)}
            check("srt_validation", report["srt"]["status"] == "ok")
        except (OSError, UnicodeError) as exc:
            check("srt_read", False, error=str(exc)[:1200])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Existing local video file")
    parser.add_argument("--srt", help="Optional UTF-8 SRT sidecar")
    parser.add_argument("--ffprobe", help="Executable path or command name")
    parser.add_argument("--expect-duration", type=positive_float)
    parser.add_argument("--expect-width", type=positive_int)
    parser.add_argument("--expect-height", type=positive_int)
    args = parser.parse_args(argv)
    report = verify(args.video, args.srt, args.ffprobe, args.expect_duration,
                    args.expect_width, args.expect_height)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
