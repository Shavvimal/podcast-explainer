"""Tests for the W11a fixes (codex round 3 and the v5 judge, 3 Nov 2026): N06 delivered derivatives,
B01 negating prefixes and direction words, the ASR lexicon, R04 review digest in the build identity,
R05 designated held-out item, R06 quoted preflight paths, R07 docs, C02 exclusive temp files, A09
entrance frames, E01 malformed series parts, N09 evidence references and verbatim replies, D03
lazy-lesson regression, R02 count labels, R01/R03 Python table checks, labels.stale and the length
budget at validation time. Run from the skill folder:

    python3 -m unittest tests.test_w11a -v

Standard library only. No network, no Gemini call, no ffmpeg needed.
"""
from __future__ import annotations

import json
import os
import random
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
SCRIPTS = SKILL / "scripts"
EVALS = SKILL / "evals" / "files"
sys.path.insert(0, str(SCRIPTS))

import pe_common as pc  # noqa: E402
import qc  # noqa: E402
import validate_script as vs  # noqa: E402
from tests.test_w8 import good_scores, quiet, sample_script, sample_timing  # noqa: E402

V5 = Path(os.environ.get("PE_E2E_V5_WORKSPACE", "/nonexistent/e2e-v5/explainers/consistent-hashing"))  # an old end-to-end workspace, when present


class TmpWs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w11a-"))
        self.ws = self.tmp / "ws"
        self.ep = self.ws / "hash-maps"
        self.ep.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def episode(self, slug="hash-maps"):
        return qc.Episode(mock.Mock(workspace=str(self.ws), slug=slug, mp4=None, remotion_dir=None))


# ------------------------------------------------------------------------------------- N06

class DeliveredDerivatives(TmpWs):
    def setUp(self):
        super().setUp()
        script = sample_script()
        (self.ep / "script.json").write_text(json.dumps(script))
        (self.ep / "timing.json").write_text(json.dumps(sample_timing(script)))
        shutil.copy(EVALS / "sample-learn.json", self.ep / "learn.json")
        shutil.copy(EVALS / "sample-facts.json", self.ep / "facts.json")
        (self.ep / "out").mkdir()
        (self.ep / "out" / "episode.mp4").write_bytes(b"not a real mp4")
        self.build()

    def build(self):
        import learn
        import transcript
        rv, _, err = quiet(learn.main, ["--workspace", str(self.ws), "--slug", "hash-maps"])
        self.assertEqual(rv, 0, err)
        rv, _, err = quiet(transcript.main, ["--workspace", str(self.ws), "--slug", "hash-maps", "--date", "2026-11-03"])
        self.assertEqual(rv, 0, err)

    def problems(self):
        rec = json.loads((self.ws / "library" / "index.json").read_text())["episodes"][0]
        return qc.delivery_problems(self.episode(), rec)

    def test_fresh_build_passes_and_lists_every_derivative(self):
        self.assertEqual(self.problems(), [])
        files = json.loads((self.ep / "delivery.json").read_text())["files"]
        for name in ("transcript.md", "transcript.json", "captions.vtt", "captions.srt", "library", "sidecar.srt",
                     "sidecar.vtt", "sidecar.transcript.md"):
            self.assertIn(name, files)

    def test_each_hand_edit_is_caught(self):
        targets = {"library": self.ws / "library" / "hash-maps.md", "captions.vtt": self.ep / "captions.vtt",
                   "captions.srt": self.ep / "captions.srt", "transcript.md": self.ep / "transcript.md",
                   "sidecar.srt": self.ep / "out" / "episode.srt", "sidecar.transcript.md": self.ep / "out" / "transcript.md"}
        for name, path in targets.items():
            old = path.read_text()
            path.write_text(old.replace("hash", "HASH", 1) + "edited\n")
            probs = self.problems()
            self.assertTrue(any(name in p for p in probs), f"{name}: {probs}")
            path.write_text(old)
        self.assertEqual(self.problems(), [])

    def test_edit_with_a_matching_digest_is_still_caught(self):
        p = self.ep / "transcript.md"
        p.write_text(p.read_text().replace("bucket", "box"))
        dl = json.loads((self.ep / "delivery.json").read_text())
        dl["files"]["transcript.md"]["sha256"] = pc.json_digest(p)
        (self.ep / "delivery.json").write_text(json.dumps(dl))
        probs = self.problems()
        self.assertTrue(any("differs from what transcript.py renders" in x for x in probs), probs)

    def test_missing_file_and_stale_script(self):
        (self.ep / "out" / "episode.vtt").unlink()
        self.assertTrue(any("sidecar.vtt missing" in p for p in self.problems()))
        self.build()
        s = json.loads((self.ep / "script.json").read_text())
        s["segments"][0]["turns"][0]["text"] += " Really."
        (self.ep / "script.json").write_text(json.dumps(s))
        self.assertTrue(any("built from another script" in p for p in self.problems()))

    def test_delivery_json_is_in_the_build_identity(self):
        a = qc.build_identity(self.episode())["id"]
        dl = json.loads((self.ep / "delivery.json").read_text())
        dl["files"]["library"]["sha256"] = "0" * 64
        (self.ep / "delivery.json").write_text(json.dumps(dl))
        self.assertNotEqual(qc.build_identity(self.episode())["id"], a)


# ------------------------------------------------------------------------------------- B01 and lexicon

