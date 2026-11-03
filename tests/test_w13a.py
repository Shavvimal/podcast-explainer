"""Tests for the W13a fixes (codex round 4 and the v6 judge, 3 Nov 2026): Q01 series carry-over with
expiry, Q08 series length cap before payment, Q02 held-out evidence, Q03 permanent quantity labels,
Q04 library copies and the bound index record, Q05 claim text, Q06 lexicon terms, Q07 every cited
reference, Q09 executable repair commands, Q10 hero still and summary links, stumble 5 row labels,
E01 measured-duration floor, D03 the longer lazy lesson, and the judge v6 learn.json rules. Run from
the skill folder:

    python3 -m unittest tests.test_w13a -v

Standard library only. No network, no Gemini call, no render.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
from tests.test_w11a import TmpWs, Ws10, compare_scene  # noqa: E402

V6 = Path(os.environ.get("PE_E2E_V6_WORKSPACE", "/nonexistent/e2e-v6/explainers/consistent-hashing"))  # an old end-to-end workspace, when present


# ------------------------------------------------------------------------------------- Q01, E01

class SeriesCarryOver(TmpWs):
    """Q01 reproduction: part 1 sets n.value '3' at 1 s, focuses at 5 s (no persist); at the end the
    value has expired, so part 2 correctly starts without it."""

    def part(self, n, world, scenes, episode=None, timing=None):
        d = self.ws / f"ser-p{n}"
        d.mkdir(parents=True, exist_ok=True)
        s = sample_script()
        s["series"] = {"id": "ser", "part": n, "parts": 2}
        (d / "script.json").write_text(json.dumps(s))
        (d / "timing.json").write_text(json.dumps(timing or {**sample_timing(s), "durationMs": 300000, "alignment": {"engine": "whisper.cpp"}}))
        (d / "scenes.json").write_text(json.dumps({"version": 1, "world": world, "scenes": scenes}))
        if episode is not None:
            (d / "episode.json").write_text(json.dumps(episode))
        (d / "glossary.json").write_text(json.dumps({"terms": []}))

    def run_series(self, final=True):
        (self.ws / "ser").mkdir(exist_ok=True)
        data = {"version": 1, "id": "ser", "parts": [{"part": 1, "slug": "ser-p1"}, {"part": 2, "slug": "ser-p2"}]}
        rep = vs.Report("series")
        vs.check_series(data, self.ws / "ser" / "series.json", rep, final=final)
        return rep

    def p1(self, persist=False):
        world = {"nodes": [{"id": "n", "label": "N"}], "edges": []}
        patch = {"value": "3", **({"persist": True} if persist else {})}
        steps = [{"atMs": 1000, "set": {"n": patch}}, {"atMs": 5000, "camera": {"focus": ["n"]}}]
        scenes = [{"id": "w1", "type": "world", "props": {"steps": steps}}]
        episode = {"world": world, "scenes": [{"id": "w1", "type": "world", "startMs": 0, "endMs": 9000, "props": {"steps": steps}}]}
        self.part(1, world, scenes, episode)

    def test_expired_value_is_not_carried(self):
        self.p1()
        self.part(2, {"nodes": [{"id": "n", "label": "N"}], "edges": []}, [])
        rep = self.run_series()
        self.assertNotIn("E32", {e["code"] for e in rep.errors}, rep.errors)
        end = vs.world_end_state(json.loads((self.ws / "ser-p1" / "scenes.json").read_text()),
                                 json.loads((self.ws / "ser-p1" / "episode.json").read_text()))
        self.assertIsNone(end["n"]["value"])

    def test_persisted_value_must_be_carried(self):
        self.p1(persist=True)
        self.part(2, {"nodes": [{"id": "n", "label": "N"}], "edges": []}, [])
        msg = " ".join(e["message"] for e in self.run_series().errors)
        self.assertIn("n.value '3' -> None", msg)
        self.part(2, {"nodes": [{"id": "n", "label": "N", "value": "3"}], "edges": []}, [])
        self.assertNotIn("E32", {e["code"] for e in self.run_series().errors})

    def test_without_episode_json_the_scene_order_gives_the_same_end_state(self):
        world = {"nodes": [{"id": "n", "label": "N"}], "edges": []}
        scenes = [{"id": "w1", "type": "world", "props": {"steps": [{"set": {"n": {"value": "3"}}}, {"camera": {"focus": ["n"]}}]}}]
        self.assertIsNone(vs.world_end_state({"world": world, "scenes": scenes})["n"]["value"])
        scenes[0]["props"]["steps"].pop()
        self.assertEqual(vs.world_end_state({"world": world, "scenes": scenes})["n"]["value"], "3", "the last step's set is live at the end")

    def test_empty_or_tiny_timing_is_not_measured(self):
        self.p1()
        world = {"nodes": [{"id": "n", "label": "N"}], "edges": []}
        self.part(2, world, [], timing={"durationMs": 1, "turns": []})
        rep = self.run_series()
        msgs = " ".join(e["message"] for e in rep.errors if e["code"] == "E21")
        self.assertIn("timing turns", msgs)
        self.assertIn("not measured speech", msgs)


# ------------------------------------------------------------------------------------- Q08

def series_script(minutes=12, scale=1):
    s = sample_script()
    s["series"] = {"id": "ser", "part": 1, "parts": 2}
    s["targetMinutes"] = minutes
    pred = pc.predict_length(s)["totalSec"]
    # pad the speech so the prediction lands near 749 s (the v6 case): 4% over 12 min, inside the 15% rule
    words = int((749.3 * scale - pred) / pc.SECS_PER_WORD)
    s["segments"][2]["turns"][1]["text"] += " " + " ".join(["word"] * words)
    return s


class SeriesLengthGate(unittest.TestCase):
    def test_one_gate_for_validator_dry_run_and_paid_path(self):
        s = series_script()
        chk = pc.length_check(s)
        self.assertAlmostEqual(chk["pred"]["totalSec"], 749.3, delta=1.0)
        self.assertEqual(chk["verdict"], "error")
        self.assertTrue(any("684" in m for _, _, m in chk["problems"]), chk["problems"])
        rep = vs.Report("x")
        vs.check_script(s, None, 12, 9999, "per-turn", rep)
        self.assertIn("E39", {e["code"] for e in rep.errors})
        s2 = json.loads(json.dumps(s))
        s2.pop("series")
        self.assertNotEqual(pc.length_check(s2)["verdict"], "error", "an unsplit script 4% over is not an error")

    def run_tts(self, script, argv):
        import tts
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="w13a-tts-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "script.json").write_text(json.dumps(script))
        with mock.patch.object(sys, "argv", ["tts.py", str(d), *argv]):
            return quiet(tts.main)

    def test_dry_run_returns_nonzero_on_a_length_error(self):
        rv, out, err = self.run_tts(series_script(), ["--dry-run"])
        self.assertEqual(rv, 1, err)
        self.assertIn("E39", out)
        s = sample_script()
        rv, _, err = self.run_tts(s, ["--dry-run", "--gap-ms", "10000"])
        self.assertEqual(rv, 1, "the actual gap setting is part of the prediction")
        rv, _, err = self.run_tts(s, ["--dry-run"])
        self.assertEqual(rv, 0, err)

    def test_paid_path_refuses_without_override(self):
        import tts
        with mock.patch.object(tts, "load_api_key", side_effect=tts.TtsError("stopped before any request (test)")) as key:
            rv, _, err = self.run_tts(series_script(), [])
            self.assertEqual(rv, 1)
            self.assertIn("refusing paid synthesis", err)
            key.assert_not_called()
            # with the override the gate lets the run continue (it then needs the key: stopped there)
            rv, out, err = self.run_tts(series_script(), ["--allow-over-length", "the learner accepted 12.5 min"])
            self.assertEqual(rv, 1)
            self.assertIn("--allow-over-length given", out)
            self.assertIn("stopped before any request", err)
            self.assertNotIn("refusing paid synthesis", err)
            key.assert_called_once()

    def test_timing_schema_has_length_override(self):
        sch = json.loads((SKILL / "schemas" / "timing.schema.json").read_text())
        self.assertIn("lengthOverride", sch["properties"])
        self.assertIn("timing[\"lengthOverride\"] = length_override", (SCRIPTS / "tts.py").read_text())


# ------------------------------------------------------------------------------------- Q02, Q07

class HeldOutAndReferences(unittest.TestCase):
    CTX = {"turns": {f"t{i:02d}" for i in range(1, 17)}, "maxSec": 200, "files": {"seg01-entry.png", "contact-sheet.png"},
           "videoText": "two keys land in the same bucket | the bucket keeps a short list and checks each key"}

    def resign(self, sc):
        judge = {k: sc[k] for k in qc.JUDGE_FIELDS if k in sc}
        sc["judgeReply"] = "x\n```json\n" + json.dumps(judge) + "\n```\n"
        sc["judgeReplySha256"] = pc.bytes_sha(sc["judgeReply"].encode(), 64)
        return sc

    def test_good_record_passes(self):
        self.assertEqual(qc.score_problems(good_scores(), "b1", self.CTX), [])

    def test_case_and_solution_are_required_and_quoted_from_the_video(self):
        for field, value, word in (("case", None, "missing"), ("case", "t06 two keys share", "quotes nothing"),
                                   ("solution", "t07: \"the bucket grows a tree of keys\"", "not in the spoken"),
                                   ("solution", "t99: \"the bucket keeps a short list\"", "cites no existing")):
            sc = good_scores()
            if value is None:
                sc["heldOut"].pop(field)
            else:
                sc["heldOut"][field] = value
            probs = qc.score_problems(self.resign(sc), "b1", self.CTX)
            self.assertTrue(any(word in p for p in probs), (field, value, probs))

    def test_every_reference_is_validated(self):
        self.assertFalse(qc._cites_real("seg99-missing.png t01", self.CTX))
        self.assertFalse(qc._cites_real("seg01-entry.png t999 99:99", self.CTX))
        self.assertFalse(qc._cites_real("seg01-entry.png 99:99", self.CTX))
        self.assertTrue(qc._cites_real("seg01-entry.png t01 01:10", self.CTX))
        self.assertTrue(qc._cites_real("[02:23]", self.CTX))
        self.assertFalse(qc._cites_real("no reference at all", self.CTX))
        self.assertIn("frame seg99-missing.png does not exist in qc/", qc._ref_problems("seg99-missing.png t01", self.CTX))


class HeldOutCheck(TmpWs):
    def setUp(self):
        super().setUp()
        s = sample_script()
        (self.ep / "script.json").write_text(json.dumps(s))
        lj = json.loads((EVALS / "sample-learn.json").read_text())
        for q in lj["selfTest"]:
            q.pop("heldOut", None)
        lj["selfTest"][4]["heldOut"] = True
        lj["selfTest"][4]["level"] = "transfer"
        self.lj = lj
        (self.ep / "learn.json").write_text(json.dumps(lj))

    def test_valid_transfer_answer_using_the_rule_is_not_a_failure(self):
        s = json.loads((self.ep / "script.json").read_text())
        s["segments"][2]["turns"][0]["text"] = self.lj["selfTest"][4]["answer"]
        (self.ep / "script.json").write_text(json.dumps(s))
        ep = self.episode()
        c = qc.held_out_check(ep, True)[0]
        self.assertEqual(c["status"], "warn", c)
        ep.qc.mkdir(exist_ok=True)
        brief = qc.write_judge_brief(ep, {"id": "b1"}).read_text()
        self.assertIn("answer overlap 100%", brief)
        self.assertIn("heldOut.case", brief)

    def test_duplicated_question_still_fails(self):
        s = json.loads((self.ep / "script.json").read_text())
        s["segments"][1]["turns"][0]["text"] = self.lj["selfTest"][4]["question"]
        (self.ep / "script.json").write_text(json.dumps(s))
        self.assertEqual(qc.held_out_check(self.episode(), True)[0]["status"], "fail")


# ------------------------------------------------------------------------------------- Q03

class PermanentLabels(Ws10):
    def test_base_label_with_a_count_fails_after_a_server_joins(self):
        world = {"layout": "ring", "nodes": [{"id": "A", "label": "A", "role": "owner", "pos": 1},
                                             {"id": "D", "label": "D", "role": "owner", "pos": 9, "revealAtMs": 6000},
                                             {"id": "c", "label": "4 keys per server", "revealAtMs": 1000}], "edges": []}
        steps = [{"atMs": 1000, "reveal": ["c"]}, {"atMs": 6000, "reveal": ["D"]}]
        ep = self.demo([{"id": "w", "type": "world", "startMs": 0, "endMs": 30000, "props": {"steps": steps}}], world=world)
        self.assertTrue(qc.renderer_expires_labels(ep.remotion))
        c = qc.labels_stale(ep)[0]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("4 keys per server", c["detail"])
        # a caption that names a quantity but states no number is not stale
        world["nodes"][2]["label"] = "keys per server"
        self.assertEqual(qc.labels_stale(self.demo([{"id": "w", "type": "world", "startMs": 0, "endMs": 30000,
                                                    "props": {"steps": steps}}], world=world))[0]["status"], "pass")


# ------------------------------------------------------------------------------------- Q05

class ClaimText(Ws10):
    CLAIM = {"kind": "count", "scope": "columns-changed", "value": 3, "of": 4}

    def test_function(self):
        self.assertIsNotNone(pc.claim_text_problem("0 of 4 move", self.CLAIM))
        self.assertIsNone(pc.claim_text_problem("3 of 4 move", self.CLAIM))
        self.assertIsNotNone(pc.claim_text_problem("2 move", self.CLAIM))
        self.assertIsNotNone(pc.claim_text_problem("none move", self.CLAIM))
        self.assertIsNone(pc.claim_text_problem("most move", self.CLAIM))

    def test_labels_counts_rejects_contradicting_text(self):
        sc = compare_scene(["A", "B", "C", "A"], ["D", "D", "D", "A"])
        sc["props"]["left"]["steps"] = [{"atMs": 1000, "stat": {"text": "0 of 4 move", "claim": {**self.CLAIM, "side": "left"}}}]
        c = qc.labels_counts(self.demo([sc]))[0]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("0 of 4", c["detail"])
        sc["props"]["left"]["steps"][0]["stat"]["text"] = "3 of 4 move"
        self.assertEqual(qc.labels_counts(self.demo([sc]))[0]["status"], "pass")

    def test_build_manifest_finds_every_claim(self):
        props = {"left": {"steps": [{"stat": {"text": "0 of 4 move", "claim": self.CLAIM}}]}, "banners": [{"text": "3 of 4", "claim": self.CLAIM}]}
        found = pc.claim_texts(props)
        self.assertEqual(len(found), 2)
        self.assertEqual([bool(pc.claim_text_problem(t, c)) for _, t, c in found], [True, False])
        self.assertIn("pc.claim_text_problem", (SCRIPTS / "build_manifest.py").read_text())


# ------------------------------------------------------------------------------------- Q06

class LexiconTerms(unittest.TestCase):
    def test_critical_canonical_term_is_refused(self):
        lx = {"not": ["really"]}
        self.assertTrue(pc.lexicon_problems(lx))
        self.assertEqual(pc.lexicon_map(lx), [])
        self.assertEqual(pc.turn_fidelity("It is not safe.", "It is really safe.", lx)["status"], "fail")
        for term in ("4", "never", "increase", "false"):
            self.assertTrue(pc.lexicon_problems({term: ["x"]}), term)
        self.assertEqual(pc.lexicon_problems({"Priya": ["prayer"]}), [])


# ------------------------------------------------------------------------------------- Q09

class RepairCommands(unittest.TestCase):
    def test_every_fix_is_a_runnable_command(self):
        import preflight
        t = preflight.Table()
        with mock.patch.object(preflight, "run", return_value=(127, "not found")), mock.patch.object(preflight.shutil, "which", return_value=None):
            preflight.check_tools(t)
        preflight.check_gemini(t, None, "", True, False)
        preflight.check_workspace(t, Path("/private/tmp/My Lessons/explainers"))
        preflight.check_whisper(t, Path("/private/tmp/My Lessons/explainers"), False, Path("/private/tmp/no such cache"))
        fixes = [r["fix"] for r in t.rows if r["fix"]]
        self.assertTrue(any("--warm" in f for f in fixes))
        self.assertTrue(any("warm-whisper" in r.get("note", "") for r in t.rows))
        sh = shutil.which("zsh") or shutil.which("bash")
        for f in fixes:
            self.assertNotIn("(or:", f)
            self.assertNotIn("(need", f)
            if sh:
                r = subprocess.run([sh, "-n", "-c", f], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, (f, r.stderr))
        out = quiet(preflight.print_table, t)[1]
        self.assertIn("# or: python3", out)


# ------------------------------------------------------------------------------------- Q04, Q10, judge v6

class LearnAndLibrary(TmpWs):
    def setUp(self):
        super().setUp()
        script = sample_script()
        (self.ep / "script.json").write_text(json.dumps(script))
        (self.ep / "timing.json").write_text(json.dumps(sample_timing(script)))
        shutil.copy(EVALS / "sample-learn.json", self.ep / "learn.json")
        shutil.copy(EVALS / "sample-facts.json", self.ep / "facts.json")
        (self.ep / "out").mkdir()
        (self.ep / "out" / "episode.mp4").write_bytes(b"not a real mp4")

    def build(self, expect=0):
        import learn
        import transcript
        rv, out, err = quiet(learn.main, ["--workspace", str(self.ws), "--slug", "hash-maps"])
        self.assertEqual(rv, expect, err)
        if expect:
            return err
        rv, _, err2 = quiet(transcript.main, ["--workspace", str(self.ws), "--slug", "hash-maps", "--date", "2026-11-03"])
        self.assertEqual(rv, 0, err2)
        return err

    def learn_json(self):
        return json.loads((self.ep / "learn.json").read_text())

    def put(self, lj):
        (self.ep / "learn.json").write_text(json.dumps(lj))

    def rec(self):
        return next(e for e in json.loads((self.ws / "library" / "index.json").read_text())["episodes"] if e["slug"] == "hash-maps")

    def final_problems(self):
        ep = self.episode()
        return qc.delivery_problems(ep, self.rec()) + qc.library_learn_problems(ep) + qc.summary_link_problems(ep)

    def test_q04_library_copy_and_record_are_verified(self):
        self.build()
        self.assertEqual(self.final_problems(), [])
        self.assertIn("record", json.loads((self.ep / "delivery.json").read_text()))
        lib_self = self.ws / "library" / "learn" / "hash-maps" / "selftest.md"
        good = lib_self.read_text()
        lib_self.write_text("# obsolete self-test\n")
        self.assertTrue(any("library/learn/hash-maps/selftest.md differs" in p for p in self.final_problems()))
        lib_self.write_text(good)
        idx_path = self.ws / "library" / "index.json"
        idx = json.loads(idx_path.read_text())
        idx["episodes"][0]["mp4"] = "/tmp/wrong-video.mp4"
        idx["episodes"][0]["cards"] = []
        idx_path.write_text(json.dumps(idx))
        probs = self.final_problems()
        self.assertTrue(any("record for hash-maps differs" in p and "mp4" in p and "cards" in p for p in probs), probs)
        self.assertTrue(any("changed after transcript.py bound it" in p for p in probs), probs)

    def test_q10_missing_hero_still_is_omitted(self):
        lj = self.learn_json()
        lj["summary"]["heroStill"] = "qc/hero-example.png"
        self.put(lj)
        err = self.build()
        self.assertIn("heroStill", err)
        summary = (self.ep / "learn" / "summary.md").read_text()
        self.assertNotIn("hero-example.png", summary)
        (self.ep / "qc" / "stills").mkdir(parents=True)
        (self.ep / "qc" / "stills" / "turn-t06.png").write_bytes(b"png")
        lj["summary"]["heroStill"] = "qc/stills/turn-t06.png"
        self.put(lj)
        self.build()
        self.assertIn("turn-t06.png", (self.ep / "learn" / "summary.md").read_text())
        self.assertEqual(qc.summary_link_problems(self.episode()), [])
        (self.ep / "qc" / "stills" / "turn-t06.png").unlink()
        self.assertTrue(qc.summary_link_problems(self.episode()))

    def test_judge_v6_self_test_rules(self):
        lj = self.learn_json()
        lj["selfTest"] = lj["selfTest"] + [dict(lj["selfTest"][0]), dict(lj["selfTest"][0])]
        for q in lj["selfTest"][5:]:
            q.pop("heldOut", None)
        self.put(lj)
        self.assertIn("exactly 5", self.build(expect=1))
        (self.ep / "brief.json").write_text(json.dumps({"selfTestCount": 7}))
        self.build()
        lj = self.learn_json()
        lj["selfTest"] = lj["selfTest"][:5]
        for q in lj["selfTest"]:
            q["level"] = "understand"
            q.pop("heldOut", None)
        lj["selfTest"][0]["level"] = lj["selfTest"][1]["level"] = "remember"
        self.put(lj)
        (self.ep / "brief.json").write_text(json.dumps({}))
        err = self.build(expect=1)
        self.assertIn("no apply or transfer", err)
        self.assertIn("2 remember-level", err)

    def test_judge_v6_analogy_card(self):
        s = sample_script()
        s["segments"][2]["role"] = "analogy"
        (self.ep / "script.json").write_text(json.dumps(s))
        self.assertIn("analogy-limit card", self.build(expect=1))
        lj = self.learn_json()
        lj["cards"][0]["front"] = "Where does the library-shelf analogy break?"
        self.put(lj)
        self.build()


# ------------------------------------------------------------------------------------- stumble 5

class RowLabels(unittest.TestCase):
    def panel(self, label):
        return {"kind": "table", "columns": ["k1", "k2", "k3", "k4"],
                "rows": [{"id": "r1", "label": label, "cells": ["A", "B", "C", "A"]}, {"id": "r2", "label": "After", "cells": ["D", "D", "B", "A"]}]}

    def test_label_column_grows_then_refuses(self):
        L = pc.panel_table_layout(self.panel("Before change"), True)
        self.assertGreaterEqual(L["labelW"], 291)
        self.assertEqual(L["labelFont"], 36)
        self.assertEqual(pc.table_problems(self.panel("Before change"), True), [])
        probs = pc.table_problems(self.panel("Before the fourth server joined"), True)
        self.assertTrue(any("row label" in p and "18 characters or fewer" in p for p in probs), probs)


# ------------------------------------------------------------------------------------- D03 and the v6 judge

class LongerLazyLesson(unittest.TestCase):
    LAZY = ("How does the mechanism work? For example, Alice says mechanism means a process because a step happens, "
            "so a result follows. That mechanism belief is not correct.")

    def test_codex_round4_lazy_lesson_fails(self):
        data = sample_script()
        for seg in data["segments"]:
            for t in seg["turns"]:
                t["text"] = self.LAZY
                t["onScreen"] = ["mechanism"]
        data["targetMinutes"] = round(pc.predict_length(data)["totalSec"] / 60, 2)
        facts = json.loads((EVALS / "sample-facts.json").read_text())
        rep = vs.Report("x")
        vs.check_script(data, facts, data["targetMinutes"], 45, "per-turn", rep, None, None)
        codes = {e["code"] for e in rep.errors}
        for c in ("E45", "E46", "E47"):
            self.assertIn(c, codes, codes)
        roles = {s["id"]: s["role"] for s in data["segments"]}
        new = [e for e in rep.errors if e["code"] in ("E45", "E46", "E47")]
        self.assertTrue(all(roles[e["segment"]] in ("mechanism", "misconception") for e in new), new)

    def test_sample_passes(self):
        facts = json.loads((EVALS / "sample-facts.json").read_text())
        data = sample_script()
        rep = vs.Report("x")
        vs.check_script(data, facts, data["targetMinutes"], 45, "per-turn", rep, None, None)
        self.assertEqual(rep.errors, [])

    @unittest.skipUnless((V6 / "script.json").is_file(), "v6 workspace not present")
    def test_v6_script_passes_the_new_teaching_checks(self):
        load = lambda n: json.loads((V6 / n).read_text())
        rep = vs.Report("v6")
        vs.check_script(load("script.json"), load("facts.json"), 12, 45, "per-turn", rep, load("brief.json"), load("outline.json"))
        self.assertFalse([e for e in rep.errors if e["code"] in ("E45", "E46", "E47", "E48")], rep.errors)

    def test_unsourced_rule_in_a_mechanism_is_an_error(self):
        data = sample_script()
        mech = next(s for s in data["segments"] if s["role"] == "mechanism")
        t = next(x for x in mech["turns"] if dict((s["id"], s["role"]) for s in data["speakers"])[x["speaker"]] == "expert")
        t["text"] = "Two names on one spot always get rehashed."
        t["factIds"] = []
        rep = vs.Report("x")
        vs.check_script(data, None, data["targetMinutes"], 45, "per-turn", rep, None, None)
        self.assertIn(("E48", t["id"]), {(e["code"], e["turn"]) for e in rep.errors})
        self.assertIn(("W49", t["id"]), {(w["code"], w["turn"]) for w in rep.warnings})


if __name__ == "__main__":
    unittest.main()
