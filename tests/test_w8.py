"""Tests for the W8a fixes (codex round 2: N01, N03, N04, N06, N08, N09, N10, N11, A05, A09, B02,
B06, C02, D03, D04, E01 and the checks from the 2 Nov 2026 real run). Run from the skill folder:

    python3 -m unittest                       (all tests)
    python3 -m unittest tests.test_w8 -v      (these only)

Standard library only. No network and no Gemini call: the API is replaced by a fake. ffmpeg is
needed only by the duplicate-retake test (it assembles a tiny episode).
"""
from __future__ import annotations

import array
import copy
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
SCRIPTS = SKILL / "scripts"
EVALS = SKILL / "evals" / "files"
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


def sample_script() -> dict:
    return json.loads((EVALS / "sample-script.json").read_text())


def sample_timing(script: dict) -> dict:
    turns, t = [], 250
    for seg in script["segments"]:
        for tr in seg["turns"]:
            turns.append({"id": tr["id"], "speaker": tr["speaker"], "segment": seg["id"], "startMs": t, "endMs": t + 2000})
            t += 2250 + (tr.get("holdAfterMs") or 0)
    return {"version": 1, "mode": "per-turn", "durationMs": t + 600, "turns": turns}


# ------------------------------------------------------------------------------------- N03

class FidelityMeaning(unittest.TestCase):
    def test_signed_number_dropped_sign_fails(self):
        r = pc.turn_fidelity("The value is -5.", "The value is 5.")
        self.assertEqual(r["status"], "fail")
        self.assertTrue(any("minus" in c for c in r["critical"]))
        self.assertEqual(pc.turn_fidelity("It is negative 5.", "It is -5")["status"], "ok")
        self.assertEqual(pc.turn_fidelity("It is -5.", "It is minus five")["status"], "ok")

    def test_antonyms_fail(self):
        for a, b in (("That increases load.", "That decreases load."), ("The lookup returns false.", "The lookup returns true."),
                     ("It needs more servers.", "It needs less servers."), ("Hash before you store.", "Hash after you store."),
                     ("The keys grow.", "The keys shrink.")):
            r = pc.turn_fidelity(a, b)
            self.assertEqual(r["status"], "fail", f"{a} | {b}: {r}")

    def test_spoken_decimal_equals_digits(self):
        self.assertEqual(pc.turn_fidelity("The value is 0.75.", "The value is zero point seven five.")["status"], "ok")
        self.assertEqual(pc.turn_fidelity("Java's limit is 0.75.", "Java's limit is 0.75")["status"], "ok")
        self.assertEqual(pc.turn_fidelity("The value is 0.75.", "The value is 0.57.")["status"], "fail")

    def test_narrow_spelling_allowances_only(self):
        self.assertTrue(pc.similar("kubernetes", "kubernetis"))   # one slip, long word
        self.assertTrue(pc.similar("colour", "color"))
        self.assertTrue(pc.similar("normalise", "normalize"))
        self.assertTrue(pc.similar("seem", "seems"))
        self.assertFalse(pc.similar("increases", "decreases"))
        self.assertFalse(pc.similar("likely", "unlikely"))
        self.assertFalse(pc.similar("cash", "cache"))            # short words are not fuzzy
        self.assertTrue(set(pc.HOMOPHONES) >= {"2", "4", "1", "8"}, "the homophone list stays")

    def test_function_word_mishearing_is_only_a_warning(self):
        self.assertEqual(pc.turn_fidelity("It sits in the ring.", "It sits and the ring.")["status"], "warn")


# ------------------------------------------------------------------------------------- N04 / B02

