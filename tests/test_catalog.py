"""Offline behavior checks; no user media, browser or provider is required."""

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "band-studio" / "scripts" / "catalog.py"
SPEC = importlib.util.spec_from_file_location("band_catalog", SCRIPT)
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "input"
        self.source.mkdir()
        self.output = self.base / "output"

    def put(self, relative, payload=b"fixture"):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_unicode_and_hash_duplicates_are_preserved_as_relative_references(self):
        self.put("排练/动机 一.M4A", b"same recording bytes")
        self.put("副本.wav", b"same recording bytes")
        self.put("notes.txt", "歌词测试".encode())
        result = catalog.build_catalog(self.source, self.output, hash_files=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"]["files"], 3)
        groups = result["duplicate_detection"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["copy_count"], 2)
        self.assertEqual(groups[0]["sha256"], hashlib.sha256(b"same recording bytes").hexdigest())
        text = (self.output / "catalog.json").read_text()
        self.assertNotIn(str(self.source), text)
        self.assertIn("排练/动机 一.M4A", text)
        self.assertNotIn("歌词测试", text)
        with (self.output / "catalog.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["listening"] == "not_performed" for row in rows))

    def test_no_hash_does_not_claim_deduplication(self):
        self.put("one.mp3")
        self.put("two.mp3")
        result = catalog.build_catalog(self.source, self.output)
        self.assertEqual(result["duplicate_detection"]["status"], "not_requested")
        self.assertEqual(result["duplicate_detection"]["groups"], [])
        self.assertTrue(all("sha256" not in item for item in result["assets"]))

    def test_skips_hidden_symlinks_credentials_dependencies_and_unknown_types(self):
        good = self.put("valid.mp3")
        for name in (".hidden.mp3", ".cache/clip.mp4", "node_modules/file.mp3", "venv/file.txt",
                     "secrets/song.wav", "api_keys.txt", "密码.txt", "data.exe", "info.json"):
            self.put(name)
        (self.source / "linked.mp3").symlink_to(good)
        external = self.base / "external"
        external.mkdir()
        (external / "external.mp3").write_bytes(b"external")
        (self.source / "linked-directory").symlink_to(external, target_is_directory=True)
        result = catalog.build_catalog(self.source, self.output)
        self.assertEqual([item["relative_path"] for item in result["assets"]], ["valid.mp3"])

    def test_existing_output_is_rejected_without_writing(self):
        self.put("one.mp3")
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            catalog.build_catalog(self.source, self.output)
        self.assertEqual(list(self.output.iterdir()), [marker])
        self.assertEqual(marker.read_text(), "keep")

    def test_output_inside_input_does_not_inventory_itself(self):
        self.put("notes.txt")
        inside = self.source / "new" / "inventory"
        result = catalog.build_catalog(self.source, inside)
        self.assertEqual([item["relative_path"] for item in result["assets"]], ["notes.txt"])
        self.assertTrue((inside / "catalog.json").is_file())

    def test_source_bytes_and_mtime_are_unchanged(self):
        source = self.put("source.wav", b"original audio")
        before = (source.read_bytes(), source.stat().st_mtime_ns)
        catalog.build_catalog(self.source, self.output, hash_files=True)
        after = (source.read_bytes(), source.stat().st_mtime_ns)
        self.assertEqual(before, after)
        self.assertEqual(list(self.source.iterdir()), [source])

    def test_probe_failure_is_recorded_per_asset_and_counted(self):
        self.put("failure.wav")
        self.put("still_indexed.txt")
        completed = subprocess.CompletedProcess(["ffprobe"], 7, stdout="", stderr="private /Users/example/key")
        with patch.object(catalog.subprocess, "run", return_value=completed) as run:
            result = catalog.build_catalog(self.source, self.output, probe=True, timeout=3)
        run.assert_called_once()
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertIsInstance(run.call_args.args[0], list)
        self.assertEqual(result["status"], "completed_with_errors")
        self.assertEqual(result["summary"]["files"], 2)
        self.assertEqual(result["summary"]["files_with_errors"], 1)
        self.assertEqual(result["summary"]["errors"], 1)
        self.assertNotIn("/Users/example", json.dumps(result))
        self.assertEqual(result["assets"][0]["errors"][0]["returncode"], 7)

    def test_probe_sanitizes_fake_ffprobe_metadata_and_only_probes_av(self):
        self.put("a.mov")
        self.put("cover.png")
        self.put("lyrics.docx", b"do not read")
        raw = {
            "format": {"filename": "/Users/private/song.mov", "duration": "2.5", "format_name": "mov,mp4",
                       "tags": {"comment": "a secret"}, "bit_rate": "123"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                         "avg_frame_rate": "30000/1001", "tags": {"artist": "Private Person"},
                         "side_data_list": [{"data": "private"}]},
                        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2,
                         "duration": "2.5", "title": "private"},
                        {"codec_type": "subtitle", "tags": {"comment": "private"}}],
        }
        completed = subprocess.CompletedProcess(["ffprobe"], 0, stdout=json.dumps(raw), stderr="")
        with patch.object(catalog.subprocess, "run", return_value=completed) as run:
            result = catalog.build_catalog(self.source, self.output, probe=True, ffprobe="custom-ffprobe")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], "custom-ffprobe")
        metadata = result["assets"][0]["metadata"]
        self.assertEqual(metadata["format"], {"format_name": "mov,mp4", "duration_seconds": 2.5})
        self.assertEqual(metadata["streams"][0]["width"], 1920)
        self.assertAlmostEqual(metadata["streams"][0]["average_frame_rate"], 30000 / 1001)
        self.assertEqual(metadata["streams"][1]["sample_rate"], 48000)
        serialized = json.dumps(result)
        for forbidden in ("/Users/private", "Private Person", "a secret", "side_data_list", "do not read"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(result["assets"][1]["probe_status"], "not_applicable")

    def test_probe_timeout_invalid_json_and_empty_streams_remain_errors(self):
        self.put("one.mp3")
        responses = [subprocess.TimeoutExpired(["ffprobe"], 2),
                     subprocess.CompletedProcess([], 0, stdout="not-json"),
                     subprocess.CompletedProcess([], 0, stdout='{"streams": []}')]
        codes = ["timeout", "invalid_metadata", "invalid_metadata"]
        for index, (response, code) in enumerate(zip(responses, codes)):
            with self.subTest(code=code, index=index):
                kwargs = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
                with patch.object(catalog.subprocess, "run", **kwargs):
                    result = catalog.build_catalog(self.source, self.base / f"out-{index}", probe=True)
                self.assertEqual(result["status"], "completed_with_errors")
                self.assertEqual(result["assets"][0]["errors"][0]["code"], code)

    def test_cli_error_exit_does_not_echo_input_paths(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = catalog.main([str(self.base / "missing"), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertNotIn(str(self.base), stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_cli_returns_nonzero_for_partial_probe_failure_and_summary(self):
        self.put("one.mp3")
        with patch.object(catalog.subprocess, "run", side_effect=FileNotFoundError("private path")):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = catalog.main([str(self.source), "--output", str(self.output), "--probe"])
        self.assertEqual(code, 1)
        summary = json.loads(stdout.getvalue())
        self.assertEqual(summary["status"], "completed_with_errors")
        self.assertEqual(summary["errors"], 1)

    def test_executable_precedence_for_cli_and_function(self):
        self.put("one.wav")
        completed = subprocess.CompletedProcess(
            [], 0, stdout='{"streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}]}'
        )
        cases = [
            ("environment-ffprobe", "argument-ffprobe", "argument-ffprobe"),
            ("environment-ffprobe", None, "environment-ffprobe"),
            ("", None, "ffprobe"),
        ]
        for entry in ("cli", "function"):
            for index, (environment, explicit, expected) in enumerate(cases):
                with self.subTest(entry=entry, expected=expected):
                    destination = self.base / f"precedence-{entry}-{index}"
                    with patch.dict(catalog.os.environ, {"BAND_STUDIO_FFPROBE": environment}):
                        with patch.object(catalog.subprocess, "run", return_value=completed) as run:
                            if entry == "cli":
                                arguments = [str(self.source), "--output", str(destination), "--probe"]
                                if explicit is not None:
                                    arguments.extend(["--ffprobe", explicit])
                                with redirect_stdout(io.StringIO()):
                                    self.assertEqual(catalog.main(arguments), 0)
                            else:
                                options = {} if explicit is None else {"ffprobe": explicit}
                                result = catalog.build_catalog(self.source, destination, probe=True, **options)
                                self.assertEqual(result["status"], "ok")
                    self.assertEqual(run.call_args.args[0][0], expected)

    def test_timeout_rejects_nonpositive_and_nonfinite_before_any_probe(self):
        self.put("one.wav")
        for index, value in enumerate((0, -1, float("nan"), float("inf"), float("-inf"))):
            with self.subTest(timeout=value):
                destination = self.base / f"invalid-timeout-{index}"
                with patch.object(catalog.subprocess, "run") as run:
                    with self.assertRaisesRegex(ValueError, "positive finite"):
                        catalog.build_catalog(self.source, destination, probe=True, timeout=value)
                run.assert_not_called()
                self.assertFalse(destination.exists())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(catalog.main([
                str(self.source), "--output", str(self.output), "--probe", "--timeout", "nan",
            ]), 2)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
