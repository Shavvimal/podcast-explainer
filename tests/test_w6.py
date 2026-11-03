"""Unit-style tests for the W6 fixes. Run from the skill folder:

    python3 -m unittest discover -s tests -v

Standard library only. No network, no Gemini call: the API is replaced by fakes. ffmpeg is
needed only by the hash-dedupe test (it assembles a tiny episode).
"""
from __future__ import annotations

import array
import copy
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pe_common as pc  # noqa: E402

DUMMY_KEY = "AIzaDUMMYdummyDUMMYdummyDUMMYdummy12345"  # fake, shaped like a Google key


def quiet(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rv = fn(*a, **k)
        except SystemExit as e:
            rv = e.code
    return rv, out.getvalue(), err.getvalue()


# ------------------------------------------------------------------------------------- C01 / C03

class KeyRedaction(unittest.TestCase):
    def setUp(self):
        pc.register_secret(DUMMY_KEY)

    def test_reflected_key_in_http_error_body_is_redacted(self):
        import tts
        body = json.dumps({"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                     "message": f"API key not valid: {DUMMY_KEY} (x-goog-api-key: {DUMMY_KEY})"}}).encode()
        err = urllib.error.HTTPError("https://example.invalid", 400, "Bad", {}, io.BytesIO(body))
        msg, _ = tts.http_error_detail(err)
        self.assertNotIn(DUMMY_KEY, msg)
        self.assertIn("<redacted>", msg)

    def test_non_json_error_body_is_redacted(self):
        import tts
        err = urllib.error.HTTPError("https://example.invalid", 502, "Bad", {}, io.BytesIO(f"proxy saw key={DUMMY_KEY}".encode()))
        msg, _ = tts.http_error_detail(err)
        self.assertNotIn(DUMMY_KEY, msg)

    def test_synth_failure_message_and_logs_never_hold_the_key(self):
        import tts

        def fake_post(key, model, body, timeout):
            raise urllib.error.HTTPError("u", 403, "x", {}, io.BytesIO(
                json.dumps({"error": {"status": "PERMISSION_DENIED", "message": f"bad key {key}"}}).encode()))

        unit = {"id": "t01", "turns": [{"id": "t01"}], "texts": ["Hello there, how are you."], "styles": [""],
                "voice": "Kore", "engine": "gemini-3.8-flash-tts"}
        with mock.patch.object(tts, "post_json", fake_post):
            with self.assertRaises(tts.TtsError) as cm:
                tts.synth_api(DUMMY_KEY, {"speakers": []}, unit, 1, 1.0, 0.5, 2.5)
        self.assertNotIn(DUMMY_KEY, str(cm.exception))
        rv, out, err = quiet(tts.die, f"failed: {cm.exception} {DUMMY_KEY}")
        self.assertNotIn(DUMMY_KEY, out + err)

    def test_key_with_newline_is_rejected_before_any_header_and_error_hides_it(self):
        bad = "AIzaBAD\nInjected: yes" + "x" * 20
        with self.assertRaises(pc.KeyError_) as cm:
            pc.validate_key(bad)
        self.assertNotIn("AIzaBAD", str(cm.exception))
        import tts
        with self.assertRaises(pc.KeyError_):
            tts.post_json(bad, "m", {}, 1.0)

    def test_redact_obj_cleans_reports(self):
        rep = {"units": {"t01": {"error": f"HTTP 400: {DUMMY_KEY}", "calls": [{"error": f"key={DUMMY_KEY}"}]}}}
        self.assertNotIn(DUMMY_KEY, json.dumps(pc.redact_obj(rep)))

    def test_preflight_scrubs_reflected_key(self):
        import preflight

        def fake_urlopen(req, timeout=0):
            raise urllib.error.HTTPError("u", 400, "x", {}, io.BytesIO(
                json.dumps({"error": {"message": f"API key not valid {DUMMY_KEY}", "details": [{"reason": "API_KEY_INVALID"}]}}).encode()))

        t = preflight.Table()
        with mock.patch.object(preflight.urllib.request, "urlopen", fake_urlopen):
            preflight.check_gemini(t, DUMMY_KEY, "env", False, False)
        self.assertNotIn(DUMMY_KEY, json.dumps(t.rows))

    def test_dotenv_quoted_value_with_comment(self):
        self.assertEqual(pc.parse_env_value('"dummy-key" # development'), "dummy-key")
        self.assertEqual(pc.parse_env_value("'dummy-key'"), "dummy-key")
        self.assertEqual(pc.parse_env_value("dummy-key # note"), "dummy-key")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / ".env"
            f.write_text('OTHER=1\nexport GEMINI_API_KEY="AIzaDUMMYquotedDUMMYquotedDUMMY12345" # dev\n')
            self.assertEqual(pc.read_env_file(f), "AIzaDUMMYquotedDUMMYquotedDUMMY12345")


# ------------------------------------------------------------------------------------- C02

class SlugContainment(unittest.TestCase):
    def test_bad_ids_rejected(self):
        for bad in ("../outside", "a/b", "A", "x..y", "", "-x"):
            with self.assertRaises(pc.BadId):
                pc.check_id(bad, "slug")
        for bad in ("../t01", "t1", "turn01"):
            with self.assertRaises(pc.BadId):
                pc.check_id(bad, "turn")
        with self.assertRaises(pc.BadId):
            pc.check_id("../../etc/x", "voice")
        self.assertEqual(pc.check_id("hash-maps", "slug"), "hash-maps")

    def test_symlink_escape_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            ws, outside = Path(td) / "ws", Path(td) / "outside"
            ws.mkdir()
            outside.mkdir()
            (ws / "evil").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(pc.BadId):
                pc.episode_dir(ws, "evil")
            (ws / "good").mkdir()
            self.assertEqual(pc.episode_dir(ws, "good"), (ws / "good").resolve())

    def test_cli_boundaries_reject_traversal(self):
        import build_manifest
        import learn
        import qc
        import transcript
        with tempfile.TemporaryDirectory() as td:
            args = mock.Mock(workspace=td, slug="../outside", remotion_dir=None, placeholder_timing=True,
                             auto_chips=False, tail_ms=None, no_sync=True)
            rv, _, err = quiet(build_manifest.build, args)
            self.assertEqual(rv, 2)
            rv, _, err = quiet(transcript.main, ["--workspace", td, "--slug", "../outside"])
            self.assertEqual(rv, 1)
            self.assertIn("invalid slug", err)
            rv, _, err = quiet(learn.main, ["--workspace", td, "--slug", "../outside"])
            self.assertEqual(rv, 1)
            rv, _, err = quiet(qc.main, ["probe", "--workspace", td, "--slug", "../outside"])
            self.assertEqual(rv, 1)

    def test_tts_rejects_bad_turn_id_and_voice(self):
        import tts
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            script = {"speakers": [{"id": "host", "voice": "Kore"}],
                      "segments": [{"id": "seg01", "turns": [{"id": "../../x", "speaker": "host", "text": "Hi there."}]}]}
            (ep / "script.json").write_text(json.dumps(script))
            with self.assertRaises(tts.TtsError):
                tts.load_script(ep)
            args = mock.Mock(audition="../../evil", audition_text="Hi", dry_run=True, model="m")
            with self.assertRaises(tts.TtsError):
                tts.audition(ep, script, args)


# ------------------------------------------------------------------------------------- B01

class AlignmentFidelity(unittest.TestCase):
    def test_never_helps_lookup_is_a_critical_fail(self):
        r = pc.turn_fidelity("Doubling helps lookup.", "Doubling never helps lookup.")
        self.assertEqual(r["status"], "fail")
        self.assertEqual(r["insertions"], 1)
        self.assertTrue(any("never" in c for c in r["critical"]))

    def test_both_directions_and_numbers(self):
        r = pc.turn_fidelity("Adding a server moves 3 keys.", "Adding a server moves keys.")
        self.assertEqual((r["status"], r["deletions"]), ("fail", 1))
        r = pc.turn_fidelity("Adding a server moves 3 keys.", "Adding a server moves 30 keys.")
        self.assertEqual((r["status"], r["substitutions"]), ("fail", 1))
        r = pc.turn_fidelity("It is not cached.", "It is cached.")
        self.assertEqual(r["status"], "fail")

    def test_equivalent_spellings_pass(self):
        self.assertEqual(pc.turn_fidelity("It keeps 100 to 200 replicas, 5 to 10 percent.", "It keeps 100-200 replicas, 5-10%.")["status"], "ok")
        self.assertEqual(pc.turn_fidelity("It doesn't move twenty-five keys.", "It does not move 25 keys")["status"], "ok")
        self.assertEqual(pc.turn_fidelity("Two seems small.", "to seem small")["status"], "ok")  # homophone; seem/seems is a spelling slip
        self.assertEqual(pc.turn_fidelity("A hash map works.", "A hashmap works.")["status"], "ok")

    def test_episode_gate_accept_binds_to_take_and_flags_stale_and_draft(self):
        script = {"segments": [{"id": "seg01", "turns": [{"id": "t01", "text": "Doubling helps lookup."},
                                                          {"id": "t02", "text": "Right."}]}]}
        timing = {"alignment": {"engine": "whisper.cpp"}, "turns": [
            {"id": "t01", "audioSha": "aaa", "alignedAudioSha": "aaa", "words": [{"text": "x"}],
             "asr": [{"text": "Doubling"}, {"text": "never"}, {"text": "helps"}, {"text": "lookup."}]},
            {"id": "t02", "audioSha": "bbb", "alignedAudioSha": "bbb", "words": [{"text": "x"}], "asr": [{"text": "Right."}]}]}
        rep = pc.episode_fidelity(script, timing)
        self.assertEqual((rep["blocking"], rep["ok"]), (1, False))
        rep = pc.episode_fidelity(script, timing, {"accept": [{"turn": "t01", "audioSha": "OLD", "reason": "x"}]})
        self.assertEqual(rep["blocking"], 1, "an acceptance for another take does not count")
        rep = pc.episode_fidelity(script, timing, {"accept": [{"turn": "t01", "audioSha": "aaa", "text": "Doubling helps lookup.", "reason": "listened"}]})
        self.assertEqual((rep["blocking"], rep["ok"]), (0, True))
        stale = copy.deepcopy(timing)
        stale["turns"][1]["audioSha"] = "new-take"
        self.assertEqual(pc.episode_fidelity(script, stale)["counts"]["stale"], 1)
        draft = copy.deepcopy(timing)
        draft["alignment"]["engine"] = "estimated"
        for t in draft["turns"]:
            t.pop("asr")
        rep = pc.episode_fidelity(script, draft)
        self.assertTrue(rep["draft"])
        self.assertFalse(rep["ok"])


# ------------------------------------------------------------------------------------- B04 / B09

def tone_wav(seconds: float, freq: float = 220.0) -> bytes:
    sr = 24000
    a = array.array("h", [int(8000 * math.sin(2 * math.pi * freq * i / sr)) for i in range(int(sr * seconds))])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())
    return buf.getvalue()


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg needed")
class HashDedupe(unittest.TestCase):
    def _episode(self, td: Path) -> Path:
        ep = td / "dup"
        ep.mkdir()
        script = {"speakers": [{"id": "host", "name": "Maya", "voice": "Kore"}, {"id": "guest", "name": "Theo", "voice": "Puck"}],
                  "segments": [{"id": "seg01", "turns": [
                      {"id": "t01", "speaker": "host", "text": "Why does that happen?"},
                      {"id": "t02", "speaker": "guest", "text": "Because the table doubles."},
                      {"id": "t03", "speaker": "host", "text": "Why does that happen?"}]}]}
        (ep / "script.json").write_text(json.dumps(script))
        return ep

    def test_identical_turns_make_one_call(self):
        import tts
        calls = []

        def fake_synth(key, script, unit, *a):
            calls.append(unit["id"])
            return tone_wav(1.2), {"finishReason": "STOP", "attempts": 1, "calls": [], "speechS": 1.2}

        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"GEMINI_API_KEY": DUMMY_KEY}):
            ep = self._episode(Path(td))
            with mock.patch.object(tts, "synth_api", fake_synth), mock.patch.object(sys, "argv", ["tts.py", str(ep), "--no-normalize", "--workers", "4"]):
                rv, out, err = quiet(tts.main)
            self.assertEqual(rv, 0, err)
            self.assertEqual(len(calls), 2, f"t01 and t03 share one take, got calls {calls}")
            timing = json.loads((ep / "timing.json").read_text())
            sha = {t["id"]: t["audioSha"] for t in timing["turns"]}
            self.assertEqual(sha["t01"], sha["t03"])
            self.assertFalse(list((ep / "audio" / "cache").glob("*.part")))

    def test_failure_with_queued_jobs_reports_the_turn_not_a_cancellation(self):
        import tts

        def fake_synth(key, script, unit, *a):
            raise tts.TtsError(f"{unit['id']}: failed after 1 tries: finishReason OTHER")

        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"GEMINI_API_KEY": DUMMY_KEY}):
            ep = self._episode(Path(td))
            with mock.patch.object(tts, "synth_api", fake_synth), mock.patch.object(sys, "argv", ["tts.py", str(ep), "--workers", "1"]):
                rv, out, err = quiet(tts.main)
            self.assertEqual(rv, 1)
            self.assertIn("stopped, nothing assembled", err)
            self.assertNotIn("CancelledError", err)