class AcceptAndDeliveryMode(unittest.TestCase):
    def setUp(self):
        self.script = {"segments": [{"id": "seg01", "turns": [{"id": "t01", "text": "Adding a server moves 3 keys."}]}]}
        self.timing = {"mode": "per-turn", "alignment": {"engine": "whisper.cpp"}, "turns": [
            {"id": "t01", "audioSha": "aaa", "alignedAudioSha": "aaa", "words": [{"text": "x", "source": "asr"}],
             "asr": [{"text": w} for w in "Adding a server moves 30 keys.".split()]}]}
        self.ok_entry = {"turn": "t01", "audioSha": "aaa", "text": "Adding a server moves 3 keys.", "reason": "listened: says three"}

    def test_accept_binds_to_audio_text_and_reason(self):
        self.assertTrue(pc.episode_fidelity(self.script, self.timing, {"accept": [self.ok_entry]})["ok"])
        changed = copy.deepcopy(self.script)
        changed["segments"][0]["turns"][0]["text"] = "Adding a server moves 30 keys."
        changed["segments"][0]["turns"][0]["text"] = "Adding a server moves 4 keys."
        rep = pc.episode_fidelity(changed, self.timing, {"accept": [self.ok_entry]})
        self.assertFalse(rep["ok"], "an acceptance for the old text must not survive a script change")
        self.assertIn("text differs", " ".join(rep["turns"][0]["acceptProblems"]))
        no_reason = {**self.ok_entry, "reason": " "}
        self.assertFalse(pc.episode_fidelity(self.script, self.timing, {"accept": [no_reason]})["ok"])
        other_take = {**self.ok_entry, "audioSha": "bbb"}
        self.assertFalse(pc.episode_fidelity(self.script, self.timing, {"accept": [other_take]})["ok"])

    def test_draft_and_chunk_modes_are_rejected(self):
        good = copy.deepcopy(self.timing)
        good["turns"][0]["asr"] = [{"text": w} for w in "Adding a server moves 3 keys.".split()]
        self.assertTrue(pc.episode_fidelity(self.script, good)["ok"])
        for patch in ({"scratch": True}, {"mode": "chunk"}, {"experimental": True}, {"alignment": {"engine": "whisper.cpp", "draft": True}}):
            t = {**copy.deepcopy(good), **patch}
            rep = pc.episode_fidelity(self.script, t)
            self.assertFalse(rep["ok"], patch)
            self.assertTrue(rep["draft"], patch)
            self.assertTrue(rep["rejected"], patch)
        est = copy.deepcopy(good)
        est["turns"][0]["words"] = [{"text": "x", "source": "estimated"}]
        self.assertFalse(pc.episode_fidelity(self.script, est)["ok"])


# ------------------------------------------------------------------------------------- N06 / N01

class ProvenanceAndIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w8-prov-"))
        self.ws = self.tmp / "ws"
        self.ep = self.ws / "hash-maps"
        self.ep.mkdir(parents=True)
        script = sample_script()
        (self.ep / "script.json").write_text(json.dumps(script))
        (self.ep / "timing.json").write_text(json.dumps(sample_timing(script)))
        shutil.copy(EVALS / "sample-learn.json", self.ep / "learn.json")
        shutil.copy(EVALS / "sample-facts.json", self.ep / "facts.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self):
        import learn
        import transcript
        rv, out, err = quiet(learn.main, ["--workspace", str(self.ws), "--slug", "hash-maps"])
        self.assertEqual(rv, 0, err)
        rv, out, err = quiet(transcript.main, ["--workspace", str(self.ws), "--slug", "hash-maps", "--date", "2026-11-02"])
        self.assertEqual(rv, 0, err)

    def episode(self):
        import qc
        return qc.Episode(mock.Mock(workspace=str(self.ws), slug="hash-maps", mp4=None, remotion_dir=None))

    def test_stale_transcript_digest_fails_even_with_same_times(self):
        import qc
        self.build()
        self.assertEqual(qc.provenance_problems(self.episode()), [])
        prov = json.loads((self.ep / "transcript.json").read_text())["provenance"]
        self.assertEqual(prov["script"], pc.json_digest(self.ep / "script.json"))
        # new text, same start times: the codex N06 case
        s = json.loads((self.ep / "script.json").read_text())
        s["segments"][1]["turns"][0]["text"] += " Really."
        (self.ep / "script.json").write_text(json.dumps(s))
        probs = qc.provenance_problems(self.episode())
        self.assertTrue(any("transcript.json was built from another script" in p for p in probs), probs)
        self.assertTrue(any("learn/ files were built from another script" in p for p in probs), probs)

    def test_hand_edited_learn_file_is_caught(self):
        import qc
        self.build()
        (self.ep / "learn" / "selftest.md").write_text("edited\n")
        probs = qc.provenance_problems(self.episode())
        self.assertTrue(any("changed after learn.py" in p for p in probs), probs)

    def test_build_identity_covers_learn_facts_transcript_and_mp4(self):
        import qc
        self.build()
        base = qc.build_identity(self.episode())["id"]
        for name, change in (("learn.json", lambda d: d["selfTest"][0].update(question="Changed?")),
                             ("facts.json", lambda d: d.update(title="changed"))):
            p = self.ep / name
            old = p.read_text()
            d = json.loads(old)
            change(d)
            p.write_text(json.dumps(d))
            self.assertNotEqual(qc.build_identity(self.episode())["id"], base, name)
            p.write_text(old)
        self.assertEqual(qc.build_identity(self.episode())["id"], base)
        (self.ep / "learn" / "cards.md").write_text("x")
        self.assertNotEqual(qc.build_identity(self.episode())["id"], base, "learn output")
        self.build()
        (self.ep / "out").mkdir()
        (self.ep / "out" / "episode.mp4").write_bytes(b"before chapters")
        a = qc.build_identity(self.episode())["id"]
        (self.ep / "out" / "episode.mp4").write_bytes(b"after chapters")
        self.assertNotEqual(qc.build_identity(self.episode())["id"], a, "embedding chapters is a new build")

    def test_restate_brief_reads_the_real_held_out_question(self):
        import qc
        self.build()
        ep = self.episode()
        ep.qc.mkdir(exist_ok=True)
        text = qc.write_restate_brief(ep).read_text()
        self.assertIn("A robot logs sensor readings keyed by timestamp", text)  # the learn.json heldOut item (R05)
        self.assertIn("```json", text)
        self.assertEqual(qc.held_out_check(ep, True)[0]["status"], "pass")
        (self.ep / "learn.json").unlink()
        self.assertEqual(qc.held_out_check(self.episode(), True)[0]["status"], "fail")
        self.assertEqual(qc.held_out_check(self.episode(), False)[0]["status"], "warn")

    def test_judge_brief_is_read_only_and_has_j11(self):
        import qc
        ep = self.episode()
        ep.qc.mkdir(exist_ok=True)
        text = qc.write_judge_brief(ep, {"id": "abc123"}).read_text()
        self.assertIn("J11", text)
        self.assertIn("do NOT write any file", text)
        self.assertIn("parent agent writes", text)
        self.assertIn("cannot listen", text)


# ------------------------------------------------------------------------------------- N09 / D04

def good_scores(build: str = "b1") -> dict:
    """A valid qc/scores.json: judge fields, the judge's reply verbatim with its sha256, and the
    restater's fields with its reply verbatim (W11a, N09)."""
    import qc
    judge = {"build": build, "round": 1, "scores": {k: 8 for k in qc.RUBRIC_KEYS}, "j": {k: 4 for k in qc.J_IDS},
             "reasons": {k: "02:23 t16: quoted" for k in qc.RUBRIC_KEYS + qc.J_IDS}, "worst": ["seg03 t16 @ 02:23: x"],
             "heldOut": {"demonstrated": False, "case": "t06: \"two keys land in the same bucket\"",
                         "solution": "t07: \"the bucket keeps a short list and checks each key\"",
                         "evidence": "searched t01 to t16; no constant-hash case"}, "notes": []}
    jreply = "Scores below.\n```json\n" + json.dumps(judge) + "\n```\n"
    restate = {"score": 4, "summary": "Five sentences.", "gaps": [],
               "retrieval": {"answer": "It doubles and re-hashes.", "citations": ["[02:23]"]},
               "transfer": {"answer": "No: identical hashes stay together.", "citations": ["[02:10]", "t16"]}}
    rreply = "Restatement.\n```json\n" + json.dumps(restate) + "\n```"
    return {**judge, "judgeReply": jreply, "judgeReplySha256": pc.bytes_sha(jreply.encode(), 64),
            "restate": {**restate, "reply": rreply, "replySha256": pc.bytes_sha(rreply.encode(), 64)}}


class ScoresValidation(unittest.TestCase):
    def good(self) -> dict:
        return good_scores()

    def test_good_scores_pass(self):
        import qc
        self.assertEqual(qc.score_problems(self.good(), "b1"), [])

    def test_out_of_range_and_non_finite_fail(self):
        import qc
        for bad in (99, math.inf, math.nan, -1, True, "9"):
            sc = self.good()
            sc["scores"]["hook"] = bad
            self.assertTrue(qc.score_problems(sc, "b1"), f"hook={bad!r} must fail")
            sc = self.good()
            sc["j"]["J3"] = bad
            self.assertTrue(qc.score_problems(sc, "b1"), f"J3={bad!r} must fail")
        # NaN and Infinity also arrive through json.loads
        sc = json.loads(json.dumps(self.good()).replace('"hook": 8', '"hook": NaN'))
        self.assertTrue(qc.score_problems(sc, "b1"))

    def test_round_reasons_and_restater_are_required(self):
        import qc
        for mutate, word in ((lambda s: s.pop("round"), "round"), (lambda s: s["reasons"].pop("J11"), "reasons"),
                             (lambda s: s["reasons"].update(hook="looks good"), "reasons"),
                             (lambda s: s.pop("restate"), "restate"), (lambda s: s["restate"].update(score=3), "restate"),
                             (lambda s: s["j"].update(J11=3), "J11"), (lambda s: s.update(build="old"), "build")):
            sc = self.good()
            mutate(sc)
            probs = qc.score_problems(sc, "b1")
            self.assertTrue(probs and any(word in p for p in probs), f"{word}: {probs}")

    def test_qc_md_audio_line_is_numbers_only(self):
        text = (SKILL / "references" / "qc.md").read_text()
        row = next(l for l in text.splitlines() if l.startswith("| 8 | Audio"))
        self.assertNotIn("click", row.lower())
        self.assertNotIn("drift", row.lower())
        self.assertIn("listen.json", text)


# ------------------------------------------------------------------------------------- N08

def tone_wav(seconds: float, freq: float) -> bytes:
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
class DuplicateRetake(unittest.TestCase):
    def test_retake_of_one_duplicate_turn_leaves_the_other(self):
        import tts
        freq = [200.0]

        def fake_synth(key, script, unit, *a):
            freq[0] += 37.0  # every call is a different take
            return tone_wav(1.2, freq[0]), {"finishReason": "STOP", "attempts": 1, "calls": [], "speechS": 1.2}

        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"GEMINI_API_KEY": DUMMY_KEY}):
            ep = Path(td) / "dup"
            ep.mkdir()
            script = {"speakers": [{"id": "host", "name": "Maya", "voice": "Kore"}, {"id": "guest", "name": "Theo", "voice": "Puck"}],
                      "segments": [{"id": "seg01", "turns": [
                          {"id": "t01", "speaker": "host", "text": "Why does that happen?"},
                          {"id": "t02", "speaker": "guest", "text": "Because the table doubles."},
                          {"id": "t03", "speaker": "host", "text": "Why does that happen?"}]}]}
            (ep / "script.json").write_text(json.dumps(script))

            def run(*flags):
                with mock.patch.object(tts, "synth_api", fake_synth), mock.patch.object(sys, "argv", ["tts.py", str(ep), "--no-normalize", *flags]):
                    rv, out, err = quiet(tts.main)
                self.assertEqual(rv, 0, err)
                return {t["id"]: t["audioSha"] for t in json.loads((ep / "timing.json").read_text())["turns"]}, out + err

            first, _ = run()
            self.assertEqual(first["t01"], first["t03"])
            # pretend t03 was aligned, so we can see its words survive the retake of t01
            tdoc = json.loads((ep / "timing.json").read_text())
            for t in tdoc["turns"]:
                t["words"] = [{"text": "x", "startMs": t["startMs"], "endMs": t["endMs"], "source": "asr"}]
                t["alignedAudioSha"] = t["audioSha"]
            (ep / "timing.json").write_text(json.dumps(tdoc))
            second, err = run("--only", "t01", "--retake")
            self.assertNotEqual(second["t01"], first["t01"], "t01 got a new take")
            self.assertEqual(second["t03"], first["t03"], "t03 keeps its take")
            self.assertIn("pinned", err)
            self.assertIn("audio changed for 1 turn(s): t01", err)
            t03 = next(t for t in json.loads((ep / "timing.json").read_text())["turns"] if t["id"] == "t03")
            self.assertTrue(t03.get("words"), "t03 keeps its alignment")
            report = json.loads((ep / "audio" / "tts-report.json").read_text())
            self.assertEqual(report["changedTurns"], ["t01"])
            third, _ = run()  # a plain rerun keeps the pinned take
            self.assertEqual(third, second)


