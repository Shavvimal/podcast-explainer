"""W18 (v9 patch of consistent-hashing): labels.early reviewed leads (`earlyOk`), the final gate,
banner side labels as cued labels, and the "A-one" id in fidelity tokens. Run from the skill folder:

    python3 -m unittest tests.test_w18 -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pe_common as pc  # noqa: E402
import qc  # noqa: E402
from test_w16 import turn  # noqa: E402


def manifest(steps, turns, banners=None, overlays=None):
    props = {"left": {"kind": "table", "steps": steps}}
    if banners is not None:
        props["banners"] = banners
    return {"video": {"fps": 30}, "turns": turns, "overlays": overlays or [],
            "scenes": [{"id": "sc07", "type": "compare", "startMs": 0, "endMs": 60000, "props": props}]}


def episode(m, final=False):
    class E:
        def need_manifest(self):
            return m
    e = E()
    e.final = final
    return e


TURNS = [turn("t63", 0, "With mod most jobs move"), turn("t64", 12000, "it moves 8 of 12")]


class EarlyOk(unittest.TestCase):
    def test_problem_carries_the_reason(self):
        probs = pc.early_label_problems(manifest([{"atMs": 600, "stat": "moved: 8 of 12", "earlyOk": "cold-open prompt"}], TURNS))
        self.assertEqual(len(probs), 1)
        self.assertEqual(probs[0]["earlyOk"], "cold-open prompt")

    def test_unmarked_problem_has_no_reason(self):
        probs = pc.early_label_problems(manifest([{"atMs": 600, "stat": "moved: 8 of 12"}], TURNS))
        self.assertIsNone(probs[0]["earlyOk"])

    def test_blank_reason_does_not_count(self):
        probs = pc.early_label_problems(manifest([{"atMs": 600, "stat": "moved: 8 of 12", "earlyOk": "  "}], TURNS))
        self.assertIsNone(probs[0]["earlyOk"])

    def test_overlay_chip_reason(self):
        ov = [{"id": "c1", "type": "chip", "startMs": 600, "endMs": 5000, "props": {"text": "8 of 12", "earlyOk": "same quantity in other words"}}]
        probs = pc.early_label_problems(manifest([], TURNS, overlays=ov))
        self.assertEqual([(p["where"], p["earlyOk"]) for p in probs], [("overlay c1", "same quantity in other words")])


class FinalGate(unittest.TestCase):
    def test_unreviewed_warns_in_diagnostic_run(self):
        c = qc.labels_early(episode(manifest([{"atMs": 600, "stat": "moved: 8 of 12"}], TURNS)))[0]
        self.assertEqual((c["id"], c["status"]), ("labels.early", "warn"))
        self.assertIn("unreviewed", c["detail"])
        self.assertIn("earlyOk", c["fix"])

    def test_unreviewed_fails_under_final(self):
        c = qc.labels_early(episode(manifest([{"atMs": 600, "stat": "moved: 8 of 12"}], TURNS), final=True))[0]
        self.assertEqual(c["status"], "fail")

    def test_reviewed_passes_under_final_and_is_listed(self):
        m = manifest([{"atMs": 600, "stat": "moved: 8 of 12", "earlyOk": "recap count carried from seg03"}], TURNS)
        c = qc.labels_early(episode(m, final=True))[0]
        self.assertEqual(c["status"], "pass")
        self.assertIn("1 reviewed earlyOk", c["detail"])
        self.assertIn("recap count carried from seg03", c["detail"])

    def test_mixed_reviewed_and_unreviewed_still_fails(self):
        m = manifest([{"atMs": 600, "stat": "moved: 8 of 12", "earlyOk": "cold open"},
                      {"atMs": 900, "note": "it is 12 in all"}], TURNS)
        c = qc.labels_early(episode(m, final=True))[0]
        self.assertEqual(c["status"], "fail")
        self.assertIn("1 unreviewed", c["detail"])
        self.assertIn("1 reviewed earlyOk", c["detail"])

    def test_nothing_early_passes(self):
        c = qc.labels_early(episode(manifest([{"atMs": 12100, "stat": "moved: 8 of 12"}], TURNS), final=True))[0]
        self.assertEqual(c["status"], "pass")


class BannerLabels(unittest.TestCase):
    def test_side_label_shown_early_is_reported(self):
        turns = [turn("t115", 0, "Give it twice the points say 1 and 7 Then it owns 4 of 12 jobs")]
        b = [{"text": "2 points: 2 stretches", "winner": "none", "labels": {"right": "R5 owns 4 of 12"}, "atMs": 0}]
        probs = pc.early_label_problems(manifest([], turns, banners=b))
        self.assertTrue(any(p["where"].endswith("labels.right") and p["number"] == "4 of 12" for p in probs), probs)

    def test_side_label_on_its_word_passes(self):
        turns = [turn("t115", 0, "Give it twice the points say 1 and 7 Then it owns 4 of 12 jobs")]
        b = [{"text": "two stretches", "winner": "none", "labels": {"right": "R5 owns 4 of 12"}, "atMs": 13 * 300}]
        self.assertEqual(pc.early_label_problems(manifest([], turns, banners=b)), [])


class SchemaAllowsEarlyOk(unittest.TestCase):
    def test_scenes_schema_lists_early_ok(self):
        s = json.loads((SKILL / "schemas" / "scenes.schema.json").read_text())
        d = s["$defs"]
        self.assertIn("earlyOk", d["worldStep"]["properties"])
        self.assertIn("earlyOk", d["panelStep"]["properties"])
        self.assertIn("earlyOk", d["banner"]["properties"])
        self.assertIn("earlyOk", d["overlay"]["properties"]["props"]["properties"])


class LetterOneId(unittest.TestCase):
    def test_hyphenated_letter_one_is_the_digit(self):
        self.assertEqual(pc.fidelity_tokens("say A-one and A-two"), ["say", "a", "1", "and", "a", "2"])

    def test_lone_one_and_compounds_unchanged(self):
        self.assertEqual(pc.fidelity_tokens("a one-off, no-one"), ["a", "one", "off", "no", "one"])

    def test_asr_a1_is_not_critical_for_a_one(self):
        r = pc.turn_fidelity("say A-one and A-two. A lands", "say A1 and A2. A lands")
        self.assertEqual(r["status"], "ok", r)

    def test_a_different_id_digit_still_fails(self):
        r = pc.turn_fidelity("say A-one and A-two. A lands", "say A3 and A2. A lands")
        self.assertEqual(r["status"], "fail", r)


if __name__ == "__main__":
    unittest.main()
