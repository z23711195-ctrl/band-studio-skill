#!/usr/bin/env python3
"""Report locally observed media-tool capabilities; no network or repair actions."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from typing import Any

COMMAND_TIMEOUT = 15.0
REQUIRED_FILTERS = ("ass", "subtitles", "drawtext")
REQUIRED_ENCODERS = ("libx264", "aac")
OPTIONAL_ANALYSIS_COMMANDS = ("whisper-cli", "whisper-cpp", "whisper", "demucs")


def resolve_tool(explicit: str | None, env_name: str, default: str) -> tuple[str, str | None]:
    requested = explicit or os.environ.get(env_name) or default
    return requested, shutil.which(requested)


def observe_command(command: list[str], timeout: float = COMMAND_TIMEOUT) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"Command exceeded {timeout:g} seconds"}
    except (OSError, UnicodeError) as exc:
        return {"status": "failed", "error": str(exc)[:1200]}
    if result.returncode:
        return {"status": "failed", "returncode": result.returncode,
                "error": (result.stderr or result.stdout or "Command failed")[-1200:]}
    return {"status": "observed", "output": result.stdout + result.stderr}


def table_names(output: str) -> set[str]:
    # FFmpeg releases use either two or three filter flags, and six encoder flags.
    return set(re.findall(r"^\s*[A-Z.]{2,7}\s+([A-Za-z0-9_]+)\s+", output, re.MULTILINE))


def diagnose(ffmpeg: str | None = None, ffprobe: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1, "status": "ok", "tools": {}, "checks": {},
        "optional_analysis": {},
        "limitations": [
            "Filter and encoder listings establish advertised capabilities only; rendering was not tested.",
            "Optional CLI discovery does not verify its models, dependencies, or analysis quality.",
            "No network, account, API-key, login, visual, or listening checks were performed.",
        ],
    }
    selected = {}
    for name, explicit in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        requested, path = resolve_tool(explicit, "BAND_STUDIO_" + name.upper(), name)
        entry: dict[str, Any] = {"requested": requested, "path": path}
        if path is None:
            entry.update(status="missing", error="Executable not found or not executable")
        else:
            observed = observe_command([path, "-version"])
            entry.update({k: v for k, v in observed.items() if k != "output"})
            if observed["status"] == "observed":
                lines = observed["output"].splitlines()
                if not lines or not lines[0].lower().startswith(name + " version"):
                    entry.update(status="failed", error="Unexpected or empty version response")
                else:
                    entry["version"] = lines[0]
                    selected[name] = path
        report["tools"][name] = entry
        if entry["status"] != "observed":
            report["status"] = "failed"

    for group, flag, required in (("filters", "-filters", REQUIRED_FILTERS),
                                   ("encoders", "-encoders", REQUIRED_ENCODERS)):
        if "ffmpeg" not in selected:
            report["checks"][group] = {"status": "unavailable", "required": list(required)}
            continue
        observed = observe_command([selected["ffmpeg"], "-hide_banner", flag])
        if observed["status"] != "observed":
            report["checks"][group] = {k: v for k, v in observed.items() if k != "output"}
            report["status"] = "failed"
            continue
        names = table_names(observed["output"])
        available = {name: name in names for name in required}
        missing = [name for name, found in available.items() if not found]
        report["checks"][group] = {"status": "missing" if missing else "observed",
                                   "available": available, "missing": missing}
        if missing:
            report["status"] = "failed"

    for name in OPTIONAL_ANALYSIS_COMMANDS:
        path = shutil.which(name)
        report["optional_analysis"][name] = {
            "status": "discovered" if path else "not_found", "path": path,
            "execution_tested": False,
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", help="Executable path or command name")
    parser.add_argument("--ffprobe", help="Executable path or command name")
    args = parser.parse_args(argv)
    report = diagnose(args.ffmpeg, args.ffprobe)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