# ------------------------------------------------------------------------------------- C02

class SymlinkEscape(unittest.TestCase):
    def test_safe_path_refuses_links_inside_the_root(self):
        with tempfile.TemporaryDirectory() as td:
            root, outside = Path(td) / "ep", Path(td) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "audio").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(pc.BadId):
                pc.safe_path(root, root / "audio" / "cache")
            (root / "real").mkdir()
            (root / "real" / "link.wav").symlink_to(outside / "x.wav")
            with self.assertRaises(pc.BadId):
                pc.safe_path(root, root / "real" / "link.wav")
            with self.assertRaises(pc.BadId):
                pc.safe_path(root, root / ".." / "outside")
            self.assertEqual(pc.safe_path(root, root / "real" / "new.wav"), root.resolve() / "real" / "new.wav")

    def test_tts_refuses_a_linked_audio_folder(self):
        import tts
        with tempfile.TemporaryDirectory() as td:
            ep, outside = Path(td) / "ep", Path(td) / "outside"
            ep.mkdir()
            outside.mkdir()
            (ep / "script.json").write_text(json.dumps({"speakers": [{"id": "host", "name": "M", "voice": "Kore"}],
                                                        "segments": [{"id": "seg01", "turns": [{"id": "t01", "speaker": "host", "text": "Hi there."}]}]}))
            (ep / "audio").symlink_to(outside, target_is_directory=True)
            with mock.patch.object(sys, "argv", ["tts.py", str(ep), "--dry-run"]):
                rv, out, err = quiet(tts.main)
            self.assertNotEqual(rv, 0)
            self.assertIn("symbolic link", err)
            self.assertEqual(list(outside.iterdir()), [])

    def test_build_manifest_refuses_linked_assets(self):
        import build_manifest as bm
        ring = SKILL / "templates" / "remotion" / "sample-inputs" / "ring"
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            ep = ws / "sample-ring"
            ep.mkdir()
            for f in ("script.json", "scenes.json"):
                shutil.copy(ring / f, ep / f)
            secret = ws / "secret.txt"
            secret.write_text("not an asset")
            (ep / "img").mkdir()
            (ep / "img" / "leak.png").symlink_to(secret)
            remotion = ws / "remotion"
            (remotion / "public" / "episodes").mkdir(parents=True)
            (remotion / "package.json").write_text("{}")
            args = mock.Mock(workspace=str(ws), slug="sample-ring", remotion_dir=str(remotion), placeholder_timing=True,
                             auto_chips=False, tail_ms=None, no_sync=False)
            rv, out, err = quiet(bm.build, args)
            self.assertEqual(rv, 1, out + err)
            self.assertIn("symbolic link", err)
            self.assertFalse((remotion / "public" / "episodes" / "sample-ring" / "img" / "leak.png").exists())


