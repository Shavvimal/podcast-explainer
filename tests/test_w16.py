"""W16 (final fix pass): the defects found by the two-part attention series (internal run notes)
and the W15 labels.early proposal. Python only; the renderer parity tests and stills are in
tests/test_renderer_w16.py. Run from the skill folder:

    python3 -m unittest tests.test_w16 -v
"""
from __future__ import annotations

import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
TEMPLATE = SKILL / "templates" / "remotion"
MATRIX_INPUTS = TEMPLATE / "sample-inputs" / "matrix"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_manifest as bm  # noqa: E402
import export_delivery as ex  # noqa: E402
import fidelity  # noqa: E402
import pe_common as pc  # noqa: E402
import preflight  # noqa: E402
import qc  # noqa: E402
import search  # noqa: E402
import validate_script as vs  # noqa: E402
from test_w7 import run_build  # noqa: E402
from test_w13a_export import make_workspace  # noqa: E402


def tmp(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


# ------------------------------------------------------------------------------- (2) fidelity

class FidelityPrefixes(unittest.TestCase):
    def status(self, script, heard, lex=None):
        return pc.turn_fidelity(script, heard, lex)

    def test_real_negating_prefixes_still_fail(self):
        for s, h in (("The token is valid.", "The token is invalid."), ("The user is authenticated.", "The user is unauthenticated."),
                     ("You can connect now.", "You can disconnect now."), ("It is able to spread keys.", "It is unable to spread keys."),
                     ("The list is sorted.", "The list is unsorted."), ("The call is safe.", "The call is unsafe."),
                     ("Both nodes are connected.", "Both nodes are disconnected.")):
            r = self.status(s, h)
            self.assertEqual(r["status"], "fail", (s, h, r))
            self.assertTrue(any("meaning changes" in c for c in r["critical"]), r)

    def test_coincidental_prefixes_are_not_critical(self):
        # W14b D12, part 2: "detail" heard as "tail", "on tired" merged into "untired"
        for s, h in (("One more detail here.", "One more tail here."), ("I am tired today.", "I am untired today."),
                     ("Check the detail now.", "Check the tail now.")):
            r = self.status(s, h)
            self.assertNotEqual(r["status"], "fail", (s, h, r))
            self.assertEqual(r["critical"], [], r)

    def test_lone_one_is_a_word_not_the_digit(self):
        self.assertEqual(pc.fidelity_tokens("One detail matters")[0], "one")
        self.assertEqual(pc.fidelity_tokens("one of four servers")[:3], ["1", "of", "4"])  # a number nearby: a count
        self.assertEqual(pc.fidelity_tokens("one second")[0], "1")
        for s, h in (("One detail matters.", "One's tail matters."), ("One detail.", "Once detail.")):
            self.assertEqual(self.status(s, h)["critical"], [], (s, h))
        self.assertEqual(self.status("He had 1 key.", "He had one key.")["status"], "ok")
        self.assertEqual(self.status("one of four servers", "two of four servers")["status"], "fail")

    def test_name_only_warns_print_a_lexicon_suggestion(self):
        script = {"speakers": [{"id": "host", "name": "Nia"}],
                  "segments": [{"turns": [{"id": "t01", "text": "So Priya, what does Bahdanau add? Ask Nia."}]}]}
        rep = {"turns": [{"diff": [{"op": "sub", "script": "priya", "heard": "chev"}, {"op": "sub", "script": "bahdanau", "heard": "badenot"},
                                   {"op": "sub", "script": "nia", "heard": "not"}, {"op": "sub", "script": "the", "heard": "a"}]}]}
        sug = fidelity.name_suggestions(script, rep)
        self.assertEqual(sug, {"Priya": ["chev"], "Bahdanau": ["badenot"]})  # "not" is refused by E40, "the" is no name

    def test_headless_advice_is_documented(self):
        self.assertIn("Headless runs", (SKILL / "scripts" / "fidelity.py").read_text())


# ------------------------------------------------------------------------------- (3) E40

class LexiconSplitAlias(unittest.TestCase):
    def test_split_or_joined_alias_is_allowed(self):
        self.assertEqual(pc.lexicon_problems({"softmax": ["soft max", "soft mask"]}), [])
        self.assertEqual(pc.lexicon_problems({"hash map": ["hashmap"]}), [])
        r = pc.turn_fidelity("Apply softmax to the scores.", "Apply soft max to the scores.", {"softmax": ["soft max"]})
        self.assertEqual(r["status"], "ok", r)

    def test_meaning_changing_aliases_are_still_refused(self):
        self.assertTrue(pc.lexicon_problems({"softmax": ["min"]}))
        self.assertTrue(pc.lexicon_problems({"it": ["it 4"]}))
        self.assertTrue(pc.lexicon_problems({"max pool": ["maxpool"]}))  # the term itself holds a direction word
        self.assertTrue(pc.lexicon_problems({"valid": ["invalid"]}))


# ------------------------------------------------------------------------------- (1) tables and matrix

class TableCells(unittest.TestCase):
    def schema_errors(self, props):
        schema = json.loads((SKILL / "schemas" / "scenes.schema.json").read_text())
        doc = {"version": 1, "scenes": [{"id": "s1", "type": "compare", "anchor": {"from": {"turn": "t01"}}, "props": props}]}
        return bm._mini_validate(doc, schema)

    def test_twelve_character_cells_fit_a_two_column_table(self):
        panel = {"title": "t", "kind": "table", "columns": ["before", "after"],
                 "rows": [{"id": "a", "label": "query it", "cells": ["minus inf 12", "0.81 to 0.26"]}]}
        self.assertEqual(pc.table_problems(panel, False), [])
        L = pc.panel_table_layout(panel, False)
        self.assertGreaterEqual(L["font"], 28)
        self.assertGreater(L["cellW"], L["cell"])  # the cell widened for its text
        right = {"title": "r", "kind": "text", "lines": [{"text": "x"}]}
        self.assertEqual(self.schema_errors({"left": panel, "right": right}), [])
        bad = copy.deepcopy(panel)
        bad["rows"][0]["cells"][0] = "x" * 13
        self.assertTrue(any("longer than 12" in e for e in self.schema_errors({"left": bad, "right": right})))

    def test_short_text_keeps_square_cells(self):
        L = pc.table_layout(12, 2, *pc.compare_body_size(False), True, 2, 6)
        self.assertEqual(L["cellW"], L["cell"])

    def test_wide_table_of_long_cells_is_still_refused(self):
        panel = {"title": "t", "kind": "table", "columns": [f"col{i}" for i in range(10)],
                 "rows": [{"id": r, "label": r, "cells": ["twelve chars"] * 10} for r in ("a", "b")]}
        self.assertTrue(any("text must be at least 28 px" in p for p in pc.table_problems(panel, False)))


def matrix(**kw):
    p = {"rows": ["brick", "fell", "it", "cracked"], "columns": ["brick", "fell", "it", "cracked"],
         "cells": [["0.70", "0.10", "0.05", "0.15"]] * 4, "heat": [[0.7, 0.1, 0.05, 0.15]] * 4}
    p.update(kw)
    return p


class Matrix(unittest.TestCase):
    def test_sample_validates_and_builds(self):
        schema = json.loads((SKILL / "schemas" / "scenes.schema.json").read_text())
        doc = json.loads((MATRIX_INPUTS / "scenes.json").read_text())
        self.assertEqual(bm._mini_validate(doc, schema), [])
        ws = tmp("w16-matrix-")
        try:
            shutil.copytree(MATRIX_INPUTS, ws / "sample-matrix")
            rc, out = run_build(ws, "sample-matrix")
            self.assertEqual(rc, 0, out)
            ep = json.loads((ws / "sample-matrix" / "episode.json").read_text())
            sc = ep["scenes"][0]
            self.assertEqual(sc["type"], "matrix")
            self.assertTrue(all("atMs" in s for s in sc["props"]["steps"]))
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_layout_keeps_text_at_28px(self):
        L = pc.matrix_layout(matrix(title="Weights", rowAxis="query", colAxis="key"))
        self.assertTrue(L["fits"])
        self.assertGreaterEqual(L["font"], 28)
        self.assertEqual(pc.matrix_problems(matrix(title="Weights")), [])

    def test_a_matrix_that_cannot_fit_is_refused_with_the_numbers(self):
        big = matrix(rows=[f"row word {i:02d}" for i in range(8)], columns=[f"column w {i:02d}" for i in range(12)],
                     cells=[["twelve chars"] * 12] * 8, heat=None)
        probs = pc.matrix_problems(big)
        self.assertEqual(len(probs), 1, probs)
        self.assertIn("text must be at least 28 px", probs[0])
        self.assertIn("At most 6 columns fit", probs[0])
        tall = matrix(rows=[f"r{i}" for i in range(12)], cells=[["0.1"] * 4] * 12, heat=None, title="t", rowAxis="q", colAxis="k")
        self.assertIn("No column count fits 12 rows", pc.matrix_problems(tall)[0])
        ws = tmp("w16-matrix-big-")
        try:
            shutil.copytree(MATRIX_INPUTS, ws / "m")
            doc = json.loads((ws / "m" / "scenes.json").read_text())
            doc["scenes"][0]["props"].update(rows=big["rows"], columns=big["columns"], cells=big["cells"])
            doc["scenes"][0]["props"].pop("heat")
            doc["scenes"][0]["props"]["steps"] = []
            (ws / "m" / "scenes.json").write_text(json.dumps(doc))
            rc, out = run_build(ws, "m")
            self.assertNotEqual(rc, 0)
            self.assertIn("text must be at least 28 px", out)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_shape_and_reference_problems(self):
        self.assertTrue(any("cells has 3 rows" in p for p in pc.matrix_problems(matrix(cells=[["a"] * 4] * 3))))
        self.assertTrue(any("outside 0..1" in p for p in pc.matrix_problems(matrix(heat=[[1.5, 0, 0, 0]] * 4))))
        steps = [{"atMs": 0, "highlight": [{"row": "glass"}]}]
        self.assertTrue(any("not one row header" in p for p in pc.matrix_problems(matrix(steps=steps))))
        dup = matrix(rows=["the", "cat", "the", "sat"], steps=[{"atMs": 0, "highlight": [{"row": "the"}]}])
        self.assertTrue(any("use its index" in p for p in pc.matrix_problems(dup)))

    def test_highlight_expires_at_next_step_unless_persist(self):
        p = matrix(steps=[{"atMs": 1000, "highlight": [{"row": "it", "col": "brick"}], "note": "it to brick"},
                          {"atMs": 3000, "highlight": [{"col": 1}]},
                          {"atMs": 5000, "highlight": [{"row": 0}], "persist": True},
                          {"atMs": 7000, "note": "done"}])
        at = lambda ms: pc.matrix_state_at(p, 0, 30, pc.ms_to_frame(ms, 30))
        s = at(2000)
        self.assertEqual((s["cells"], s["note"]), ({"2,0"}, "it to brick"))
        s = at(4000)
        self.assertEqual((s["cells"], s["cols"], s["note"]), (set(), {1}, None))
        s = at(8000)
        self.assertEqual((s["rows"], s["cols"], s["note"]), ({0}, set(), "done"))

    def test_visible_text_lists_headers_cells_and_note(self):
        p = matrix(title="Weights", steps=[{"atMs": 1000, "note": "it to brick"}])
        m = {"video": {"fps": 30}, "scenes": [{"id": "s", "type": "matrix", "startMs": 0, "endMs": 9000, "props": p}], "overlays": []}
        texts = pc.scene_texts_at(m, m["scenes"][0], 2000)
        for t in ("Weights", "cracked", "0.70", "it to brick"):
            self.assertIn(t, texts)
        self.assertNotIn("it to brick", pc.scene_texts_at(m, m["scenes"][0], 100))

    def test_heat_colour_keeps_text_contrast(self):
        src = (TEMPLATE / "src" / "scenes" / "MatrixScene.tsx").read_text()
        heat = src.split('MATRIX_HEAT = "')[1][:7]
        self.assertGreaterEqual(qc.contrast(qc.color_rgb(heat), qc.color_rgb("#F2F4F8")), 4.5)

    def test_qc_reads_the_matrix_text_size(self):
        class E:  # the part of qc.Episode that builtin_text reads
            remotion = TEMPLATE
            manifest = {"video": {"fps": 30}, "scenes": [{"id": "s1", "type": "matrix", "startMs": 0, "endMs": 1000,
                                                          "props": matrix(cells=[["twelve chars"] * 4] * 4,
                                                                          rows=["r"] * 12, heat=None)}]}

            def need_manifest(self):
                return self.manifest
        out = qc.builtin_text(E())
        self.assertTrue(any("s1 matrix" in r for r in out["read"]))


# ------------------------------------------------------------------------------- (7) pill

class PillHeight(unittest.TestCase):
    def test_pill_grows_for_a_value(self):
        self.assertEqual(pc.node_size({"shape": "pill"})[1], 88)
        self.assertEqual(pc.node_size({"shape": "pill", "value": "x"})[1], 128)
        self.assertEqual(pc.node_size({"shape": "pill", "sublabel": "s", "value": "x"})[1], 160)
        self.assertEqual(pc.node_size({"value": "x"})[1], 160)  # box unchanged

    def test_nodefit_catches_a_short_node(self):
        world = {"nodes": [{"id": "scale", "label": "÷ 8", "sublabel": "scales scores", "shape": "pill", "h": 88, "x": 0, "y": 0},
                           {"id": "softmax", "label": "softmax", "sublabel": "scores to weights", "shape": "pill", "x": 0, "y": 0}]}
        tl = [{"t": 1000, "set": {"scale": {"value": "root 64 = 8"}}}]
        probs = pc.node_fit_problems(world, tl)
        self.assertEqual(len(probs), 1, probs)
        self.assertIn("node scale (pill)", probs[0])
        world["nodes"][0].pop("h")  # the default height grows to 160
        self.assertEqual(pc.node_fit_problems(world, tl), [])

    def test_qc_check_reports_it(self):
        class E:
            manifest = {"video": {"fps": 30}, "world": {"nodes": [{"id": "p", "label": "x", "sublabel": "y", "value": "z", "shape": "pill", "h": 88}]},
                        "scenes": [{"id": "s1", "type": "world", "startMs": 0, "endMs": 1000, "props": {"steps": []}}]}

            def need_manifest(self):
                return self.manifest
        c = qc.world_nodefit(E())[0]
        self.assertEqual((c["id"], c["status"]), ("world.nodefit", "fail"))


# ------------------------------------------------------------------------------- (8) labels.early

def turn(tid, a, text, per=300):
    ws = [{"text": w, "startMs": a + i * per, "endMs": a + i * per + per - 20} for i, w in enumerate(text.split())]
    return {"id": tid, "text": text, "startMs": a, "endMs": ws[-1]["endMs"], "words": ws}


class LabelsEarly(unittest.TestCase):
    def manifest(self, steps, turns):
        return {"video": {"fps": 30}, "turns": turns, "overlays": [],
                "scenes": [{"id": "sc07", "type": "compare", "startMs": 0, "endMs": 60000,
                            "props": {"left": {"kind": "table", "steps": steps}}}]}

    def test_count_shown_a_turn_early_warns_with_turn_and_lead(self):
        turns = [turn("t63", 0, "With mod most jobs get a new robot"), turn("t64", 12000, "Mod 4 to mod 5 moves 8 of 12")]
        probs = pc.early_label_problems(self.manifest([{"atMs": 600, "stat": "moved: 8 of 12"}], turns))
        self.assertEqual(len(probs), 1, probs)
        p = probs[0]
        self.assertEqual((p["number"], p["turn"], p["spokenTurn"]), ("8 of 12", "t63", "t64"))
        self.assertEqual(p["leadMs"], 12000 + 6 * 300 - 600)  # "8" is the 7th word of t64

    def test_anchored_on_the_word_or_recap_passes(self):
        turns = [turn("t63", 0, "So 8 of 12 moved"), turn("t64", 12000, "Again 8 of 12 moved")]
        self.assertEqual(pc.early_label_problems(self.manifest([{"atMs": 300, "stat": "moved: 8 of 12"},
                                                                {"atMs": 12100, "stat": "8 of 12 again"}], turns)), [])
        # within the turn that speaks it, a short lead passes
        turns = [turn("t01", 0, "the weight is 0.81 for brick")]
        self.assertEqual(pc.early_label_problems(self.manifest([{"atMs": 0, "note": "w 0.81"}], turns)), [])

    def test_ids_and_words_are_not_quantities(self):
        turns = [turn("t01", 0, "remainder zero goes to the first robot"), turn("t02", 9000, "R1 one more")]
        self.assertEqual(pc.early_label_problems(self.manifest([{"atMs": 0, "stat": "one rule for R1"}], turns)), [])

    def test_qc_check_is_a_warning(self):
        turns = [turn("t63", 0, "With mod most jobs move"), turn("t64", 12000, "it moves 8 of 12")]

        class E:
            manifest = self.manifest([{"atMs": 600, "stat": "moved: 8 of 12"}], turns)

            def need_manifest(self):
                return self.manifest
        c = qc.labels_early(E())[0]
        self.assertEqual(c["status"], "warn")
        self.assertIn("in t63", c["detail"])
        self.assertIn("before t64 speaks it", c["detail"])

    def test_v7_defect_is_caught(self):
        p = Path(os.environ.get("PE_EXAMPLE_V7_EPISODE", "/nonexistent/consistent-hashing-v7/episode.json"))  # an old example build, when present
        if not p.is_file():
            self.skipTest("examples/consistent-hashing-v7 not present")
        probs = pc.early_label_problems(json.loads(p.read_text()))
        self.assertTrue(any(x["text"] == "moved: 8 of 12" and x["turn"] == "t63" and x["spokenTurn"] == "t64" for x in probs), probs)


# ------------------------------------------------------------------------------- (9) diagram hide, D16 empty stage

class BuildWarnings(unittest.TestCase):
    def test_reveal_after_hide_warns(self):
        steps = [{"hide": ["neg"]}, {"reveal": ["zero"]}, {"reveal": ["neg"]}]
        probs = bm.diagram_hide_problems(steps)
        self.assertEqual(len(probs), 1)
        self.assertIn("'neg'", probs[0])
        self.assertEqual(bm.diagram_hide_problems([{"reveal": ["a"]}, {"hide": ["a"]}]), [])

    def test_empty_stage_lead(self):
        sc = {"type": "equation", "startMs": 1000, "props": {"lines": [{"text": "a", "atMs": 6000}, {"text": "b", "atMs": 7000}]}}
        self.assertEqual(bm.empty_stage_ms(sc), 5000)
        sc["props"]["lines"][0].pop("atMs")  # a line without a cue shows at its fallback frame
        self.assertIsNone(bm.empty_stage_ms(sc))
        cmp = {"type": "compare", "startMs": 0, "props": {"left": {"kind": "text", "lines": [{"text": "x", "atMs": 3000}]},
                                                          "right": {"kind": "table", "rows": []}}}
        self.assertIsNone(bm.empty_stage_ms(cmp))  # a table panel is never empty


# ------------------------------------------------------------------------------- (10) W21 and E13 on the deep skeleton

class DeepSkeleton(unittest.TestCase):
    def check(self, roles_goals, part):
        segs = [{"id": f"seg{i + 1:02d}", "role": r, "learningGoal": g, "title": ""} for i, (r, g) in enumerate(roles_goals)]
        data = {"depth": "deep", "series": {"id": "att", "part": part, "parts": 2}}
        rep = vs.Report("outline.json")
        vs.check_structure(data, segs, 11, rep)
        return [(p["code"], p["message"]) for p in rep.items]

    def test_part_1_following_the_skeleton_validates_clean(self):
        items = self.check([("hook", "Predict"), ("plain", "First principles"), ("example", "Worked example 1"),
                            ("terms", "Terms"), ("misconception", "Refute"), ("selftest", "H, I: M7; one question left open")], 1)
        self.assertFalse([i for i in items if i[0] in ("W21", "E13")], items)

    def test_part_2_explain_back_goal_passes(self):
        items = self.check([("recap", "Two retrieval questions"), ("mechanism", "Learner drives"), ("analogy", "Map it"),
                            ("misconception", "Second one"), ("transfer", "Apply"), ("selftest", "Full explain-back, next-time question")], 2)
        self.assertFalse([i for i in items if i[0] in ("W21", "E13")], items)

    def test_unsplit_deep_still_needs_two_checks(self):
        segs = [{"id": "seg01", "role": "hook"}, {"id": "seg02", "role": "misconception"}, {"id": "seg03", "role": "recap"},
                {"id": "seg04", "role": "selftest"}]
        rep = vs.Report("outline.json")
        vs.check_structure({"depth": "deep"}, segs, 11, rep)
        self.assertTrue(any(p["code"] == "E21" for p in rep.items))


# ------------------------------------------------------------------------------- (4, 11) restater first, reply storage

class Replies(unittest.TestCase):
    def test_docs_run_the_restater_first(self):
        skill = (SKILL / "SKILL.md").read_text()
        qcmd = (SKILL / "references" / "qc.md").read_text()
        self.assertIn("restate agent FIRST", qcmd)
        self.assertIn("restater FIRST", skill)
        self.assertNotIn("in parallel", skill)
        self.assertIn("ran BEFORE you", (SKILL / "scripts" / "qc.py").read_text())
        self.assertIn("cannot be proven", qcmd)
        self.assertIn("as received", qcmd)

    def test_save_reply_records_sha_and_scores_must_match(self):
        ws = tmp("w16-reply-")
        try:
            (ws / "ep" / "qc").mkdir(parents=True)
            reply = ws / "r.md"
            reply.write_text('Scores below.\n```json\n{"score": 4}\n```\n', encoding="utf-8")
            o = io.StringIO()
            with redirect_stdout(o):
                rc = qc.main(["save-reply", "--workspace", str(ws), "--slug", "ep", "--kind", "restate", "--file", str(reply)])
            self.assertEqual(rc, 0, o.getvalue())
            meta = json.loads((ws / "ep" / "qc" / "replies" / "restate.json").read_text())
            self.assertEqual(meta["sha256"], pc.bytes_sha(reply.read_bytes(), 64))
            self.assertEqual((ws / "ep" / "qc" / "replies" / "restate.md").read_text(), reply.read_text())

            class E:
                qc = ws / "ep" / "qc"
            self.assertEqual(qc.stored_reply_problems(E(), {"restate": {"replySha256": meta["sha256"]}}), [])
            self.assertTrue(qc.stored_reply_problems(E(), {"restate": {"replySha256": "0" * 64}}))
            reply.write_text("no json here\n")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(qc.main(["save-reply", "--workspace", str(ws), "--slug", "ep", "--kind", "judge", "--file", str(reply)]), 1)
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# ------------------------------------------------------------------------------- (5) series export

class SeriesExport(unittest.TestCase):
    def test_exports_every_part_the_series_folder_and_an_index(self):
        root = tmp("w16-series-")
        try:
            ws = make_workspace(root, "att-p1")
            make_workspace(root, "att-p2")
            sdir = ws / "att"
            (sdir / "research" / "sources").mkdir(parents=True)
            (sdir / "research" / "sources" / "s1-vaswani.md").write_text("quote\n")
            (sdir / "glossary.json").write_text('{"terms": []}\n')
            (sdir / "series.json").write_text(json.dumps({"version": 1, "id": "att", "title": "Attention", "depth": "deep",
                                                          "parts": [{"part": 1, "slug": "att-p1", "title": "One"},
                                                                    {"part": 2, "slug": "att-p2", "title": "Two"}]}))
            out = root / "export"
            o = io.StringIO()
            with redirect_stdout(o), redirect_stderr(o):
                rc = ex.main(["--workspace", str(ws), "--series", str(sdir / "series.json"), "--to", str(out)])
            self.assertEqual(rc, 0, o.getvalue())
            for rel in ("att-p1/out/episode.mp4", "att-p2/transcript.md", "series/series.json", "series/research/sources/s1-vaswani.md",
                        "index.md", "export.json"):
                self.assertTrue((out / rel).is_file(), rel)
            rec = json.loads((out / "export.json").read_text())
            self.assertEqual(sorted(rec["parts"]), ["att-p1", "att-p2"])
            self.assertEqual(rec["index"]["brokenLinks"], [])
            for rel, d in rec["seriesFiles"].items():
                self.assertEqual(d["sha256"], d["sourceSha256"], rel)
            self.assertIn("(att-p2/out/episode.mp4)", (out / "index.md").read_text())
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(ex.main(["--workspace", str(ws), "--series", str(sdir), "--to", str(out)]), 1)  # not empty
                self.assertEqual(ex.main(["--workspace", str(ws), "--series", str(sdir), "--to", str(out), "--force"]), 0)
                self.assertEqual(ex.main(["--workspace", str(ws), "--series", str(sdir), "--to", str(ws / "inside")]), 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------------------- (6) search ranking

LIB_MD = """---
slug: {slug}
title: "{title}"
---

## [00:00] Chapter 1: Start

{turns}

## Glossary

- **causal mask**{mention}: hides later words
"""


class SearchRanking(unittest.TestCase):
    def test_turns_outrank_the_shared_glossary_and_glossary_links_to_the_teaching_part(self):
        lib = tmp("w16-lib-")
        try:
            (lib / "att-p1.md").write_text(LIB_MD.format(slug="att-p1", title="Part 1", mention="",
                                                         turns="**[00:05] Theo:** Each word scores every word."))
            (lib / "att-p2.md").write_text(LIB_MD.format(slug="att-p2", title="Part 2", mention=" [08:24]",
                                                         turns="**[08:24] Theo:** The causal mask sets later scores to minus infinity."))
            (lib / "index.json").write_text(json.dumps({"version": 1, "episodes": [
                {"slug": "att-p1", "title": "Part 1", "series": {"id": "att", "part": 1, "of": 2}},
                {"slug": "att-p2", "title": "Part 2", "series": {"id": "att", "part": 2, "of": 2}}]}))
            _, chunks = search.load_library(lib)
            g1 = next(c for c in chunks if c["kind"] == "glossary" and c["file"].endswith("att-p1.md"))
            self.assertEqual((g1["slug"], g1["ms"]), ("att-p2", 8 * 60_000 + 24_000))  # links to the part that teaches it
            self.assertIn("taught in att-p2", g1["text"])
            for engine in ("bm25", "rg"):
                if engine == "rg" and not shutil.which("rg"):
                    continue
                res = search.bm25("causal mask", chunks) if engine == "bm25" else search.rg_phrase("causal mask", lib, chunks)
                self.assertEqual(res[0][1]["kind"], "turn", (engine, [(s, c["kind"], c["slug"]) for s, c in res]))
        finally:
            shutil.rmtree(lib, ignore_errors=True)


# ------------------------------------------------------------------------------- small W14b items

class SmallFixes(unittest.TestCase):
    def test_d01_preflight_reports_a_missing_esbuild_binary(self):
        ws = tmp("w16-pre-")
        try:
            pkg = ws / "remotion" / "node_modules" / "remotion"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text('{"version": "4"}')
            t = preflight.Table()
            preflight.check_workspace(t, ws)
            row = next(r for r in t.rows if r["check"] == "esbuild binary")
            self.assertEqual(row["status"], "FAIL")
            self.assertIn("npm rebuild esbuild", row["fix"])
            self.assertTrue(any(r["check"] == "jsonschema (optional)" and not r["required"] for r in t.rows))  # D05
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_d03_fact_span_validates(self):
        schema = json.loads((SKILL / "schemas" / "facts.schema.json").read_text())
        fact = {"id": "f1", "kind": "sourced", "claim": "c", "numbers": [], "sourceId": "s1", "quote": "q",
                "span": {"file": "research/sources/s1-vaswani.md", "line": 42}}
        rep = vs.Report("facts.json")
        errs = bm._mini_validate({"version": 1, "facts": [fact]}, schema)
        self.assertFalse([e for e in errs if "span" in e], errs)
        fact["span"] = {"line": 3}
        self.assertTrue(any("file" in e for e in bm._mini_validate({"version": 1, "facts": [fact]}, schema)))
        del rep

    def test_d02_d10_d17_d23_docs(self):
        depth = (SKILL / "references" / "depth.md").read_text()
        self.assertIn("explainers/<series-id>/research/", depth)
        self.assertIn("Leave room in part 1's world layout", depth)
        self.assertIn("--embed-chapters` at step 12", (SKILL / "references" / "library.md").read_text())
        self.assertIn("explain-back hold up to 15 s", (SKILL / "references" / "qc.md").read_text())


if __name__ == "__main__":
    unittest.main()