# ------------------------------------------------------------------------------------- A02 / A01

class SeriesPartsMapping(unittest.TestCase):
    def test_parts_becomes_of(self):
        import transcript
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            ep = ws / "s-p2"
            ep.mkdir()
            script = {"id": "s-p2", "title": "T", "series": {"id": "test-series", "part": 2, "parts": 3},
                      "speakers": [{"id": "host", "name": "Maya", "role": "learner"}],
                      "segments": [{"id": "seg01", "role": "hook", "turns": [{"id": "t01", "speaker": "host", "text": "Hi |oh| there <short pause> now."}]}]}
            timing = {"durationMs": 2000, "mode": "per-turn", "turns": [{"id": "t01", "startMs": 250, "endMs": 1500}]}
            (ep / "script.json").write_text(json.dumps(script))
            (ep / "timing.json").write_text(json.dumps(timing))
            args = mock.Mock(tags=None, depth=None, series=None, part=None, date="2026-11-02", mp4=None)
            e = transcript.build_episode(ws, "s-p2", args, None)
            self.assertEqual(e["series"], {"id": "test-series", "part": 2, "of": 3})
            self.assertEqual(e["chapters"][0]["turns"][0]["text"], "Hi there now.", "per-turn backchannel is not spoken")

    def test_scripts_compile_on_python_310_and_311(self):
        for exe in ("python3.10", "python3.11"):
            if not shutil.which(exe):
                continue
            for f in sorted(SCRIPTS.glob("*.py")):
                r = subprocess.run([exe, "-c", f"import ast; ast.parse(open({str(f)!r}).read())"], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{exe} {f.name}: {r.stderr[-300:]}")


# ------------------------------------------------------------------------------------- B07 / B06

class AnchorsAndVisibility(unittest.TestCase):
    def test_punctuation_only_anchor_word_is_an_error(self):
        import build_manifest as bm
        turn = {"id": "t01", "text": "Does it work? Yes.", "startMs": 0, "endMs": 1000,
                "words": [{"text": "Does", "startMs": 0, "endMs": 200}, {"text": "it", "startMs": 200, "endMs": 300},
                          {"text": "work?", "startMs": 300, "endMs": 600}, {"text": "Yes.", "startMs": 700, "endMs": 1000}]}
        probs = bm.Problems()
        ms = bm.Resolver({"t01": turn}).point({"turn": "t01", "word": "?", "edge": "end"}, "scene s01", probs)
        self.assertIsNone(ms)
        self.assertTrue(any("no letters or digits" in e for e in probs.errors))
        probs = bm.Problems()
        self.assertEqual(bm.Resolver({"t01": turn}).point({"turn": "t01", "word": "work"}, "s", probs), 300)

    def test_future_step_text_is_not_visible_now(self):
        m = {"scenes": [{"id": "s1", "type": "world", "startMs": 0, "endMs": 30000,
                         "props": {"steps": [{"atMs": 0, "note": "start"}, {"atMs": 20000, "set": {"n1": {"value": "100", "label": "future"}}}]}}],
             "world": {"nodes": [{"id": "n1", "label": "box", "revealAtMs": 0}, {"id": "n2", "label": "later", "revealAtMs": 25000}], "edges": []},
             "overlays": []}
        now = pc.visible_text(m, 0, 1000)
        self.assertNotIn("100", now)
        self.assertNotIn("future", now)
        self.assertNotIn("later", now)
        self.assertIn("100", pc.visible_text(m, 19000, 21000))
        check = {"scenes": [{"id": "c", "type": "check", "startMs": 0, "endMs": 9000,
                             "props": {"question": "Why?", "answer": "Because", "answerAtMs": 8000}}], "overlays": []}
        self.assertNotIn("Because", pc.visible_text(check, 0, 5000))
        self.assertIn("Because", pc.visible_text(check, 0, 8500))


# ------------------------------------------------------------------------------------- B08

class GapLogRefresh(unittest.TestCase):
    def test_timestamp_moves_and_learner_cells_survive(self):
        import learn
        lj = {"title": "T", "gapLog": [{"question": "Why 1/n?", "turn": "t05", "where": "seg03"}]}
        ctx1 = {"times": {("g", 1): 1000}, "start_of": {"t05": 1000, "t09": 2000}}
        seeded = learn.render_gaplog(lj, ctx1, None)
        self.assertIn("[00:01] (t05)", seeded)
        # Priya edits the seed row status and adds their own row citing t09
        edited = seeded.replace("| open |", "| closed | by rewatch |").rstrip("\n") + \
            "\n| 2026-11-03 | My own question | seg04 | [00:02] (t09) | open | |\n"
        ctx2 = {"times": {("g", 1): 61000}, "start_of": {"t05": 61000, "t09": 125000}}
        out = learn.render_gaplog(lj, ctx2, edited)
        self.assertIn("[01:01] (t05)", out)
        self.assertNotIn("[00:01]", out)
        self.assertIn("[02:05] (t09)", out)
        self.assertIn("closed", out)
        self.assertIn("My own question", out)
        # an old row without a turn tag is matched to its seed by question text
        legacy = seeded.replace("[00:01] (t05)", "[00:01]")
        self.assertIn("[01:01] (t05)", learn.render_gaplog(lj, ctx2, legacy))


# ------------------------------------------------------------------------------------- E11 / D03

class ValidatorRules(unittest.TestCase):
    def _run(self, data, facts=None, minutes=2.5):
        import validate_script as vs
        rep = vs.Report("x")
        vs.check_script(data, facts, minutes, 45, "per-turn", rep, None)
        return rep

    def _sample(self):
        return json.loads((SKILL / "evals" / "files" / "sample-script.json").read_text())

    def _facts(self):
        return json.loads((SKILL / "evals" / "files" / "sample-facts.json").read_text())

    def test_e11_spoken_colon_is_fine_speaker_prefix_is_not(self):
        data = self._sample()
        names = [s["name"] for s in data["speakers"]]
        t = data["segments"][-1]["turns"][-1]
        t["text"] = "So the opening puzzle: what moves when a server joins?"
        self.assertFalse([p for p in self._run(data, self._facts()).errors if p["code"] == "E11"])
        t["text"] = f"{names[0]}: what moves when a server joins?"
        self.assertTrue([p for p in self._run(data, self._facts()).errors if p["code"] == "E11"])
        t["text"] = "Host: what moves when a server joins?"
        self.assertTrue([p for p in self._run(data, self._facts()).errors if p["code"] == "E11"])

    def test_hollow_lesson_fails(self):
        data = self._sample()
        data.pop("targetMinutes", None)
        for seg in data["segments"]:
            for t in seg["turns"]:
                t["text"] = "How does the mechanism work? The mechanism works because it works."
                for k in ("onScreen", "factIds", "pause", "holdAfterMs"):
                    t.pop(k, None)
        rep = self._run(data, self._facts(), minutes=None)
        codes = {p["code"] for p in rep.errors}
        for c in ("E06", "E07", "E09", "E23", "E25"):
            self.assertIn(c, codes, f"{c} missing; errors: {sorted(codes)}")
        self.assertIn("W26", {p["code"] for p in rep.warnings})

    def test_sample_still_passes(self):
        rep = self._run(self._sample(), self._facts(), minutes=self._sample().get("targetMinutes", 2.5))
        self.assertEqual(rep.errors, [])


# ------------------------------------------------------------------------------------- run-log 2

class RestateQuestion(unittest.TestCase):
    def test_last_retrieve_prompt_not_last_question(self):
        import qc
        ep = mock.Mock()
        ep.script = {"segments": [
            {"id": "seg05", "role": "misconception", "turns": [{"id": "t34", "text": "So which keys move?",
                                                                 "pause": {"kind": "retrieve", "prompt": "Which keys move when D joins?"}}]},
            {"id": "seg08", "role": "selftest", "turns": [{"id": "t72", "text": "And for next time: how would you pick three servers?"}]}]}
        ep._load = lambda name: {}
        self.assertEqual(qc.restate_question(ep), "Which keys move when D joins?")


if __name__ == "__main__":
    unittest.main()