# ------------------------------------------------------------------------------------- A09

class SceneEntrances(unittest.TestCase):
    def run_place(self, gap_ms: int, anchor_inside: bool = False):
        import build_manifest as bm
        turns = [{"id": "t01", "startMs": 0, "endMs": 3000}, {"id": "t02", "startMs": 3000 + gap_ms, "endMs": 6000 + gap_ms}]
        a = 4500 if anchor_inside else 3000 + gap_ms
        scenes = [{"id": "s1", "type": "title", "startMs": 0, "endMs": a}, {"id": "s2", "type": "diagram", "startMs": a, "endMs": 9000}]
        res = bm.place_entrances(scenes, turns)
        return scenes[1], res["overlaps"]

    def test_default_gap_shortens_the_entrance_so_speech_never_overlaps(self):
        import build_manifest as bm
        sc, overlaps = self.run_place(250)
        # W11a (A09 on frames): the start snaps to frame 90 (3000 ms), so all 7 frames fit before 3250 ms.
        self.assertEqual((sc["enterLeadMs"], sc["enterMs"]), (250, bm.ENTER_MS))
        self.assertEqual(overlaps, [])
        self.assertLessEqual(sc["startMs"] + sc["enterMs"], 3250)
        sc, overlaps = self.run_place(150)
        self.assertEqual((sc["enterLeadMs"], sc["enterMs"]), (150, 133), "a 150 ms gap fits 4 whole frames (133 ms)")
        sc, overlaps = self.run_place(600)
        self.assertEqual((sc["enterLeadMs"], sc["enterMs"]), (bm.ENTER_MS, bm.ENTER_MS))
        sc, overlaps = self.run_place(50)
        self.assertEqual(sc["enterMs"], 0, "a 50 ms silence is a cut, not a 50 ms flicker")
        self.assertEqual(overlaps, [])

    def test_anchor_inside_a_turn_cuts_in(self):
        # W11a (A09, codex round 3): "never overlaps" stays the contract, so an inside-speech anchor is a cut.
        sc, overlaps = self.run_place(250, anchor_inside=True)
        self.assertEqual(sc["enterMs"], 0)
        self.assertEqual(overlaps, [])

    def test_enter_ms_is_in_the_episode_schema(self):
        schema = json.loads((SKILL / "schemas" / "episode.schema.json").read_text())
        self.assertIn('"enterMs"', json.dumps(schema))


# ------------------------------------------------------------------------------------- B06