class FidelityB01(unittest.TestCase):
    def test_negating_prefix_substitutions_fail(self):
        for s, h in (("The token is valid.", "The token is invalid."), ("The user is authenticated.", "The user is unauthenticated."),
                     ("You can connect now.", "You can disconnect now."), ("The hash is able to spread keys.", "The hash is unable to spread keys.")):
            r = pc.turn_fidelity(s, h)
            self.assertEqual(r["status"], "fail", (s, h, r))

    def test_direction_word_deleted_or_inserted_fails(self):
        for s, h in (("The load increases when a server dies.", "The load when a server dies."),
                     ("The answer is false here.", "The answer is here."),
                     ("Add more servers to the ring.", "Add servers to the ring."),
                     ("The ring keeps the keys.", "The ring keeps the keys before.")):
            r = pc.turn_fidelity(s, h)
            self.assertEqual(r["status"], "fail", (s, h, r))
            self.assertTrue(any("direction word" in c for c in r["critical"]), r)

    def test_harmless_differences_still_warn_only(self):
        self.assertEqual(pc.turn_fidelity("The colour of the bucket.", "The color of the bucket.")["status"], "ok")
        self.assertEqual(pc.turn_fidelity("So the bucket holds a list.", "Now the bucket holds a list.")["status"], "warn")


