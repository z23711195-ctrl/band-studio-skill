"""Synthetic and mocked checks; no private media or service credentials required."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "band-studio" / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


doctor = load("doctor")
verify_delivery = load("verify_delivery")
FILTERS = "Filters:\n TS ass V->V render\n .. subtitles V->V render\n T.C drawtext V->V render\n"
ENCODERS = "Encoders:\n V....D libx264 H.264\n A..... aac AAC\n"
GOOD_SRT = "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n\n2\n00:00:01,000 --> 00:00:02,000\nSecond cue\n"


def which(name):
    return "/mock/" + name if name in ("ffmpeg", "ffprobe") else None


def command_ok(command, **kwargs):
    if "-filters" in command:
        output = FILTERS
    elif "-encoders" in command:
        output = ENCODERS
    else:
        output = Path(command[0]).name + " version test-build\n"
    return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")


def probe_ok(command, **kwargs):
    data = {"format": {"duration": "3.0"}, "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 640,
         "height": 360, "duration": "3.0", "pix_fmt": "yuv420p"},
        {"index": 1, "codec_type": "audio", "codec_name": "aac"}]}
    return subprocess.CompletedProcess(command, 0, stdout=json.dumps(data), stderr="")


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(doctor.os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_missing_tools_nonzero_json(self):
        with patch.object(doctor.shutil, "which", return_value=None), io.StringIO() as stdout:
            with contextlib.redirect_stdout(stdout):
                code = doctor.main([])
            data = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(data["tools"]["ffmpeg"]["status"], "missing")
        self.assertEqual(data["checks"]["filters"]["status"], "unavailable")

    def test_observed_capabilities(self):
        with patch.object(doctor.shutil, "which", side_effect=which), \
             patch.object(doctor.subprocess, "run", side_effect=command_ok) as run:
            data = doctor.diagnose()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(all(data["checks"]["filters"]["available"].values()))
        self.assertFalse(data["optional_analysis"]["whisper"]["execution_tested"])
        self.assertTrue(all(call.kwargs["timeout"] == 15 for call in run.call_args_list))
        self.assertTrue(all("shell" not in call.kwargs for call in run.call_args_list))

    def test_subprocess_failure(self):
        failed = subprocess.CompletedProcess([], 3, stdout="", stderr="synthetic failure")
        with patch.object(doctor.shutil, "which", side_effect=which), \
             patch.object(doctor.subprocess, "run", return_value=failed):
            data = doctor.diagnose()
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["tools"]["ffmpeg"]["returncode"], 3)

    def test_timeout(self):
        with patch.object(doctor.shutil, "which", side_effect=which), \
             patch.object(doctor.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 15)):
            data = doctor.diagnose()
        self.assertEqual(data["tools"]["ffprobe"]["status"], "timeout")
        self.assertEqual(data["status"], "failed")

    def test_os_error(self):
        with patch.object(doctor.subprocess, "run", side_effect=PermissionError("denied")):
            self.assertEqual(doctor.observe_command(["test"])["status"], "failed")

    def test_empty_version_not_success(self):
        result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(doctor.shutil, "which", side_effect=which), \
             patch.object(doctor.subprocess, "run", return_value=result):
            self.assertEqual(doctor.diagnose()["status"], "failed")

    def test_exact_filter_names(self):
        def command(command, **kwargs):
            result = command_ok(command, **kwargs)
            if "-filters" in command:
                result.stdout = result.stdout.replace("subtitles ", "subtitles_other ")
            return result
        with patch.object(doctor.shutil, "which", side_effect=which), \
             patch.object(doctor.subprocess, "run", side_effect=command):
            data = doctor.diagnose()
        self.assertEqual(data["checks"]["filters"]["missing"], ["subtitles"])
        self.assertEqual(data["status"], "failed")

    def test_filter_command_failure(self):
        def command(command, **kwargs):
            if "-filters" in command:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="list failed")
            return command_ok(command, **kwargs)
        with patch.object(doctor.shutil, "which", side_effect=which), \
             patch.object(doctor.subprocess, "run", side_effect=command):
            self.assertEqual(doctor.diagnose()["checks"]["filters"]["status"], "failed")

    def test_explicit_over_environment_over_path(self):
        with patch.dict(doctor.os.environ, {"BAND_STUDIO_FFMPEG": "/env/ffmpeg"}), \
             patch.object(doctor.shutil, "which", side_effect=lambda value: value):
            self.assertEqual(doctor.resolve_tool("/chosen/ffmpeg", "BAND_STUDIO_FFMPEG", "ffmpeg")[0], "/chosen/ffmpeg")
            self.assertEqual(doctor.resolve_tool(None, "BAND_STUDIO_FFMPEG", "ffmpeg")[0], "/env/ffmpeg")


class SrtTests(unittest.TestCase):
    def codes(self, text, duration=3.0):
        return {e["code"] for e in verify_delivery.validate_srt(text, duration)["errors"]}

    def test_valid_unicode_bom_and_crlf(self):
        data = verify_delivery.validate_srt("\ufeff" + GOOD_SRT.replace("\n", "\r\n"), 3.0)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["cue_count"], 2)

    def test_negative_and_invalid_timestamps(self):
        for timestamp in ("-00:00:01,000", "00:60:00,000", "00:00:99,000"):
            with self.subTest(timestamp=timestamp):
                self.assertIn("invalid_time", self.codes(GOOD_SRT.replace("00:00:00,000", timestamp)))

    def test_empty_text_and_file(self):
        self.assertIn("empty_srt", self.codes(" \n"))
        self.assertIn("empty_or_invalid_text", self.codes("1\n00:00:00,000 --> 00:00:01,000\n<i></i>"))

    def test_overlap(self):
        self.assertIn("overlap", self.codes(GOOD_SRT.replace("00:00:01,000 -->", "00:00:00,900 -->")))

    def test_out_of_order(self):
        text = "1\n00:00:02,000 --> 00:00:03,000\nA\n\n2\n00:00:00,000 --> 00:00:01,000\nB"
        self.assertIn("time_order", self.codes(text))

    def test_out_of_bounds(self):
        self.assertIn("out_of_bounds", self.codes(GOOD_SRT, 1.5))

    def test_zero_duration(self):
        self.assertIn("invalid_duration", self.codes("1\n00:00:01,000 --> 00:00:01,000\nA"))

    def test_unknown_duration(self):
        self.assertIn("unknown_video_duration", self.codes(GOOD_SRT, None))

    def test_bad_or_duplicate_index(self):
        self.assertIn("invalid_index", self.codes("A\n00:00:00,000 --> 00:00:01,000\ntext"))
        self.assertIn("index_order", self.codes(GOOD_SRT.replace("\n\n2\n", "\n\n1\n")))


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.video = self.directory / "fixture.mp4"
        self.video.write_bytes(b"mock-only fixture")
        self.srt = self.directory / "fixture.srt"
        self.srt.write_text(GOOD_SRT, encoding="utf-8")
        environment = patch.dict(verify_delivery.os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def run_verify(self, **kwargs):
        with patch.object(verify_delivery.shutil, "which", return_value="/mock/ffprobe"), \
             patch.object(verify_delivery.subprocess, "run", side_effect=probe_ok):
            return verify_delivery.verify(self.video, **kwargs)

    def test_valid_metadata_srt_and_expectations(self):
        data = self.run_verify(srt=self.srt, expect_duration=3, expect_width=640, expect_height=360)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["srt"]["cue_count"], 2)
        self.assertTrue(any("burned" in item for item in data["limitations"]))
        self.assertTrue(any("listening" in item for item in data["limitations"]))

    def test_duration_and_resolution_mismatch(self):
        data = self.run_verify(expect_duration=6, expect_width=1920, expect_height=1080)
        failed = {c["name"] for c in data["checks"] if c["status"] == "failed"}
        self.assertTrue({"expected_duration", "expected_width", "expected_height"}.issubset(failed))

    def test_bad_srt_fails_delivery(self):
        self.srt.write_text("1\n00:00:04,000 --> 00:00:05,000\nLate", encoding="utf-8")
        self.assertEqual(self.run_verify(srt=self.srt)["status"], "failed")

    def test_missing_video_or_tool(self):
        with patch.object(verify_delivery.shutil, "which", return_value=None), \
             patch.object(verify_delivery.subprocess, "run") as run:
            data = verify_delivery.verify(self.directory / "missing.mp4")
        self.assertEqual(data["status"], "failed")
        run.assert_not_called()

    def test_failed_probe(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="bad input")
        with patch.object(verify_delivery.shutil, "which", return_value="/mock/ffprobe"), \
             patch.object(verify_delivery.subprocess, "run", return_value=result):
            data = verify_delivery.verify(self.video)
        self.assertEqual(data["status"], "failed")

    def test_probe_timeout(self):
        with patch.object(verify_delivery.shutil, "which", return_value="/mock/ffprobe"), \
             patch.object(verify_delivery.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 30)):
            data = verify_delivery.verify(self.video)
        self.assertEqual(data["status"], "failed")
        self.assertTrue(any(c.get("error") == "FFprobe timed out" for c in data["checks"]))

    def test_invalid_json(self):
        with patch.object(verify_delivery.shutil, "which", return_value="/mock/ffprobe"), \
             patch.object(verify_delivery.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="not json", stderr="")):
            self.assertEqual(verify_delivery.verify(self.video)["status"], "failed")

    def test_unknown_duration_rejects_srt_bounds(self):
        result = subprocess.CompletedProcess([], 0, stderr="", stdout=json.dumps({"streams": [
            {"codec_type": "video", "width": 640, "height": 360}], "format": {"duration": "NaN"}}))
        with patch.object(verify_delivery.shutil, "which", return_value="/mock/ffprobe"), \
             patch.object(verify_delivery.subprocess, "run", return_value=result):
            data = verify_delivery.verify(self.video, srt=self.srt)
        self.assertEqual(data["status"], "failed")
        self.assertTrue(any(e["code"] == "unknown_video_duration" for e in data["srt"]["errors"]))

    def test_nonfinite_cli_expectations_rejected(self):
        for value in ("nan", "inf", "-1", "0"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    verify_delivery.main([str(self.video), "--expect-duration", value])
                self.assertEqual(error.exception.code, 2)

    def test_main_nonzero_is_json(self):
        with patch.object(verify_delivery.shutil, "which", return_value=None), io.StringIO() as stdout:
            with contextlib.redirect_stdout(stdout):
                code = verify_delivery.main([str(self.video)])
            self.assertEqual(json.loads(stdout.getvalue())["status"], "failed")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