class VisibilityParity(unittest.TestCase):
    def test_hidden_node_does_not_count(self):
        m = {"world": {"nodes": [{"id": "a", "label": "server A", "revealAtMs": 0}], "edges": []},
             "scenes": [{"id": "s1", "type": "world", "startMs": 0, "endMs": 20000,
                         "props": {"steps": [{"atMs": 5000, "hide": ["a"]}]}}], "overlays": []}
        self.assertIn("server A", pc.visible_text(m, 0, 1000))
        self.assertNotIn("server A", pc.visible_text(m, 8000, 12000))
        self.assertIn("server A", pc.visible_text(m, 4000, 6000), "visible at the start of the window")

    def test_set_override_and_latest_note_only(self):
        m = {"world": {"nodes": [{"id": "a", "label": "A", "value": "3", "revealAtMs": 0}], "edges": []},
             "scenes": [{"id": "s1", "type": "world", "startMs": 0, "endMs": 20000,
                         "props": {"steps": [{"atMs": 0, "note": "first note"}, {"atMs": 5000, "set": {"a": {"value": "7"}}, "note": "second"}]}}],
             "overlays": []}
        late = pc.visible_text(m, 9000, 10000)
        self.assertIn("7", late)
        self.assertNotIn("first note", late)
        self.assertNotIn(" 3", " " + late)

    def test_compare_fill_cells_wait_for_their_cue_and_plain_cells_show(self):
        sc = {"id": "c1", "type": "compare", "startMs": 0, "endMs": 20000, "props": {
            "left": {"title": "mod N", "kind": "table", "columns": ["k0", "k1"],
                     "rows": [{"id": "r1", "label": "owner", "cells": ["B", "C"]}, {"id": "r2", "label": "keys", "cells": ["3", "4"]}],
                     "steps": [{"atMs": 8000, "fill": {"r1": [1]}}, {"atMs": 12000, "fill": {"r1": "all"}}]},
            "right": {"title": "ring", "kind": "text", "lines": [{"text": "late line", "atMs": 15000}]},
            "verdict": {"text": "ring wins", "atMs": 16000}}}
        m = {"scenes": [sc], "overlays": []}
        early = pc.visible_text(m, 0, 5000)
        self.assertIn("keys", early)
        self.assertIn("3", early, "an untimed cell shows at once (N02 rule)")
        self.assertNotIn("C", early.split())
        self.assertNotIn("late line", early)
        self.assertNotIn("ring wins", early)
        mid = pc.visible_text(m, 8500, 9000).split()
        self.assertIn("C", mid)
        self.assertNotIn("B", mid)
        self.assertIn("B", pc.visible_text(m, 12500, 13000).split())
        self.assertIn("ring wins", pc.visible_text(m, 16000, 17000))

    def test_build_manifest_uses_the_shared_function(self):
        src = (SCRIPTS / "build_manifest.py").read_text()
        self.assertIn("pc.visible_text(", src)
        self.assertIn("pc.visible_text(", (SCRIPTS / "qc.py").read_text())
        self.assertIn("visibilityAt", (SCRIPTS / "pe_common.py").read_text(), "the parity list names the TS functions")


# ------------------------------------------------------------------------------------- D03 and the real-run checks