class Lexicon(unittest.TestCase):
    LX = {"Priya": ["pria", "prayer"], "Nia": ["near"]}

    def test_alias_is_read_as_the_name(self):
        self.assertEqual(pc.turn_fidelity("Priya, try it.", "Pria, try it.")["status"], "warn")
        self.assertEqual(pc.turn_fidelity("Priya, try it.", "Pria, try it.", self.LX)["status"], "ok")
        self.assertEqual(pc.turn_fidelity("Right, Nia.", "Right, near.", self.LX)["status"], "ok")

    def test_lexicon_cannot_hide_a_meaning_change(self):
        bad = {"Priya": ["not"], "Theo": ["five"], "valid": ["invalid"], "Nia": ["more"]}
        probs = pc.lexicon_problems(bad)
        self.assertEqual(len(probs), 4, probs)
        self.assertEqual(pc.lexicon_map(bad), [])
        r = pc.turn_fidelity("Priya says 4 keys move.", "Pria says 5 keys move.", self.LX)
        self.assertEqual(r["status"], "fail", "a lexicon never hides a number change")
        r = pc.turn_fidelity("The key is valid.", "The key is invalid.", bad)
        self.assertEqual(r["status"], "fail")

    def test_episode_fidelity_reads_brief_lexicon(self):
        script = {"segments": [{"turns": [{"id": "t01", "text": "Priya, which keys move?"}]}]}
        timing = {"mode": "per-turn", "alignment": {"engine": "whisper.cpp"},
                  "turns": [{"id": "t01", "audioSha": "a", "alignedAudioSha": "a", "words": [{"text": "x", "source": "asr"}],
                             "asr": [{"text": w} for w in "Prayer, which keys move?".split()]}]}
        self.assertEqual(pc.episode_fidelity(script, timing)["counts"]["warn"], 1)
        self.assertEqual(pc.episode_fidelity(script, timing, None, self.LX)["counts"]["ok"], 1)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "brief.json").write_text(json.dumps({"lexicon": self.LX}))
            self.assertEqual(pc.load_lexicon(Path(d)), self.LX)

    def test_validator_e40_on_brief(self):
        brief = json.loads((SKILL / "evals" / "files" / "sample-script.json").read_text())  # only for speakers
        data = {"version": 1, "id": "x", "concept": "c", "source": {"kind": "topic"}, "learner": {"name": "Priya", "knows": [], "confusedBy": []},
                "coreMessage": "m", "learnerOutcome": "o", "minutes": 6, "speakers": [
                    {k: s[k] for k in ("id", "name", "voice", "color", "side", "role")} for s in brief["speakers"]],
                "lexicon": {"Priya": ["pria", "never"]}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "brief.json"
            p.write_text(json.dumps(data))
            rv, out, _ = quiet(vs.main, [str(p)])
            self.assertEqual(rv, 1, out)
            self.assertIn("E40", out)
            data["lexicon"] = {"Priya": ["pria", "prayer"]}
            p.write_text(json.dumps(data))
            rv, out, _ = quiet(vs.main, [str(p)])
            self.assertEqual(rv, 0, out)


# ------------------------------------------------------------------------------------- R04 and R05

class ReviewIdentityAndHeldOut(TmpWs):
    def setUp(self):
        super().setUp()
        script = sample_script()
        (self.ep / "script.json").write_text(json.dumps(script))
        (self.ep / "timing.json").write_text(json.dumps(sample_timing(script)))
        shutil.copy(EVALS / "sample-learn.json", self.ep / "learn.json")
        (self.ep / "brief.json").write_text(json.dumps({"viewing": "phone", "depth": "quick", "minutes": 6}))

    def test_review_fields_change_the_build(self):
        base = qc.build_identity(self.episode())["id"]
        for patch in ({"viewing": "desktop"}, {"depth": "standard"}, {"minutes": 12}, {"targetMinutes": 7},
                      {"lexicon": {"Priya": ["pria"]}}, {"learnerLevel": "novice"}):
            b = {"viewing": "phone", "depth": "quick", "minutes": 6, **patch}
            (self.ep / "brief.json").write_text(json.dumps(b))
            self.assertNotEqual(qc.build_identity(self.episode())["id"], base, patch)
        (self.ep / "brief.json").write_text(json.dumps({"viewing": "phone", "depth": "quick", "minutes": 6, "created": "2026-11-03"}))
        self.assertEqual(qc.build_identity(self.episode())["id"], base, "a field outside the review set does not change the build")
        lj = json.loads((self.ep / "learn.json").read_text())
        for q in lj["selfTest"]:
            q.pop("heldOut", None)
        lj["selfTest"][1]["heldOut"] = True
        (self.ep / "learn.json").write_text(json.dumps(lj))
        self.assertNotEqual(qc.build_identity(self.episode())["id"], base)

    def set_heldout(self, idx_list):
        lj = json.loads((EVALS / "sample-learn.json").read_text())
        for i, q in enumerate(lj["selfTest"]):
            q.pop("heldOut", None)
            if i in idx_list:
                q["heldOut"] = True
        (self.ep / "learn.json").write_text(json.dumps(lj))
        return lj

    def test_designation_rules(self):
        self.assertEqual(qc.held_out_check(self.episode(), True)[0]["status"], "pass")
        self.set_heldout([])
        self.assertEqual(qc.held_out_check(self.episode(), True)[0]["status"], "fail")
        self.assertEqual(qc.held_out_check(self.episode(), False)[0]["status"], "warn")
        self.assertEqual(qc.transfer_question(self.episode()), "", "no fallback to an undesignated question")
        self.set_heldout([1, 4])
        self.assertIn("exactly one", qc.held_out_check(self.episode(), True)[0]["detail"])
        self.set_heldout([0])  # level understand
        self.assertEqual(qc.held_out_check(self.episode(), True)[0]["status"], "fail")

    def test_question_already_in_the_video_fails(self):
        lj = self.set_heldout([4])
        s = json.loads((self.ep / "script.json").read_text())
        s["segments"][1]["turns"][0]["text"] = lj["selfTest"][4]["question"]
        (self.ep / "script.json").write_text(json.dumps(s))
        c = qc.held_out_check(self.episode(), True)[0]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("already spoken or shown", c["detail"])

    def test_answer_already_in_the_video_is_judge_evidence(self):
        # W13a (Q02): answer overlap is evidence for the judge (warn), not a hard failure.
        lj = self.set_heldout([4])
        s = json.loads((self.ep / "script.json").read_text())
        s["segments"][2]["turns"][0]["text"] = lj["selfTest"][4]["answer"]
        (self.ep / "script.json").write_text(json.dumps(s))
        c = qc.held_out_check(self.episode(), True)[0]
        self.assertEqual(c["status"], "warn", c)
        self.assertIn("answer", c["detail"])

    def test_judge_brief_asks_to_verify_and_scores_record_it(self):
        ep = self.episode()
        ep.qc.mkdir(exist_ok=True)
        text = qc.write_judge_brief(ep, {"id": "b1"}).read_text()
        self.assertIn("must not demonstrate", text)
        self.assertIn("A robot logs sensor readings", text)
        sc = good_scores()
        sc["heldOut"] = {"demonstrated": True, "evidence": "t12 works it"}
        self.assertTrue(any("held-out case demonstrated" in p for p in qc.score_problems(sc, "b1")))

    def test_learn_py_rejects_two_held_out_items(self):
        import learn
        self.set_heldout([1, 4])
        rv, _, err = quiet(learn.main, ["--workspace", str(self.ws), "--slug", "hash-maps"])
        self.assertEqual(rv, 1)
        self.assertIn("exactly one", err)


# ------------------------------------------------------------------------------------- N09

class EvidenceReferences(unittest.TestCase):
    CTX = {"turns": {f"t{i:02d}" for i in range(1, 17)}, "maxSec": 200, "files": {"seg01-entry.png", "contact-sheet.png"}}

    def resign(self, sc):
        judge = {k: sc[k] for k in qc.JUDGE_FIELDS if k in sc}
        sc["judgeReply"] = "```json\n" + json.dumps(judge) + "\n```"
        sc["judgeReplySha256"] = pc.bytes_sha(sc["judgeReply"].encode(), 64)
        r = sc["restate"]
        r["reply"] = "```json\n" + json.dumps({k: r[k] for k in qc.RESTATE_FIELDS}) + "\n```"
        r["replySha256"] = pc.bytes_sha(r["reply"].encode(), 64)
        return sc

    def test_valid_record_passes_with_context(self):
        self.assertEqual(qc.score_problems(good_scores(), "b1", self.CTX), [])

    def test_codex_forgery_is_rejected(self):
        sc = good_scores()
        sc["reasons"] = {k: "t999" for k in sc["reasons"]}
        sc["worst"] = []
        sc["restate"] = {"score": 5, "summary": "x", "gaps": ["I cannot explain the mechanism."]}
        probs = qc.score_problems(self.resign_partial(sc), "b1", self.CTX)
        joined = " ".join(probs)
        self.assertIn("turn t999 does not exist", joined)
        self.assertIn("restate.retrieval", joined)
        self.assertIn("restate.reply", joined)

    def resign_partial(self, sc):
        judge = {k: sc[k] for k in qc.JUDGE_FIELDS if k in sc}
        sc["judgeReply"] = "```json\n" + json.dumps(judge) + "\n```"
        sc["judgeReplySha256"] = pc.bytes_sha(sc["judgeReply"].encode(), 64)
        return sc

    def test_time_outside_episode_and_empty_worst(self):
        sc = good_scores()
        sc["reasons"]["hook"] = "59:59 t02: x"
        sc["scores"]["visual"] = 6
        sc["worst"] = []
        probs = qc.score_problems(self.resign(sc), "b1", self.CTX)
        self.assertTrue(any("outside the episode" in p for p in probs), probs)
        self.assertTrue(any("worst is empty" in p for p in probs), probs)

    def test_reply_must_be_verbatim(self):
        sc = good_scores()
        sc["judgeReplySha256"] = "0" * 64
        self.assertTrue(any("judgeReplySha256" in p for p in qc.score_problems(sc, "b1", self.CTX)))
        sc = good_scores()
        sc["scores"]["hook"] = 10  # the record no longer matches what the judge said
        self.assertTrue(any("differs from the judge's own JSON block" in p for p in qc.score_problems(sc, "b1", self.CTX)))
        sc = good_scores()
        sc["restate"]["score"] = 5
        self.assertTrue(any("restater's own JSON block" in p for p in qc.score_problems(sc, "b1", self.CTX)))

    def test_restate_citations_must_exist(self):
        sc = good_scores()
        sc["restate"]["transfer"]["citations"] = ["frame-999.png"]
        probs = qc.score_problems(self.resign(sc), "b1", self.CTX)
        self.assertTrue(any("restate.transfer.citations" in p for p in probs), probs)
        sc = good_scores()
        sc["restate"]["transfer"]["citations"] = ["seg01-entry.png"]
        self.assertEqual(qc.score_problems(self.resign(sc), "b1", self.CTX), [])

    def test_docs_say_a_record_cannot_prove_independence(self):
        for ref in ("qc.md", "learning-design.md"):
            text = (SKILL / "references" / ref).read_text()
            self.assertIn("cannot prove", text, ref)
            self.assertIn("VERBATIM", text, ref)


# ------------------------------------------------------------------------------------- R06, R07

class PreflightAndDocs(unittest.TestCase):
    def test_fix_command_survives_spaces(self):
        import preflight
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / "My Lessons" / "explainers"
            t = preflight.Table()
            preflight.check_workspace(t, ws)
            fix = next(r["fix"] for r in t.rows if r["check"] == "remotion workspace")
            toks = shlex.split(fix)
            self.assertIn(str(ws.resolve()), toks)
            self.assertIn(str((ws / "remotion").resolve()), toks)

    def test_contract_entrance_and_final_qc(self):
        for text in ((SKILL / "SKILL.md").read_text(), (SKILL / "references" / "qc.md").read_text()):
            self.assertNotIn("It changes nothing", text)
            self.assertIn("refreshes", text)

    def test_skill_commands_have_explicit_working_directories(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertIn('SKILL="', text)
        self.assertNotIn("cd explainers/remotion && node SKILL", text)
        self.assertIn('"$SKILL/scripts/align.mjs"', text)


# ------------------------------------------------------------------------------------- C02

class ExclusiveTemp(unittest.TestCase):
    def test_planted_temp_links_are_never_written_through(self):
        import build_manifest as bm
        import tts
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            outside = d / "outside.txt"
            outside.write_text("keep")
            ep = d / "ep"
            (ep / "audio" / "cache").mkdir(parents=True)
            for planted in (ep / "episode.json.tmp", ep / "audio" / "cache" / "pins.json.part", ep / "timing.tmp",
                            ep / "transcript.md.tmp"):
                planted.symlink_to(outside)
            bm.write_atomic(ep / "episode.json", "{}")
            tts.save_pins(ep / "audio" / "cache", {"t01": {"hash": "ab" * 8, "take": "cd" * 8}}, [{"id": "t01", "hash": "ab" * 8}])
            pc.atomic_write(ep / "timing.json", "{}", base=ep)
            import transcript
            transcript.write_if_changed(ep / "transcript.md", "x")
            self.assertEqual(outside.read_text(), "keep")
            self.assertEqual((ep / "episode.json").read_text(), "{}")
            self.assertTrue((ep / "audio" / "cache" / "pins.json").is_file())

    def test_link_at_target_or_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "real").mkdir()
            (d / "ep").mkdir()
            (d / "ep" / "timing.json").symlink_to(d / "real" / "x.json")
            with self.assertRaises(pc.BadId):
                pc.atomic_write(d / "ep" / "timing.json", "{}", base=d / "ep")
            (d / "ep" / "audio").symlink_to(d / "real")
            with self.assertRaises(pc.BadId):
                pc.atomic_write(d / "ep" / "audio" / "episode.wav", b"x", base=d / "ep")
            self.assertFalse((d / "real" / "episode.wav").exists())

    def test_no_guessable_temp_names_left_in_scripts(self):
        for name in ("tts.py", "build_manifest.py", "learn.py", "transcript.py"):
            text = (SCRIPTS / name).read_text()
            for bad in ('with_name(path.name + ".tmp")', 'with_suffix(".tmp")', '(PIN_FILE + ".part")', '.tmp.wav"', '.norm.wav")'):
                self.assertNotIn(bad, text, f"{name}: {bad}")


# ------------------------------------------------------------------------------------- A09

class EntranceFrames(unittest.TestCase):
    def test_codex_case_ends_before_speech_on_frames(self):
        import build_manifest as bm
        turns = [{"id": "t01", "startMs": 0, "endMs": 3017}, {"id": "t02", "startMs": 3250, "endMs": 6000}]
        scenes = [{"id": "s1", "type": "title", "startMs": 0, "endMs": 3250}, {"id": "s2", "type": "diagram", "startMs": 3250, "endMs": 9000}]
        res = bm.place_entrances(scenes, turns, 233)
        sc = scenes[1]
        frm = pc.ms_to_frame(sc["startMs"], 30)
        frames = pc._js_round(sc["enterMs"] * 30 / 1000)
        self.assertLessEqual((frm + frames) * 1000 / 30, 3250)
        self.assertGreater(sc["enterMs"], 0)
        self.assertEqual(res["overlaps"], [])

    def test_random_gaps_never_overlap_rendered_frames(self):
        import build_manifest as bm
        rnd = random.Random(11)
        for _ in range(3000):
            e, g = rnd.randint(1000, 5000), rnd.randint(0, 800)
            n = e + g
            turns = [{"id": "t01", "startMs": 0, "endMs": e}, {"id": "t02", "startMs": n, "endMs": n + 3000}]
            a = rnd.choice([n, rnd.randint(n + 1, n + 2999)])
            scenes = [{"id": "s1", "type": "title", "startMs": 0, "endMs": a}, {"id": "s2", "type": "diagram", "startMs": a, "endMs": n + 5000}]
            res = bm.place_entrances(scenes, turns)
            sc = scenes[1]
            f = pc.ms_to_frame(sc["startMs"], 30)
            fr = pc._js_round(sc["enterMs"] * 30 / 1000)
            fs, fe = f * 1000 / 30, (f + fr) * 1000 / 30
            self.assertEqual(res["overlaps"], [])
            if fr:
                self.assertFalse(any(t["startMs"] < fe - 1 and t["endMs"] > fs + 1 for t in turns), (e, g, a, sc))
            if a != n:
                self.assertEqual(sc["enterMs"], 0, "an inside-speech anchor cuts in")


# ------------------------------------------------------------------------------------- E01

class SeriesInputs(TmpWs):
    def part(self, n, timing="ok", scenes="ok", glossary=True):
        d = self.ws / f"ser-p{n}"
        d.mkdir(parents=True, exist_ok=True)
        s = sample_script()
        s["series"] = {"id": "ser", "part": n, "parts": 2}
        (d / "script.json").write_text(json.dumps(s))
        if timing == "ok":
            (d / "timing.json").write_text(json.dumps({**sample_timing(s), "alignment": {"engine": "whisper.cpp"}}))
        elif timing == "bad":
            (d / "timing.json").write_text("{not json")
        elif timing == "zero":
            (d / "timing.json").write_text(json.dumps({"turns": []}))
        if scenes == "ok":
            (d / "scenes.json").write_text(json.dumps({"version": 1, "scenes": [], "world": {"nodes": [], "edges": []}}))
        elif scenes == "bad":
            (d / "scenes.json").write_text("[[[")
        if glossary:
            (d / "glossary.json").write_text(json.dumps({"terms": [{"term": "bucket", "definition": "a slot"}]}))

    def run_series(self, final=True):
        (self.ws / "ser").mkdir(exist_ok=True)
        data = {"version": 1, "id": "ser", "parts": [{"part": 1, "slug": "ser-p1"}, {"part": 2, "slug": "ser-p2"}]}
        rep = vs.Report("series")
        vs.check_series(data, self.ws / "ser" / "series.json", rep, final=final)
        return {e["code"] for e in rep.errors}, " ".join(e["message"] for e in rep.errors)

    def test_malformed_timing_and_scenes_are_errors(self):
        self.part(1)
        self.part(2, timing="bad", scenes="bad")
        codes, msg = self.run_series(final=False)
        self.assertIn("E21", codes, msg)
        self.assertIn("E32", codes, msg)
        self.part(2, timing="zero")
        codes, msg = self.run_series(final=False)
        self.assertIn("durationMs", msg)

    def test_glossary_is_required_in_strict_mode(self):
        self.part(1)
        self.part(2, glossary=False)
        codes, msg = self.run_series(final=True)
        self.assertIn("E31", codes, msg)
        self.assertIn("glossary", msg)
        codes, _ = self.run_series(final=False)
        self.assertNotIn("E31", codes)


# ------------------------------------------------------------------------------------- D03

class LazyLesson(unittest.TestCase):
    LAZY = "How does the mechanism work? For example, Alice says mechanism means a process, so a result follows."

    def test_lazy_sample_fails(self):
        data = sample_script()
        for seg in data["segments"]:
            for t in seg["turns"]:
                t["text"] = self.LAZY
                t["onScreen"] = ["mechanism"]
        facts = json.loads((EVALS / "sample-facts.json").read_text())
        rep = vs.Report("x")
        vs.check_script(data, facts, data["targetMinutes"], 45, "per-turn", rep, None, None)
        codes = {e["code"] for e in rep.errors}
        self.assertIn("E41", codes, codes)
        self.assertIn("E44", codes, codes)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "script.json"
            p.write_text(json.dumps(data))
            rv, out, _ = quiet(vs.main, [str(p), "--facts", str(EVALS / "sample-facts.json")])
            self.assertEqual(rv, 1)
            self.assertIn("RESULT: FAIL", out)

    def test_each_requirement_alone(self):
        def run(seg_role, texts):
            data = sample_script()
            seg = next(s for s in data["segments"] if s["role"] == seg_role)
            for t, x in zip(seg["turns"], texts):
                t["text"] = x
            rep = vs.Report("x")
            vs.check_script(data, None, data["targetMinutes"], 45, "per-turn", rep, None, None)
            return {e["code"] for e in rep.errors if e["segment"] == seg["id"]}
        mech = next(s for s in sample_script()["segments"] if s["role"] == "mechanism")
        n = len(mech["turns"])
        self.assertIn("E41", run("mechanism", ["The table fills up, so it grows to 32 buckets. A bucket is called a slot."] * n))
        self.assertIn("E42", run("mechanism", ["Because the table fills, it doubles to 32 buckets, so lists stay short."] * n))
        self.assertIn("E43", run("mechanism", ["Because the table fills, it doubles, so lists stay short. Load means entries per bucket."] * n))
        self.assertIn("E44", run("misconception", ["Every key gets its own slot?", "Let us see what happens with buckets.", "Then it holds a list."]))

    def test_sample_and_real_scripts_pass_the_new_checks(self):
        rep = vs.Report("x")
        data = sample_script()
        vs.check_script(data, json.loads((EVALS / "sample-facts.json").read_text()), data["targetMinutes"], 45, "per-turn", rep, None, None)
        self.assertEqual({e["code"] for e in rep.errors} & {"E41", "E42", "E43", "E44"}, set())


# ------------------------------------------------------------------------------------- length budget

class LengthBudget(unittest.TestCase):
    def test_prediction_includes_gaps_tails_and_lead(self):
        s = {"segments": [{"turns": [{"text": "one two three"}, {"text": "four five", "holdAfterMs": 7000}]},
                          {"turns": [{"text": "six"}]}]}
        p = pc.predict_length(s)
        self.assertAlmostEqual(p["speechSec"], 6 * 0.357)
        self.assertAlmostEqual(p["holdSec"], 7.0)
        self.assertAlmostEqual(p["gapSec"], 0.25)
        self.assertAlmostEqual(p["tailSec"], 1.2)
        self.assertAlmostEqual(p["totalSec"], 6 * 0.357 + 7 + 0.25 + 1.2 + 0.25)

    def test_thresholds(self):
        pred = {"totalSec": 60 * 1.16, "speechSec": 0, "holdSec": 0, "gapSec": 0, "tailSec": 0, "leadSec": 0}
        self.assertEqual(pc.length_verdict(pred, 1)[0], "error")
        pred["totalSec"] = 60 * 1.10
        self.assertEqual(pc.length_verdict(pred, 1)[0], "warn")
        pred["totalSec"] = 60 * 1.05
        self.assertEqual(pc.length_verdict(pred, 1)[0], "ok")

    def test_validator_and_tts_dry_run_agree(self):
        import tts
        data = sample_script()
        for seg in data["segments"]:
            for t in seg["turns"]:
                t["text"] = t["text"] + " " + t["text"]
        rep = vs.Report("x")
        vs.check_script(data, None, data["targetMinutes"], 200, "per-turn", rep, None, None)
        self.assertIn("E39", {e["code"] for e in rep.errors})
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            turns = tts.flat_turns(data)
            units = [{"id": t["id"], "key": "ab" * 8, "texts": [t["text"]], "turns": [t]} for t in turns]
            with mock.patch.object(tts, "unit_expected", lambda u: 1.0):
                rv, out, err = quiet(tts.dry_run, data, turns, units, "gemini-3.8-flash-tts", cache, "per-turn")
            self.assertEqual(rv["lengthVerdict"], "error")
            self.assertAlmostEqual(rv["predicted"]["totalSec"], rep.length["totalSec"], delta=0.1)
            self.assertIn("predicted final length", err + out)

    @unittest.skipUnless((V5 / "script.json").is_file(), "v5 run not in the scratchpad")
    def test_v5_script_is_caught_before_tts(self):
        data = json.loads((V5 / "script.json").read_text())
        rep = vs.Report("v5")
        vs.check_script(data, None, data.get("targetMinutes"), 45, "per-turn", rep, None, None)
        self.assertIn("E39", {e["code"] for e in rep.errors})
        timing = json.loads((V5 / "timing.json").read_text())
        pred = pc.predict_length(data)["totalSec"] * 1000
        self.assertLess(abs(pred - timing["durationMs"]) / timing["durationMs"], 0.02, "prediction within 2% of the measured audio")


# ------------------------------------------------------------------------------------- R02, R03, R01

def compare_scene(before, after, stats=(), tag=None, chip_claim=None, banners=None):
    cols = [str(i) for i in range(len(before))]
    left = {"title": "hash mod N", "kind": "table", "columns": cols,
            "rows": [{"id": "r1", "label": "before", "cells": list(before)}, {"id": "r2", "label": "after", "cells": list(after)}],
            "steps": [{"atMs": ms, "stat": text} for ms, text in stats]}
    if tag is not None:
        left["tag"] = tag
    props = {"left": left, "right": {"title": "ring", "kind": "text", "lines": [{"text": "ring"}]}}
    if banners:
        props["verdict"], props["banners"] = banners[0], banners[1:]
    return {"id": "sc04", "type": "compare", "props": props, "startMs": 0, "endMs": 60000}


class Ws10(TmpWs):
    def setUp(self):
        super().setUp()
        self.e = self.ws / "demo"
        self.e.mkdir()
        (self.ws / "remotion" / "src").mkdir(parents=True)
        shutil.copy(SKILL / "templates" / "remotion" / "src" / "theme.ts", self.ws / "remotion" / "src" / "theme.ts")

    def demo(self, scenes, overlays=None, brief=None, world=None, holds=None):
        (self.e / "episode.json").write_text(json.dumps({"video": {"fps": 30}, "scenes": scenes, "turns": [],
                                                         "overlays": overlays or [], "world": world, "holds": holds or []}))
        if brief is not None:
            (self.e / "brief.json").write_text(json.dumps(brief))
        return qc.Episode(mock.Mock(workspace=str(self.ws), slug="demo", mp4=None, remotion_dir=None))


class CountLabelsR02(Ws10):
    BEFORE, AFTER = ["A", "B", "C", "A"], ["D", "D", "B", "A"]

    def test_codex_true_statement_passes(self):
        ep = self.demo([compare_scene(self.BEFORE, self.AFTER, stats=[(1000, "2 of 4 move to D")])])
        c = qc.labels_counts(ep)[0]
        self.assertEqual(c["status"], "pass", c)
        self.assertTrue(ep.labels_checked)

    def test_codex_false_tag_fails(self):
        ep = self.demo([compare_scene(self.BEFORE, self.AFTER, tag="0 of 4 move")])
        c = qc.labels_counts(ep)[0]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("0 of 4 move", c["detail"])

    def test_title_counts_too(self):
        sc = compare_scene(self.BEFORE, self.AFTER)
        sc["props"]["left"]["title"] = "1 of 4 move"
        self.assertEqual(qc.labels_counts(self.demo([sc]))[0]["status"], "fail")

    def test_ambiguous_wording_only_warns_and_is_unchecked(self):
        ep = self.demo([compare_scene(self.BEFORE, self.AFTER, stats=[(1000, "1 of 4 keys miss")])])
        c = qc.labels_counts(ep)[0]
        self.assertEqual(c["status"], "warn", c)
        self.assertIn("unchecked", c["detail"])
        self.assertTrue(ep.labels_unchecked)

    def test_structured_claim_is_exact(self):
        ok = [{"id": "c1", "type": "chip", "startMs": 500, "endMs": 5000,
               "props": {"text": "two go to D", "claim": {"kind": "count", "of": 4, "scope": "cells-changed-to", "to": "D", "value": 2, "side": "left"}}}]
        self.assertEqual(qc.labels_counts(self.demo([compare_scene(self.BEFORE, self.AFTER)], overlays=ok))[0]["status"], "pass")
        bad = json.loads(json.dumps(ok))
        bad[0]["props"]["claim"]["value"] = 3
        c = qc.labels_counts(self.demo([compare_scene(self.BEFORE, self.AFTER)], overlays=bad))[0]
        self.assertEqual(c["status"], "fail", c)


class TablesR01R03(Ws10):
    def test_ragged_rows_fail_in_qc_and_build(self):
        sc = compare_scene(["A"], ["B"])
        sc["props"]["left"]["rows"][0]["cells"] = ["A", "LOST"]
        c = {x["id"]: x for x in qc.text_size(self.demo([sc]))}
        self.assertEqual(c["text.minsize"]["status"], "fail", c)
        self.assertIn("one cell per column", c["text.minsize"]["detail"])
        import build_manifest as bm
        probs = bm.Problems()
        sc2 = json.loads(json.dumps(sc))
        bm.check_compare(sc2, None, None, probs)
        self.assertTrue(any("exactly one cell per column" in e for e in probs.errors), probs.errors)
        sc2["props"]["left"]["rows"][0]["cells"] = []
        probs = bm.Problems()
        bm.check_compare(sc2, None, None, probs)
        self.assertTrue(probs.errors, "a short row is an error too")

    def test_impossible_geometry_fails_every_viewing(self):
        cols = [str(i) for i in range(14)]
        sc = compare_scene(cols, cols)
        sc["props"]["left"]["rows"] = [{"id": f"r{i}", "label": f"row {i}", "cells": list(cols)} for i in range(6)]
        sc["props"]["title"] = "A title"
        for v in ("desktop", "phone"):
            c = {x["id"]: x for x in qc.text_size(self.demo([sc], brief={"viewing": v}))}
            self.assertEqual(c["text.minsize"]["status"], "fail", (v, c["text.minsize"]))

    def test_builtin_component_text_is_read_for_phone(self):
        comp = self.ws / "remotion" / "src" / "components"
        comp.mkdir(parents=True)
        (comp / "SpeakerRail.tsx").write_text("const a = <div style={{ fontSize: type.min }} />;\n")
        (comp / "ChapterLabel.tsx").write_text("const a = <div style={{ fontSize: 40 }} />;\n")
        c = {x["id"]: x for x in qc.text_size(self.demo([], brief={"viewing": "phone"}))}
        self.assertEqual(c["text.phone"]["status"], "fail", c)
        self.assertIn("SpeakerRail.tsx:1", c["text.phone"]["detail"])
        (comp / "SpeakerRail.tsx").write_text("const a = <div style={{ fontSize: 36 }} />;\n")
        c = {x["id"]: x for x in qc.text_size(self.demo([], brief={"viewing": "phone"}))}
        self.assertEqual(c["text.phone"]["status"], "pass", c)


# ------------------------------------------------------------------------------------- labels.stale

class StaleLabels(Ws10):
    """A legacy renderer (visibleText.ts without overlayState.ts) keeps labels until changed: stale is a
    fail. The current template ends labels at the next step unless persist: only persist labels can be
    stale, and they warn."""

    def setUp(self):
        super().setUp()
        (self.ws / "remotion" / "src" / "visibleText.ts").write_text("// legacy renderer, no overlayState.ts\n")

    def current_renderer(self):
        (self.ws / "remotion" / "src" / "visibleText.ts").unlink()

    def world(self, persist=False):
        nodes = [{"id": "A", "label": "A", "role": "owner", "pos": 1}, {"id": "B", "label": "B", "role": "owner", "pos": 5},
                 {"id": "D", "label": "D", "role": "owner", "pos": 9, "revealAtMs": 20000},
                 {"id": "count", "label": "keys per server", "value": "6 each", "revealAtMs": 5000}]
        if persist:
            nodes[3]["persist"] = True
        return {"layout": "ring", "nodes": nodes, "edges": []}

    def scene(self, steps):
        return {"id": "sc03", "type": "world", "startMs": 0, "endMs": 90000, "props": {"steps": steps}}

    def test_v5_pattern_fails(self):
        steps = [{"atMs": 5000, "reveal": ["count"]}, {"atMs": 20000, "reveal": ["D"]}, {"atMs": 60000, "set": {"count": {"value": "4 each"}}}]
        c = qc.labels_stale(self.demo([self.scene(steps)], world=self.world()))[0]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("keys per server", c["detail"])
        self.assertIn("D", c["detail"])

    def test_update_in_the_same_step_or_soon_passes(self):
        steps = [{"atMs": 5000, "reveal": ["count"]}, {"atMs": 20000, "reveal": ["D"], "set": {"count": {"value": "4 each"}}}]
        self.assertEqual(qc.labels_stale(self.demo([self.scene(steps)], world=self.world()))[0]["status"], "pass")
        steps = [{"atMs": 5000, "reveal": ["count"]}, {"atMs": 20000, "reveal": ["D"]}, {"atMs": 21000, "set": {"count": {"value": "4 each"}}}]
        self.assertEqual(qc.labels_stale(self.demo([self.scene(steps)], world=self.world()))[0]["status"], "pass")

    def test_persist_is_an_explicit_claim_that_warns(self):
        steps = [{"atMs": 5000, "reveal": ["count"]}, {"atMs": 20000, "reveal": ["D"]}]
        self.assertEqual(qc.labels_stale(self.demo([self.scene(steps)], world=self.world(persist=True)))[0]["status"], "warn")
        steps = [{"atMs": 5000, "reveal": ["count"], "set": {"count": {"value": "6 each", "persist": True}}}, {"atMs": 20000, "reveal": ["D"]}]
        self.assertEqual(qc.labels_stale(self.demo([self.scene(steps)], world=self.world()))[0]["status"], "warn")

    def test_current_renderer_expires_non_persist_labels(self):
        self.current_renderer()
        steps = [{"atMs": 5000, "reveal": ["count"]}, {"atMs": 20000, "reveal": ["D"]}, {"atMs": 60000, "set": {"count": {"value": "4 each"}}}]
        c = qc.labels_stale(self.demo([self.scene(steps)], world=self.world()))[0]
        self.assertEqual(c["status"], "pass", c)
        self.assertIn("unless persist", c["detail"])
        self.assertEqual(qc.labels_stale(self.demo([self.scene(steps)], world=self.world(persist=True)))[0]["status"], "warn")

    def test_chip_over_a_change_fails(self):
        steps = [{"atMs": 20000, "reveal": ["D"]}]
        chips = [{"id": "c1", "type": "chip", "startMs": 15000, "endMs": 40000, "props": {"text": "3 servers"}}]
        w = self.world()
        w["nodes"].pop()  # no count node
        c = qc.labels_stale(self.demo([self.scene(steps)], overlays=chips, world=w))[0]
        self.assertEqual(c["status"], "fail", c)
        chips[0]["props"]["persist"] = True
        self.assertEqual(qc.labels_stale(self.demo([self.scene(steps)], overlays=chips, world=w))[0]["status"], "warn")

    def test_ids_are_not_quantity_labels(self):
        self.assertFalse(qc.is_quantity_label("7"))
        self.assertFalse(qc.is_quantity_label("B"))
        self.assertTrue(qc.is_quantity_label("D's keys 3"))
        self.assertTrue(qc.is_quantity_label("points per server 2"))

    @unittest.skipUnless((V5 / "episode.json").is_file(), "v5 run not in the scratchpad")
    def test_v5_episode_flags_the_judged_stale_label(self):
        ep = qc.Episode(mock.Mock(workspace=str(V5.parent), slug=V5.name, mp4=None, remotion_dir=None))
        c = qc.labels_stale(ep)[0]
        self.assertEqual(c["status"], "fail")
        self.assertIn("keys per server 4 each", c["detail"])

    def test_coverage_runs_it(self):
        self.assertIn("out += labels_stale(ep)", (SCRIPTS / "qc.py").read_text())


# ------------------------------------------------------------------------------------- W11b ports

class RendererPorts(unittest.TestCase):
    def manifest(self, chips, steps):
        return {"video": {"fps": 30}, "world": None, "overlays": chips,
                "scenes": [{"id": "s1", "type": "diagram", "startMs": 0, "endMs": 30000, "props": {"elements": [], "steps": steps}}]}

    def test_chip_ends_at_the_next_visual_step_unless_persist(self):
        chip = {"id": "c", "type": "chip", "startMs": 1000, "endMs": 20000, "props": {"text": "chip"}}
        m = self.manifest([chip], [{"atMs": 5000, "reveal": []}])
        self.assertIn("chip", pc.visible_text(m, 4000, 4500))
        self.assertNotIn("chip", pc.visible_text(m, 6000, 9000))
        chip["props"]["persist"] = True
        self.assertIn("chip", pc.visible_text(m, 6000, 9000))
        # never under 700 ms
        chip2 = {"id": "d", "type": "chip", "startMs": 4900, "endMs": 20000, "props": {"text": "late"}}
        a, b, _ = pc.chip_frames(chip2, pc.visual_step_times(self.manifest([chip2], [{"atMs": 5000}])), 30)
        self.assertGreaterEqual((b - a) * 1000 / 30, 700 - 34)

    def test_node_value_expires_and_set_patch_persist(self):
        world = {"nodes": [{"id": "n", "label": "count", "value": "3 each", "revealAtMs": 0}], "edges": []}
        tl = [{"t": 5000, "sceneId": "s"}, {"t": 9000, "sceneId": "s", "set": {"n": {"value": "4 each"}}}, {"t": 12000, "sceneId": "s"}]
        at = lambda ms: pc.world_texts_at(world, tl, ms, 30)
        self.assertIn("3 each", at(1000))
        self.assertNotIn("3 each", at(6000))
        self.assertIn("4 each", at(10000))
        self.assertNotIn("4 each", at(13000))
        tl[1]["set"]["n"]["persist"] = True
        self.assertIn("4 each", at(13000))

    def test_walk_and_ring_checks(self):
        world = {"layout": "ring", "ring": {"positions": 12}, "nodes": [
            {"id": "k4", "label": "4", "role": "item", "pos": 4}, {"id": "B", "label": "B", "role": "owner", "pos": 6},
            {"id": "D", "label": "D", "role": "owner", "pos": 9}], "edges": []}
        tl = [{"t": 4000, "sceneId": "w1", "walk": [{"item": "k4", "to": "D"}]}]
        probs = pc.walk_problems(world, tl)
        self.assertEqual(len(probs), 1)
        self.assertIn("its successor is B", probs[0])
        tl[0]["walk"] = [{"item": "k4", "to": "D", "overshoot": True}]
        self.assertEqual(pc.walk_problems(world, tl), [])
        tl[0]["walk"] = ["k4"]
        self.assertEqual(pc.walk_problems(world, tl), [])
        world["nodes"][2]["ringOffset"] = 40
        self.assertTrue(pc.ring_problems(world))

    def test_build_manifest_accepts_walk_objects(self):
        import build_manifest as bm
        world = {"layout": "ring", "ring": {"positions": 12}, "nodes": [
            {"id": "k4", "label": "4", "role": "item", "pos": 4}, {"id": "B", "label": "B", "role": "owner", "pos": 6}], "edges": []}
        probs = bm.Problems()
        bm.check_steps(world, [{"atMs": 1, "walk": [{"item": "k4", "to": "B"}, "k4", {"item": "k4", "to": "k4"}]}], "w", 0, probs, {})
        self.assertEqual(len(probs.errors), 1, probs.errors)
        self.assertIn("not an owner", probs.errors[0])

    def test_table_problems_name_what_fits(self):
        cols = [str(i) for i in range(14)]
        panel = {"kind": "table", "columns": cols, "rows": [{"id": f"r{i}", "label": "x", "cells": cols} for i in range(6)]}
        probs = pc.table_problems(panel, True)
        self.assertTrue(any("columns fit" in p or "No column count fits" in p for p in probs), probs)
        self.assertEqual(pc.table_problems({"kind": "table", "columns": ["a", "b"], "rows": [{"id": "r", "label": "x", "cells": ["1", "2"]}]}, False), [])

    def test_sample_scenes_values_persist(self):
        doc = json.loads((EVALS / "sample-scenes.json").read_text())
        persisted = [n for n in (doc.get("world") or {}).get("nodes", []) if n.get("value") is not None and n.get("persist")]
        self.assertTrue(persisted, "sample node values that stay true carry persist")


if __name__ == "__main__":
    unittest.main()
