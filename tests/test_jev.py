"""Offline Jev contract checks using synthetic text and mocked HTTP only."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request


SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "band-studio" / "scripts" / "jev.py"
SPEC = importlib.util.spec_from_file_location("band_jev", SCRIPT)
jev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jev)

FAKE_KEY = "synthetic-test-key-never-a-real-credential"
RANK = {
    "brief": "Keep the supplied rhythmic motif; compare text proposals only.",
    "candidates": [
        {"id": "a", "summary": "A short syncopated guitar motif.", "evidence": "Supplied rehearsal note."},
        {"id": "b", "summary": "A long ambient introduction."},
    ],
}
PREFLIGHT = {
    "requirements": [{"id": "keep_motif", "text": "Keep the supplied motif."}],
    "proposal": {"styles": "dry guitar, syncopated bass", "excluded_styles": "orchestra",
                 "lyrics": "", "instrumental": True, "source_attached": False},
}
EVIDENCE = {"claims": [{"id": "claim_1", "claim": "The artist approved this arrangement.",
                         "evidence": "No artist approval was supplied."}]}


def cloud_response(*_args, **_kwargs):
    """A synthetic rank result, never a real inference or provider observation."""
    answers = {}
    for candidate in ("a", "b"):
        answers["rank_" + candidate] = {
            "type": "score", "score": 2.7,
            "probabilities": {"0": 0.0, "1": 0.0, "2": 0.3, "3": 0.7},
            "confidence": 0.8,
        }
        answers["evidence_" + candidate] = {"type": "noul", "noul": 0.9}
    return {"model": "jev-test-1", "answers": answers,
            "usage": {"input_tokens": 100, "output_tokens": 20}}


def choice_response(request, *_args, selection="supported", **_kwargs):
    answers = {}
    for question_id, question in request["questions"].items():
        answers[question_id] = {
            "type": "choice", "choice": selection, "confidence": 0.9,
            "probabilities": {key: 0.9 if key == selection else 0.05 for key in question["criteria"]},
        }
    return {"model": "jev-test-1", "answers": answers,
            "usage": {"input_tokens": 50, "output_tokens": 10}}


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = io.BytesIO(payload)
        self.status = 200

    def read(self, size=-1):
        return self.payload.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.payload.close()


class JevTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.cache = self.base / "cache"
        self.counter = 0
        environment = patch.dict(jev.os.environ, {"HOME": str(self.base)}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        home = patch.object(Path, "home", return_value=self.base)
        home.start()
        self.addCleanup(home.stop)
        network = patch.object(
            urllib.request.OpenerDirector, "open",
            side_effect=AssertionError("An offline test tried to use the network"),
        )
        self.network = network.start()
        self.addCleanup(network.stop)

    def invoke(self, mode="rank", data=None, options=(), raw=None, output=None):
        self.counter += 1
        source = self.base / f"input-{self.counter}.json"
        source.write_bytes(raw if raw is not None else json.dumps(
            RANK if data is None else data, ensure_ascii=False,
        ).encode("utf-8"))
        destination = output or self.base / f"output-{self.counter}.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = [mode, "--input", str(source), "--output", str(destination),
                     "--cache-dir", str(self.cache), *options]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = jev.main(arguments)
        result = json.loads(destination.read_text()) if destination.exists() else None
        return code, result, source, stdout.getvalue() + stderr.getvalue()

    def config(self, name, value):
        file = self.base / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(value), encoding="utf-8")
        return file

    def assert_private(self, report, console=""):
        text = json.dumps(report, ensure_ascii=False) + console
        self.assertNotIn(FAKE_KEY, text)

    def test_default_dry_run_never_calls_network_even_with_credentials(self):
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}):
            code, report, _, console = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(report["network_calls"], 0)
        self.network.assert_not_called()
        self.assert_private(report, console)

    def test_execute_without_credentials_defers_without_network(self):
        code, report, _, _ = self.invoke(options=["--execute"])
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "deferred")
        self.assertEqual(report["network_calls"], 0)
        self.network.assert_not_called()

    def test_all_modes_can_be_planned_without_cloud_access(self):
        for mode, data in (("rank", RANK), ("preflight", PREFLIGHT), ("evidence", EVIDENCE)):
            with self.subTest(mode=mode):
                code, report, _, _ = self.invoke(mode, data)
                self.assertEqual(code, 0)
                self.assertEqual(report["status"], "dry_run")
                self.assertEqual(report["network_calls"], 0)
        self.network.assert_not_called()

    def test_unknown_fields_and_duplicate_or_unsafe_ids_are_rejected(self):
        variants = []
        extra = copy.deepcopy(RANK)
        extra["api_key"] = FAKE_KEY
        variants.append(extra)
        extra_candidate = copy.deepcopy(RANK)
        extra_candidate["candidates"][0]["audio_path"] = "recording.wav"
        variants.append(extra_candidate)
        duplicated = copy.deepcopy(RANK)
        duplicated["candidates"][1]["id"] = "a"
        variants.append(duplicated)
        for invalid_id in ("../escape", "a\nb", "", "has space"):
            unsafe = copy.deepcopy(RANK)
            unsafe["candidates"][0]["id"] = invalid_id
            variants.append(unsafe)
        for data in variants:
            with self.subTest(data=data):
                code, report, _, console = self.invoke(data=data, options=["--execute"])
                self.assertEqual(code, 2)
                self.assert_private(report, console)
        self.network.assert_not_called()

    def test_wrong_types_and_unknown_mode_specific_fields_are_rejected(self):
        variants = [
            ("rank", {"brief": "test", "candidates": [{"id": "a", "summary": True}]}),
            ("rank", {"brief": "test", "candidates": []}),
            ("preflight", {**PREFLIGHT, "proposal": {**PREFLIGHT["proposal"], "instrumental": "true"}}),
            ("preflight", {**PREFLIGHT, "proposal": {**PREFLIGHT["proposal"], "unexpected": "x"}}),
            ("evidence", {"claims": [{"id": "c", "claim": "text", "evidence": ["text"]}]}),
            ("evidence", {**EVIDENCE, "audio": "anything.wav"}),
        ]
        for mode, data in variants:
            with self.subTest(mode=mode, data=data):
                code, _, _, _ = self.invoke(mode, data)
                self.assertEqual(code, 2)
        self.network.assert_not_called()

    def test_candidate_and_input_size_limits_are_enforced_before_network(self):
        too_many = {"brief": "test", "candidates": [
            {"id": f"c{n}", "summary": "candidate"} for n in range(25)
        ]}
        for data in (too_many, {"brief": "x" * 65536, "candidates": RANK["candidates"]}):
            with self.subTest(size=len(json.dumps(data))):
                code, _, _, _ = self.invoke(data=data, options=["--execute"])
                self.assertEqual(code, 2)
        self.network.assert_not_called()

    def test_binary_invalid_json_and_duplicate_json_keys_are_rejected(self):
        for raw in (b"\x00\xff\xfeaudio", b"not json", b'{"brief":"one","brief":"two","candidates":[]}'):
            with self.subTest(raw=raw):
                code, _, _, _ = self.invoke(raw=raw, options=["--execute"])
                self.assertEqual(code, 2)
        self.network.assert_not_called()

    def test_existing_output_is_preserved_and_source_is_unchanged(self):
        destination = self.base / "existing.json"
        original = b'{"keep":"original"}\n'
        destination.write_bytes(original)
        before = destination.stat().st_mtime_ns
        code, _, source, _ = self.invoke(output=destination)
        self.assertEqual(code, 2)
        self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(destination.stat().st_mtime_ns, before)
        self.assertEqual(json.loads(source.read_text()), RANK)
        self.network.assert_not_called()

    def test_output_cannot_replace_input_or_follow_an_existing_symlink(self):
        source = self.base / "source.json"
        source.write_text(json.dumps(RANK), encoding="utf-8")
        original = (source.read_bytes(), source.stat().st_mtime_ns)
        link = self.base / "linked-output.json"
        link.symlink_to(source)
        for output in (source, link):
            with self.subTest(output=output.name), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(jev.main(["rank", "--input", str(source), "--output", str(output)]), 2)
                self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), original)
        self.network.assert_not_called()

    def test_text_reference_does_not_open_or_modify_media(self):
        media = self.base / "unread.wav"
        media.write_bytes(b"synthetic-media-never-upload-this")
        original = (media.read_bytes(), media.stat().st_mtime_ns)
        data = copy.deepcopy(RANK)
        data["candidates"][0]["evidence"] = str(media)
        open_original = Path.open

        def guard(path, *args, **kwargs):
            self.assertNotEqual(path, media, "Text references must not cause media access")
            return open_original(path, *args, **kwargs)

        with patch.object(Path, "open", guard):
            code, _, _, _ = self.invoke(data=data)
        self.assertEqual(code, 0)
        self.assertEqual((media.read_bytes(), media.stat().st_mtime_ns), original)

    def test_success_calls_cloud_once_with_timeout_and_redacts_key(self):
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            code, report, _, console = self.invoke(options=["--execute"])
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["network_calls"], 1)
        request.assert_called_once()
        self.assertIn(25, [*request.call_args.args, *request.call_args.kwargs.values()])
        self.assert_private(report, console)

    def test_identical_content_uses_cache_with_no_second_network_call(self):
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            code, first, _, _ = self.invoke(options=["--execute"])
            self.assertEqual(code, 0)
            request.reset_mock()
            code, second, _, _ = self.invoke(options=["--execute"])
        self.assertEqual(code, 0)
        request.assert_not_called()
        self.assertEqual(first["network_calls"], 1)
        self.assertEqual(second["network_calls"], 0)
        self.assertEqual(first["source"], "network")
        self.assertEqual(second["source"], "cache")
        self.assertEqual(first["usage"], {"input_tokens": 100, "output_tokens": 20})
        self.assertEqual(second["usage"], {"input_tokens": 0, "output_tokens": 0})
        self.assertEqual(second["stored_usage"], first["usage"])
        self.assertEqual(first["results"], second["results"])
        self.assert_private(second)

    def test_input_and_model_changes_invalidate_cache(self):
        changed = copy.deepcopy(RANK)
        changed["brief"] += " Keep the ending short."
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            self.assertEqual(self.invoke(options=["--execute"])[0], 0)
            self.assertEqual(self.invoke(data=changed, options=["--execute"])[0], 0)
            self.assertEqual(self.invoke(options=["--execute", "--model", "jev-other-test"])[0], 0)
        self.assertEqual(request.call_count, 3)

    def test_changed_question_definition_invalidates_cache(self):
        build = jev.build_request

        def changed_request(*args, **kwargs):
            request = build(*args, **kwargs)
            questions = request["questions"]
            if isinstance(questions, dict):
                first = next(iter(questions.values()))
            else:
                first = questions[0]
            # This changes the requested judgment while preserving IDs and response shape.
            first["instructions"] += " Additional test criterion."
            return request

        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            self.assertEqual(self.invoke(options=["--execute"])[0], 0)
            request.reset_mock()
            with patch.object(jev, "build_request", side_effect=changed_request):
                self.assertEqual(self.invoke(options=["--execute"])[0], 0)
            request.assert_called_once()

    def test_no_cache_skips_read_and_write(self):
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            for _ in range(2):
                code, report, _, _ = self.invoke(options=["--execute", "--no-cache"])
                self.assertEqual(code, 0)
                self.assertEqual(report["network_calls"], 1)
        self.assertEqual(request.call_count, 2)
        self.assertFalse(self.cache.exists() and list(self.cache.iterdir()))

    def test_expired_or_corrupt_cache_requires_a_fresh_call(self):
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            with patch.object(jev.time, "time", return_value=100000.0):
                self.assertEqual(self.invoke(options=["--execute"])[0], 0)
            request.reset_mock()
            with patch.object(jev.time, "time", return_value=100000.0 + 86401.0):
                self.assertEqual(self.invoke(options=["--execute"])[0], 0)
                request.assert_called_once()
            cached_files = list(self.cache.glob("*.json"))
            self.assertTrue(cached_files)
            for file in cached_files:
                file.write_text("invalid cache JSON", encoding="utf-8")
            request.reset_mock()
            self.assertEqual(self.invoke(options=["--execute"])[0], 0)
            request.assert_called_once()

    def test_malformed_cloud_results_are_deferred_and_not_cached(self):
        responses = []
        for bad_value in (float("nan"), float("inf"), True, -0.1, 1.1):
            value = cloud_response()
            value["answers"]["evidence_a"]["noul"] = bad_value
            responses.append(value)
        for bad_score in (True, float("nan"), -1, 4):
            value = cloud_response()
            value["answers"]["rank_a"]["score"] = bad_score
            responses.append(value)
        for probabilities in ({"0": 0.2, "1": 0.2, "2": 0.2, "3": 0.2},
                              {"0": False, "1": 0, "2": 0.3, "3": 0.7},
                              {"0": 0, "1": 0, "2": float("nan"), "3": 0.7}):
            value = cloud_response()
            value["answers"]["rank_a"]["probabilities"] = probabilities
            responses.append(value)
        missing = cloud_response()
        del missing["answers"]["rank_a"]
        responses.append(missing)
        extra = cloud_response()
        extra["answers"]["unknown_question"] = {"type": "noul", "noul": 0.9}
        responses.append(extra)
        for usage in ({"input_tokens": True, "output_tokens": 20},
                      {"input_tokens": -1, "output_tokens": 20},
                      {"input_tokens": 1, "output_tokens": float("nan")}):
            invalid_usage = cloud_response()
            invalid_usage["usage"] = usage
            responses.append(invalid_usage)
        responses.extend([{}, {"answers": []}, None])
        for index, response in enumerate(responses):
            with self.subTest(index=index), patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
                 patch.object(jev, "perform_request", return_value=response) as request:
                code, report, _, console = self.invoke(options=["--execute"])
                self.assertEqual(code, 3)
                self.assertEqual(report["status"], "deferred")
                self.assertEqual(report["network_calls"], 1)
                request.assert_called_once()
                self.assertFalse(list(self.cache.glob("*.json")))
                self.assert_private(report, console)

    def test_transport_errors_are_safe_deferred_without_retry(self):
        failures = [
            (urllib.error.HTTPError("https://example.invalid/" + FAKE_KEY, status, FAKE_KEY,
                                    {"Location": "https://redirect.invalid/" + FAKE_KEY},
                                    io.BytesIO(FAKE_KEY.encode())), "http_" + str(status))
            for status in (401, 403, 429, 529, 302)
        ]
        failures.extend([(TimeoutError(FAKE_KEY), "network_failure"),
                         (urllib.error.URLError(TimeoutError(FAKE_KEY)), "network_failure")])
        for index, (failure, reason) in enumerate(failures):
            with self.subTest(index=index), patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
                 patch.object(urllib.request.OpenerDirector, "open", side_effect=failure) as request:
                code, report, _, console = self.invoke(options=["--execute"])
            self.assertEqual(code, 3)
            self.assertEqual(report["status"], "deferred")
            self.assertEqual(report["reason"], reason)
            self.assertEqual(report["network_calls"], 1)
            request.assert_called_once()
            self.assertFalse(list(self.cache.glob("*.json")))
            self.assert_private(report, console)

    def test_key_priority_is_environment_then_explicit_env_then_config_env(self):
        explicit = self.base / "explicit.env"
        explicit.write_text("TYPESAFE_API_KEY=synthetic-explicit-key\n", encoding="utf-8")
        configured = self.base / "configured.env"
        configured.write_text("TYPESAFE_API_KEY=synthetic-config-key\n", encoding="utf-8")
        config = self.config("settings.json", {"env_file": str(configured), "model": "jev-latest"})
        cases = [
            ({"TYPESAFE_API_KEY": FAKE_KEY}, ["--env-file", str(explicit)], FAKE_KEY),
            ({}, ["--env-file", str(explicit)], "synthetic-explicit-key"),
            ({}, [], "synthetic-config-key"),
        ]
        for environment, extra, expected in cases:
            with self.subTest(expected=expected), patch.dict(jev.os.environ, environment), \
                 patch.object(jev, "perform_request", side_effect=cloud_response) as request:
                code, report, _, console = self.invoke(options=[
                    "--execute", "--no-cache", "--config", str(config), *extra,
                ])
            self.assertEqual(code, 0)
            request.assert_called_once()
            self.assertIn(expected, [*request.call_args.args, *request.call_args.kwargs.values()])
            self.assertNotIn(expected, json.dumps(report) + console)

    def test_default_local_config_reuses_existing_env_file_without_shell_execution(self):
        private_env = self.base / "private.env"
        marker = self.base / "must-not-exist"
        private_env.write_text(
            "TYPESAFE_API_KEY='synthetic-default-key'\n"
            + "UNRELATED=$(touch " + str(marker) + ")\n", encoding="utf-8",
        )
        self.config(".config/band-studio/jev.json", {"env_file": str(private_env), "model": "jev-pinned-test"})
        with patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            code, report, _, console = self.invoke(options=["--execute"])
        self.assertEqual(code, 0)
        request.assert_called_once()
        values = [*request.call_args.args, *request.call_args.kwargs.values()]
        self.assertIn("synthetic-default-key", values)
        self.assertTrue(any(isinstance(value, dict) and value.get("model") == "jev-pinned-test" for value in values))
        self.assertFalse(marker.exists())
        self.assertNotIn("synthetic-default-key", json.dumps(report) + console)

    def test_explicit_model_overrides_config(self):
        config = self.config("settings.json", {"model": "jev-config-test"})
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            code, _, _, _ = self.invoke(options=[
                "--execute", "--config", str(config), "--model", "jev-explicit-test",
            ])
        self.assertEqual(code, 0)
        values = [*request.call_args.args, *request.call_args.kwargs.values()]
        self.assertTrue(any(isinstance(value, dict) and value.get("model") == "jev-explicit-test" for value in values))

    def test_config_does_not_accept_embedded_secrets_or_extra_fields(self):
        for value in ({"api_key": FAKE_KEY}, {"env_file": None, "command": "anything"}):
            config = self.config("bad-config.json", value)
            code, report, _, console = self.invoke(options=["--config", str(config), "--execute"])
            self.assertEqual(code, 2)
            self.assert_private(report, console)
        self.network.assert_not_called()

    def test_transport_posts_json_once_and_disables_redirects(self):
        response = FakeHTTPResponse(json.dumps(cloud_response()).encode("utf-8"))
        build_opener = urllib.request.build_opener
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(urllib.request, "build_opener", wraps=build_opener) as build, \
             patch.object(urllib.request.OpenerDirector, "open", return_value=response) as request:
            code, report, _, console = self.invoke(options=["--execute"])
        self.assertEqual(code, 0)
        request.assert_called_once()
        http_request = request.call_args.args[0]
        self.assertEqual(http_request.get_method(), "POST")
        self.assertEqual(http_request.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(http_request.get_header("Authorization"), "Bearer " + FAKE_KEY)
        self.assertEqual(request.call_args.kwargs["timeout"], 25)
        payload = json.loads(http_request.data)
        self.assertEqual(payload["state"], RANK)
        self.assertEqual(len(payload["questions"]), 4)
        self.assertNotIn(FAKE_KEY, http_request.data.decode())
        redirect_handler = next(
            handler for handler in build.call_args.args
            if isinstance(handler, urllib.request.HTTPRedirectHandler)
        )
        for status in (301, 302, 303, 307, 308):
            self.assertIsNone(redirect_handler.redirect_request(
                http_request, None, status, "redirect", {}, "https://other.invalid/",
            ))
        self.assert_private(report, console)

    def test_invalid_http_json_is_deferred_without_caching(self):
        for raw in (b"not json", b'{"model":"a","model":"b"}', b'{"value":NaN}',
                    b"x" * (1024 * 1024 + 1)):
            with self.subTest(length=len(raw)), patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
                 patch.object(urllib.request.OpenerDirector, "open", return_value=FakeHTTPResponse(raw)) as request:
                code, report, _, _ = self.invoke(options=["--execute"])
            self.assertEqual(code, 3)
            self.assertEqual(report["status"], "deferred")
            request.assert_called_once()
            self.assertFalse(list(self.cache.glob("*.json")))

    def test_preflight_scope_and_conflicts_are_reported_without_claiming_media_verification(self):
        for observed in (False, True):
            for selection in ("supported", "conflicting", "unknown"):
                data = copy.deepcopy(PREFLIGHT)
                if observed:
                    data["observed"] = {"source_attached": False}
                with self.subTest(observed=observed, selection=selection), \
                     patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
                     patch.object(jev, "perform_request", side_effect=lambda *args, **kwargs: choice_response(
                         *args, selection=selection, **kwargs,
                     )):
                    code, report, _, _ = self.invoke("preflight", data, ["--execute", "--no-cache"])
                self.assertEqual(code, 0)
                self.assertTrue(report["advisory_only"])
                self.assertEqual(report["review_scope"], "observed_fields" if observed else "planned_fields")
                self.assertEqual(report["results"][0]["review"], selection != "supported")
                self.assertEqual(report["assessment"],
                                 "no_text_conflicts_detected" if selection == "supported" else "review_required")

    def test_evidence_requires_review_for_contradiction_and_insufficient_support(self):
        for selection in ("supported", "contradicted", "insufficient"):
            with self.subTest(selection=selection), patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
                 patch.object(jev, "perform_request", side_effect=lambda *args, **kwargs: choice_response(
                     *args, selection=selection, **kwargs,
                 )):
                code, report, _, _ = self.invoke("evidence", EVIDENCE, ["--execute", "--no-cache"])
            self.assertEqual(code, 0)
            self.assertTrue(report["advisory_only"])
            self.assertEqual(report["results"][0]["answer"]["choice"], selection)
            self.assertEqual(report["results"][0]["review"], selection != "supported")

    def test_choice_that_disagrees_with_probabilities_is_not_success(self):
        request = jev.build_request("preflight", PREFLIGHT)
        raw = choice_response(request)
        raw["answers"]["preflight_keep_motif"]["choice"] = "conflicting"
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", return_value=raw):
            code, report, _, _ = self.invoke("preflight", PREFLIGHT, ["--execute"])
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "deferred")
        self.assertFalse(list(self.cache.glob("*.json")))

    def test_cache_contains_no_source_text_and_revalidates_stored_response(self):
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            self.assertEqual(self.invoke(options=["--execute"])[0], 0)
            cached_files = list(self.cache.glob("*.json"))
            self.assertEqual(len(cached_files), 1)
            text = cached_files[0].read_text()
            self.assertNotIn(RANK["brief"], text)
            self.assertNotIn(RANK["candidates"][0]["summary"], text)
            self.assertNotIn(FAKE_KEY, text)
            cache = json.loads(text)
            cache["response"]["answers"]["evidence_a"]["noul"] = True
            cached_files[0].write_text(json.dumps(cache), encoding="utf-8")
            request.reset_mock()
            code, report, _, _ = self.invoke(options=["--execute"])
            self.assertEqual(code, 0)
            self.assertEqual(report["source"], "network")
            request.assert_called_once()

    def test_environment_key_and_explicit_model_ignore_missing_lower_priority_env_file(self):
        config = self.config("stale-config.json", {"env_file": str(self.base / "missing-private.env")})
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=cloud_response) as request:
            code, report, _, _ = self.invoke(options=[
                "--execute", "--config", str(config), "--model", "jev-explicit-test",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(report["requested_model"], "jev-explicit-test")
        request.assert_called_once()
        self.assert_private(report)

    def test_dry_run_does_not_require_valid_credentials_or_unused_env_file(self):
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": "invalid\ncredential"}):
            code, report, _, _ = self.invoke(options=[
                "--model", "jev-explicit-test", "--env-file", str(self.base / "missing-private.env"),
            ])
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(report["network_calls"], 0)
        self.network.assert_not_called()

    def test_unexpected_service_error_is_safe_deferred(self):
        with patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}), \
             patch.object(jev, "perform_request", side_effect=RuntimeError(FAKE_KEY)) as request:
            code, report, _, console = self.invoke(options=["--execute"])
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "deferred")
        self.assertEqual(report["reason"], "service_failure")
        request.assert_called_once()
        self.assert_private(report, console)

    def test_invalid_timeout_is_rejected_without_network(self):
        for value in ("0", "-1", "nan", "inf", "301"):
            with self.subTest(timeout=value), patch.dict(jev.os.environ, {"TYPESAFE_API_KEY": FAKE_KEY}):
                code, report, _, _ = self.invoke(options=["--execute", "--timeout", value])
            self.assertEqual(code, 2)
            self.assertEqual(report["network_calls"], 0)
        self.network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