class TeachingChecks(unittest.TestCase):
    def run_v(self, data, facts=None, minutes=2.5, outline=None):
        import validate_script as vs
        rep = vs.Report("x")
        vs.check_script(data, facts, minutes, 45, "per-turn", rep, None, outline)
        return {p["code"] for p in rep.errors}, {p["code"] for p in rep.warnings}

    def facts(self):
        return json.loads((EVALS / "sample-facts.json").read_text())

    def test_tautology_lesson_now_fails(self):
        import validate_script as vs
        data = sample_script()
        n = 0
        for seg in data["segments"]:
            for t in seg["turns"]:
                t["text"] = "How does the mechanism work? The mechanism works because it works."
                t["onScreen"] = ["mechanism"]
                t["factIds"] = []
                n += 1
        hold = sum(t.get("holdAfterMs", 0) for s in data["segments"] for t in s["turns"]) / 1000
        minutes = (n * 12 * vs.SECS_PER_WORD + hold) / 60  # a matching duration, as in the codex input
        errors, _ = self.run_v(data, None, minutes)
        for code in ("E27", "E28", "E29"):
            self.assertIn(code, errors, f"{code} missing: {sorted(errors)}")
        rv, out, _ = quiet(vs.main, [str(self._write(data)), "--minutes", f"{minutes:.3f}"])
        self.assertEqual(rv, 1)
        self.assertIn("RESULT: FAIL", out)

    def _write(self, data) -> Path:
        d = Path(tempfile.mkdtemp(prefix="w8-taut-"))
        self.addCleanup(shutil.rmtree, d, True)
        p = d / "script.json"
        p.write_text(json.dumps(data))
        return p

    def test_sample_and_real_shape_pass(self):
        errors, warnings = self.run_v(sample_script(), self.facts(), sample_script()["targetMinutes"])
        self.assertEqual(errors, set())

    def test_onscreen_only_number_in_example_is_an_error(self):
        data = sample_script()
        seg = next(s for s in data["segments"] if s["role"] == "mechanism")
        seg["turns"][1]["onScreen"] = ["load factor", "0.75", "slot 9"]
        seg["turns"][1]["text"] += " Slot 9 here."
        errors, _ = self.run_v(data, self.facts())
        self.assertNotIn("E34", errors)
        seg["turns"][1]["text"] = seg["turns"][1]["text"].replace(" Slot 9 here.", "")
        seg["turns"][1]["onScreen"] = ["load factor", "0.75", "slot"]
        seg["turns"][1]["onScreen"].append("key at 9")
        errors, warnings = self.run_v(data, self.facts())
        self.assertIn("E34", errors)

    def test_case_without_general_rule(self):
        data = sample_script()
        outline = {"segments": [{"id": "seg03", "requireGeneralRule": True}]}
        seg = next(s for s in data["segments"] if s["id"] == "seg03")
        has_rule = any(re.search(r"on average", t["text"]) for t in seg["turns"])
        errors, warnings = self.run_v(data, self.facts(), outline=outline)
        if has_rule:
            self.assertNotIn("E33", errors)
        for t in seg["turns"]:
            t["text"] = t["text"].replace("on average", "then")
        errors, warnings = self.run_v(data, self.facts(), outline=outline)
        self.assertIn("E33", errors)
        errors, warnings = self.run_v(data, self.facts())
        self.assertIn("W33", warnings)

    def test_core_segment_needs_a_hold_before_an_answer(self):
        data = sample_script()
        outline = {"segments": [{"id": "seg03", "coreSegment": True}]}
        errors, _ = self.run_v(data, self.facts(), outline=outline)
        self.assertIn("E35", errors)
        q = data["segments"][2]["turns"][0]
        q["holdAfterMs"] = 7000
        q["pause"] = {"kind": "predict", "prompt": "What stops the lists getting long?"}
        errors, _ = self.run_v(data, self.facts(), minutes=2.65, outline=outline)
        self.assertNotIn("E35", errors)
        _, warnings = self.run_v(sample_script(), self.facts())
        self.assertIn("W35", warnings, "a bare answer in another mechanism segment only warns")

    def test_explain_back_pause_comes_before_the_explain_back(self):
        data = sample_script()
        outline = {"segments": [{"id": "seg04", "explainBack": True}]}
        errors, _ = self.run_v(data, self.facts(), outline=outline)
        self.assertIn("E37", errors)
        seg = data["segments"][3]
        seg["turns"].insert(0, {"id": "t13", "speaker": "guest", "kind": "question", "text": "Before I do, say it back yourself.",
                                "holdAfterMs": 7000, "pause": {"kind": "explain-back", "prompt": "Explain the three steps aloud"}})
        errors, _ = self.run_v(data, self.facts(), minutes=2.7, outline=outline)
        self.assertNotIn("E37", errors)

    def test_outline_core_segment_is_single(self):
        import validate_script as vs
        outline = json.loads(json.dumps({"segments": [{"id": "seg01", "role": "hook", "coreSegment": True},
                                                      {"id": "seg02", "role": "mechanism", "coreSegment": True}]}))
        rep = vs.Report("o")
        vs.check_outline(outline, None, rep)
        self.assertIn("E36", {p["code"] for p in rep.errors})


# ------------------------------------------------------------------------------------- E01

