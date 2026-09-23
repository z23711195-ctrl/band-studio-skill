#!/usr/bin/env python3
"""Build a local, read-only media inventory using only the standard library.

Only paths relative to the input root are written. Probe output is allowlisted;
tags, comments, filenames, raw stderr and document contents are never retained.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


EXTENSIONS = {
    "audio": {".mp3", ".m4a", ".wav", ".flac", ".aac", ".aif", ".aiff", ".ogg", ".opus", ".wma"},
    "video": {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi", ".mpeg", ".mpg", ".mts", ".m2ts"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".gif", ".bmp", ".avif"},
    "document": {".pdf", ".docx", ".txt", ".md", ".rtf", ".xlsx"},
}
TYPE_BY_EXTENSION = {extension: kind for kind, extensions in EXTENSIONS.items() for extension in extensions}
SKIP_DIRECTORIES = {
    "node_modules", "vendor", "venv", "env", "__pycache__", "site-packages",
    "build", "dist", "target", "secrets", "credentials", "private_keys",
}
SECRET_MARKERS = {
    "credential", "password", "passwd", "secret", "token", "api_key", "api-key",
    "apikey", "private_key", "private-key", "id_rsa", "id_ed25519",
    "密码", "密钥", "凭据", "验证码",
}


def _excluded_name(name: str) -> bool:
    lowered = name.casefold()
    return name.startswith(".") or any(marker in lowered for marker in SECRET_MARKERS)


def _error(stage: str, code: str, **details: Any) -> dict[str, Any]:
    # Deliberately do not include exception messages or tool stderr: they may
    # contain absolute paths, tags or other private values.
    return {"stage": stage, "code": code, **details}


def _snapshot(root: Path) -> tuple[list[tuple[Path, str]], list[dict[str, Any]]]:
    found: list[tuple[Path, str]] = []
    errors: list[dict[str, Any]] = []

    def walk_error(_: OSError) -> None:
        errors.append(_error("scan", "directory_unreadable"))

    for current, directories, filenames in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(current)
        directories[:] = sorted(
            name for name in directories
            if not _excluded_name(name)
            and name.casefold() not in SKIP_DIRECTORIES
            and not (parent / name).is_symlink()
        )
        for name in sorted(filenames):
            path = parent / name
            kind = TYPE_BY_EXTENSION.get(path.suffix.casefold())
            if kind and not _excluded_name(name) and not path.is_symlink():
                found.append((path, kind))
    return sorted(found, key=lambda item: item[0].relative_to(root).as_posix()), errors


def _number(value: Any, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if integer:
        return int(number) if number.is_integer() else None
    return number


def _safe_token(value: Any) -> str | None:
    # Codec and container identifiers should never include free-form text.
    if isinstance(value, str) and 0 < len(value) <= 80:
        if all(character.isascii() and (character.isalnum() or character in "_,.-") for character in value):
            return value
    return None


def _sanitize_probe(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("probe_not_object")
    raw_streams = raw.get("streams")
    if not isinstance(raw_streams, list):
        raise ValueError("probe_streams_missing")
    streams: list[dict[str, Any]] = []
    for source in raw_streams:
        if not isinstance(source, dict) or source.get("codec_type") not in {"audio", "video"}:
            continue
        target: dict[str, Any] = {"codec_type": source["codec_type"]}
        codec = _safe_token(source.get("codec_name"))
        if codec is not None:
            target["codec_name"] = codec
        for name in ("width", "height", "sample_rate", "channels"):
            value = _number(source.get(name), integer=True)
            if value is not None:
                target[name] = value
        duration = _number(source.get("duration"))
        if duration is not None:
            target["duration_seconds"] = duration
        # Frame rates are normalized to numbers, never copied as arbitrary text.
        frame_rate = source.get("avg_frame_rate")
        if isinstance(frame_rate, str) and frame_rate.count("/") == 1:
            numerator, denominator = frame_rate.split("/")
            top, bottom = _number(numerator), _number(denominator)
            if top is not None and bottom is not None and bottom > 0:
                fps = top / bottom
                if math.isfinite(fps):
                    target["average_frame_rate"] = fps
        streams.append(target)
    if not streams:
        raise ValueError("probe_no_audio_video_streams")
    result: dict[str, Any] = {"streams": streams}
    source_format = raw.get("format")
    if isinstance(source_format, dict):
        container: dict[str, Any] = {}
        name = _safe_token(source_format.get("format_name"))
        if name is not None:
            container["format_name"] = name
        duration = _number(source_format.get("duration"))
        if duration is not None:
            container["duration_seconds"] = duration
        if container:
            result["format"] = container
    return result


def _probe(path: Path, executable: str, timeout: float) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    command = [
        executable, "-v", "error", "-show_entries",
        "format=format_name,duration:stream=codec_type,codec_name,width,height,sample_rate,channels,duration,avg_frame_rate",
        "-of", "json", str(path),
    ]
    try:
        completed = subprocess.run(
            command, shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return None, _error("probe", "timeout", timeout_seconds=timeout)
    except OSError:
        return None, _error("probe", "executable_unavailable")
    if completed.returncode != 0:
        return None, _error("probe", "nonzero_exit", returncode=completed.returncode)
    try:
        metadata = _sanitize_probe(json.loads(completed.stdout))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, _error("probe", "invalid_metadata")
    return metadata, None


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_catalog(
    input_root: str | Path, output: str | Path, *, probe: bool = False,
    hash_files: bool = False, ffprobe: str | None = None, timeout: float = 20,
) -> dict[str, Any]:
    root_argument, output_path = Path(input_root), Path(output)
    if root_argument.is_symlink() or not root_argument.is_dir():
        raise ValueError("Input must be an existing non-symlink directory.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be a positive finite number.")
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError("Output directory must not already exist.")
    executable = ffprobe if ffprobe is not None else (os.environ.get("BAND_STUDIO_FFPROBE") or "ffprobe")
    if not executable or "\x00" in executable:
        raise ValueError("The ffprobe executable must be a nonempty path without null bytes.")
    root = root_argument.resolve()
    # Snapshot first: an output created inside the input cannot index itself.
    candidates, scan_errors = _snapshot(root)
    assets: list[dict[str, Any]] = []
    for path, kind in candidates:
        record: dict[str, Any] = {
            "relative_path": path.relative_to(root).as_posix(), "media_type": kind,
            "status": "indexed", "listening": "not_performed",
            "content_review": "not_performed", "errors": [],
        }
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError("Source changed after snapshot")
            before = path.stat()
            record["size_bytes"] = before.st_size
            if hash_files:
                record["sha256"] = _digest(path)
            if probe and kind in {"audio", "video"}:
                metadata, problem = _probe(path, executable, timeout)
                record["probe_status"] = "error" if problem else "ok"
                if problem:
                    record["errors"].append(problem)
                else:
                    record["metadata"] = metadata
            else:
                record["probe_status"] = "not_applicable" if probe else "not_requested"
            after = path.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                record["errors"].append(_error("source", "changed_during_scan"))
                record.pop("sha256", None)
        except OSError:
            record["errors"].append(_error("source", "file_unreadable_or_changed"))
            record.pop("sha256", None)
        if record["errors"]:
            record["status"] = "error"
        assets.append(record)

    hashes: dict[str, list[str]] = {}
    if hash_files:
        for record in assets:
            if "sha256" in record:
                hashes.setdefault(record["sha256"], []).append(record["relative_path"])
    duplicates = [
        {"sha256": digest, "relative_paths": paths, "copy_count": len(paths)}
        for digest, paths in sorted(hashes.items()) if len(paths) > 1
    ]
    error_count = len(scan_errors) + sum(len(record["errors"]) for record in assets)
    summary = {
        "files": len(assets), "files_with_errors": sum(bool(record["errors"]) for record in assets),
        "errors": error_count,
        "by_type": {kind: sum(record["media_type"] == kind for record in assets) for kind in EXTENSIONS},
        "probe_requested": probe, "hash_requested": hash_files,
    }
    result = {
        "schema_version": 1, "status": "completed_with_errors" if error_count else "ok",
        "scope": "local inventory; no playback, uploads or document text extraction",
        "path_basis": "input_root_relative", "listening": "not_performed",
        "summary": summary, "scan_errors": scan_errors,
        "duplicate_detection": {
            "status": "sha256_comparison" if hash_files else "not_requested",
            "meaning": "identical bytes only; not recording identity" if hash_files else "not evaluated",
            "groups": duplicates,
        },
        "assets": assets,
    }
    output_path.mkdir(parents=True, exist_ok=False)
    with (output_path / "catalog.json").open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    fields = ["relative_path", "media_type", "size_bytes", "status", "sha256", "probe_status", "listening", "errors"]
    with (output_path / "catalog.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in assets:
            row = {key: record.get(key, "") for key in fields}
            row["errors"] = json.dumps(record["errors"], ensure_ascii=False)
            writer.writerow(row)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_root", metavar="INPUT_ROOT", type=Path)
    parser.add_argument("--output", required=True, type=Path, metavar="NEW_DIRECTORY")
    parser.add_argument("--probe", action="store_true", help="Probe audio/video container metadata; does not listen.")
    parser.add_argument("--hash", dest="hash_files", action="store_true", help="Compute SHA256 and group byte-identical files.")
    parser.add_argument("--ffprobe", default=None, metavar="PATH",
                        help="Override BAND_STUDIO_FFPROBE; otherwise use ffprobe from PATH.")
    parser.add_argument("--timeout", type=float, default=20)
    arguments = parser.parse_args(argv)
    try:
        result = build_catalog(**vars(arguments))
    except (ValueError, FileExistsError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except OSError:
        print(json.dumps({"status": "error", "error": "Unable to create or write the new output directory."}), file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], **result["summary"]}, ensure_ascii=False))
    return 1 if result["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