class SeriesFinal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w8-series-"))
        self.ws = self.tmp
        (self.ws / "ser").mkdir()
        self.series = {"version": 1, "id": "ser", "title": "S", "parts": [{"part": 1, "slug": "ser-p1"}, {"part": 2, "slug": "ser-p2"}]}
        (self.ws / "ser" / "series.json").write_text(json.dumps(self.series))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, final):
        import validate_script as vs
        rep = vs.Report("s")
        vs.check_series(self.series, self.ws / "ser" / "series.json", rep, final=final)
        return {p["code"] for p in rep.errors}, {p["code"] for p in rep.warnings}

    def part(self, n, retrieval_pause_in_check=True, world=None):
        d = self.ws / f"ser-p{n}"
        d.mkdir(exist_ok=True)
        seg_check = {"id": "seg02", "role": "check", "turns": [{"id": "t02", "speaker": "host", "text": "Which keys move?",
                                                                 **({"pause": {"kind": "retrieve", "prompt": "Which?"}, "holdAfterMs": 7000} if retrieval_pause_in_check else {})}]}
        script = {"series": {"id": "ser", "part": n, "parts": 2},
                  "speakers": [{"id": "host", "name": "Maya"}, {"id": "guest", "name": "Theo"}],
                  "segments": [{"id": "seg01", "role": "misconception", "turns": []}, seg_check]}
        (d / "script.json").write_text(json.dumps(script))
        (d / "timing.json").write_text(json.dumps({"durationMs": 60000}))
        (d / "scenes.json").write_text(json.dumps(world or {"world": {"nodes": [], "edges": []}, "scenes": []}))

    def test_all_parts_absent_fails_in_final_mode(self):
        errors, warnings = self.check(final=False)
        self.assertEqual(errors, set())
        errors, _ = self.check(final=True)
        self.assertIn("E30", errors)

    def test_one_check_segment_with_a_pause_counts_once(self):
        self.part(1)
        (self.ws / "ser-p2").mkdir()
        errors, _ = self.check(final=False)
        self.assertIn("E21", errors, "one check segment with a retrieve pause is ONE retrieval, not two")

    def test_carried_world_state(self):
        # W13a (Q01): a `set` label shows until the next step unless persist, so the carried label is persistent here.
        w1 = {"world": {"nodes": [{"id": "a", "label": "A", "pos": 2}, {"id": "d", "label": "D", "pos": 9}], "edges": []},
              "scenes": [{"id": "s1", "type": "world", "props": {"steps": [{"set": {"a": {"label": "A (2 keys)", "persist": True}}}, {"hide": ["d"]}]}}]}
        w2_bad = {"world": {"nodes": [{"id": "a", "label": "A", "pos": 3}], "edges": []}, "scenes": []}
        self.part(1, world=w1)
        self.part(2, world=w2_bad)
        errors, warnings = self.check(final=False)
        self.assertIn("W32", warnings)
        errors, _ = self.check(final=True)
        self.assertIn("E32", errors)
        w2_good = {"world": {"nodes": [{"id": "a", "label": "A (2 keys)", "pos": 2}], "edges": []}, "scenes": []}
        self.part(2, world=w2_good)
        errors, warnings = self.check(final=True)
        self.assertNotIn("E32", errors, "d was hidden at the end of part 1, so part 2 need not carry it")


# ------------------------------------------------------------------------------------- A05 / N10 / N11

class OneSourceOfTruth(unittest.TestCase):
    def test_term_limits_come_from_the_schema(self):
        import validate_script as vs
        common = json.loads((SKILL / "schemas" / "common.schema.json").read_text())["$defs"]["newTermLimits"]["default"]
        self.assertEqual(vs.MAX_NEW_TERMS, {k: common[k] for k in ("quick", "standard", "deep")})
        outline = json.loads((SKILL / "schemas" / "outline.schema.json").read_text())
        self.assertEqual(outline["properties"]["segments"]["items"]["properties"]["newTerms"]["maxItems"], common["perSegment"])
        ld = (SKILL / "references" / "learning-design.md").read_text()
        self.assertNotIn("6 per part", ld)

    def test_true_peak_constant_and_docs_agree(self):
        import tts
        self.assertEqual(tts.MONO_TRUE_PEAK, pc.MONO_TRUE_PEAK)
        self.assertEqual(pc.MONO_TRUE_PEAK, -4.5)
        files = [SKILL / "SKILL.md"] + sorted((SKILL / "references").glob("*.md"))
        for f in files:
            text = f.read_text()
            for bad in ("default -4.0", "--true-peak -4.0", "ceiling is -4.0", "ceiling of -4.0", "(-4.0 dBTP"):
                self.assertNotIn(bad, text, f"{f.name} still states -4.0 as a current default")
        self.assertNotIn("default -4.0", (SCRIPTS / "qc.py").read_text())

    def test_align_uses_file_url_to_path(self):
        src = (SCRIPTS / "align.mjs").read_text()
        self.assertIn("fileURLToPath(import.meta.url)", src)
        self.assertNotIn("new URL(import.meta.url).pathname", src)
        if shutil.which("node"):
            r = subprocess.run(["node", "--check", str(SCRIPTS / "align.mjs")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with tempfile.TemporaryDirectory() as td:
                d = Path(td) / "Skill Library"
                d.mkdir()
                probe = d / "probe.mjs"
                probe.write_text('import path from "node:path";\nimport { fileURLToPath } from "node:url";\n'
                                 'console.log(path.join(path.dirname(fileURLToPath(import.meta.url)), "fidelity.py"));\n')
                out = subprocess.run(["node", str(probe)], capture_output=True, text=True).stdout.strip()
                self.assertEqual(Path(out).resolve(), (d / "fidelity.py").resolve())


if __name__ == "__main__":
    unittest.main()
