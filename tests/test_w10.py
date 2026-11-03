"""W10 tests: text.minsize reads built-in compare tables and diagram text (never skips), text.phone
severity by brief.json `viewing`, the 720p sheet named in the judge brief, validator W38 (J8 expert
runs), labels.counts (J11 counts on compare tables), and the tableLayout.ts band layout against its
Python port in qc.py. Run from the skill folder:

    PE_REMOTION_DIR=<remotion project with node_modules> python3 -m unittest tests.test_w10 -v

Without PE_REMOTION_DIR the TypeScript parity test is skipped.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
SCRIPTS = SKILL / "scripts"
SRC = SKILL / "templates" / "remotion" / "src"
sys.path.insert(0, str(SCRIPTS))
import qc  # noqa: E402
import validate_script as vs  # noqa: E402

REMOTION = os.environ.get("PE_REMOTION_DIR")
ESBUILD = Path(REMOTION).resolve() / "node_modules" / ".bin" / "esbuild" if REMOTION else None
HAVE_BUNDLER = bool(shutil.which("node") and ESBUILD and ESBUILD.is_file())

COLS = [str(i) for i in range(12)]
MOD3 = ["A", "B", "C"] * 4
MOD4 = ["A", "B", "C", "D"] * 3


def table_scene(stats: list[tuple[int, str]], banners: list[dict] | None = None, labels=("k mod 3", "k mod 4"),
                cells=(MOD3, MOD4), title: str | None = None) -> dict:
    left = {"title": "hash mod N", "tag": "naive", "kind": "table", "columns": COLS,
            "valueColors": {"A": "#5BD69A", "B": "#C792EA", "C": "#FF7A7A", "D": "#F2D16B"},
            "rows": [{"id": "r1", "label": labels[0], "cells": list(cells[0])}, {"id": "r2", "label": labels[1], "cells": list(cells[1])}],
            "steps": [{"atMs": ms, "stat": text} for ms, text in stats]}
    right = {"title": "hash ring", "tag": "ring", "kind": "text", "lines": [{"text": "ring"}]}
    props = {"left": left, "right": right}
    if title:
        props["title"] = title
    if banners:
        props["verdict"], props["banners"] = banners[0], banners[1:]
    return {"id": "sc04", "type": "compare", "props": props, "startMs": 0, "endMs": 60000}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w10-"))
        self.ws = self.tmp / "ws"
        self.ep = self.ws / "demo"
        self.ep.mkdir(parents=True)
        self.rem = self.ws / "remotion"
        (self.rem / "src").mkdir(parents=True)
        shutil.copy(SRC / "theme.ts", self.rem / "src" / "theme.ts")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def episode(self, scenes, brief=None, turns=None, overlays=None):
        (self.ep / "episode.json").write_text(json.dumps({"video": {"fps": 30}, "scenes": scenes, "turns": turns or [],
                                                          "overlays": overlays or []}))
        if brief is not None:
            (self.ep / "brief.json").write_text(json.dumps(brief))
        return qc.Episode(mock.Mock(workspace=str(self.ws), slug="demo", mp4=None, remotion_dir=None))

    def checks(self, ep) -> dict:
        return {c["id"]: c for c in qc.text_size(ep)}


# ------------------------------------------------------------------------------------- text.minsize

class BuiltinText(Workspace):
    def test_legacy_compare_table_is_read(self):
        # A project whose CompareScene.tsx predates tableLayout.ts renders 12 cells per row at 30 px.
        (self.rem / "src" / "scenes").mkdir()
        (self.rem / "src" / "scenes" / "CompareScene.tsx").write_text("// old\n")
        c = self.checks(self.episode([table_scene([])]))
        self.assertEqual(c["text.minsize"]["status"], "pass", c)
        self.assertIn("legacy one-row layout", c["text.minsize"]["detail"])
        self.assertEqual(c["text.phone"]["status"], "warn", c)
        self.assertIn("12 cells per row", c["text.phone"]["detail"])
        self.assertIn("30 px", c["text.phone"]["detail"])

    def test_banded_compare_table_is_readable(self):
        c = self.checks(self.episode([table_scene([])]))  # no CompareScene in the project: the template's bands
        self.assertIn("2 band(s) of up to 6", c["text.minsize"]["detail"])
        self.assertIn("text 36 px", c["text.minsize"]["detail"])
        # W11a (R01): the table itself has no phone finding; built-in text (pills, rail) is judged separately.
        self.assertNotIn("sc04 left table", c["text.phone"]["detail"], c)

    def test_low_contrast_cell_fill_fails(self):
        sc = table_scene([])
        sc["props"]["left"]["valueColors"]["A"] = "#3A4356"
        c = self.checks(self.episode([sc]))
        self.assertEqual(c["text.minsize"]["status"], "fail", c)
        self.assertIn("contrast", c["text.minsize"]["detail"])

    def diagram(self, fill="#F2F4F8", font=34, highlight_last=("m2",), title="Analogy"):
        els = [{"id": "m1", "kind": "text", "x": 10, "y": 10, "text": "depot to server", "fontSize": font, "fill": fill},
               {"id": "m2", "kind": "text", "x": 10, "y": 90, "text": "house to key", "fontSize": 40}]
        return {"id": "sc06", "type": "diagram", "startMs": 0, "endMs": 20000,
                "props": {"title": title, "elements": els,
                          "steps": [{"atMs": 1000, "reveal": ["m1"]}, {"atMs": 5000, "highlight": list(highlight_last)}]}}

    def test_diagram_text_size_after_stage_scale(self):
        c = self.checks(self.episode([self.diagram()]))
        self.assertEqual(c["text.minsize"]["status"], "pass", c)
        self.assertIn("sc06 diagram: 2 inline text element(s), 34 to 40 px", c["text.minsize"]["detail"])
        self.assertEqual(c["text.phone"]["status"], "warn")  # 34 px is under the 36 px phone threshold
        self.assertIn("m1", c["text.phone"]["detail"])

    def test_diagram_low_contrast_fill_fails(self):
        c = self.checks(self.episode([self.diagram(fill="#3A4356")]))
        self.assertEqual(c["text.minsize"]["status"], "fail", c)
        self.assertIn("m1", c["text.minsize"]["detail"])

    def test_dimmed_at_scene_end_warns(self):
        # #FF7A7A is 7.5:1 alone; at DiagramScene's dimmed opacity it drops under 4.5:1.
        c = self.checks(self.episode([self.diagram(fill="#FF7A7A")]))
        self.assertEqual(c["text.minsize"]["status"], "warn", c)
        self.assertIn("dimmed", c["text.minsize"]["detail"])
        c = self.checks(self.episode([self.diagram(fill="#FF7A7A", highlight_last=("m1", "m2"))]))
        self.assertEqual(c["text.minsize"]["status"], "pass", c)

    def test_dim_factor_matches_diagram_scene(self):
        text = (SRC / "scenes" / "DiagramScene.tsx").read_text()
        m = re.search(r"DIAGRAM_DIM = ([\d.]+)", text) or re.search(r"1 - ([\d.]+) \* hiP", text)
        self.assertIsNotNone(m, "DiagramScene.tsx: dim factor not found")
        self.assertEqual(float(m.group(1)), qc.DIAGRAM_DIM)

    def test_never_skips(self):
        c = self.checks(self.episode([{"id": "w", "type": "world", "props": {}}]))
        self.assertEqual(c["text.minsize"]["status"], "pass")
        self.assertIn("world", c["text.minsize"]["detail"])
        self.assertNotEqual(c["text.phone"]["status"], "skip")


class Viewing(Workspace):
    def test_phone_fails_desktop_warns(self):
        (self.rem / "src" / "scenes").mkdir()
        (self.rem / "src" / "scenes" / "CompareScene.tsx").write_text("// old\n")
        self.assertEqual(self.checks(self.episode([table_scene([])], brief={"viewing": "phone"}))["text.phone"]["status"], "fail")
        self.assertEqual(self.checks(self.episode([table_scene([])], brief={"viewing": "desktop"}))["text.phone"]["status"], "warn")
        self.assertEqual(self.checks(self.episode([table_scene([])], brief={}))["text.phone"]["status"], "warn")

    def test_base_rule_fails_in_both_modes(self):
        sc = {"id": "d", "type": "diagram", "startMs": 0, "endMs": 1000,
              "props": {"elements": [{"id": "t", "kind": "text", "text": "x", "fill": "#30343C"}]}}
        for v in ("phone", "desktop"):
            self.assertEqual(self.checks(self.episode([sc], brief={"viewing": v}))["text.minsize"]["status"], "fail", v)

    def test_judge_brief_names_the_reference_sheet(self):
        ep = self.episode([table_scene([])], brief={"viewing": "desktop"})
        text = qc.write_judge_brief(ep).read_text()
        self.assertIn("contact-sheet-720", text)
        self.assertIn("viewing is **desktop**", text)
        ep = self.episode([table_scene([])], brief={"viewing": "phone"})
        text = qc.write_judge_brief(ep).read_text()
        self.assertIn("is a blocker", text)

    def test_schema_enum(self):
        schema = json.loads((SKILL / "schemas" / "brief.schema.json").read_text())
        self.assertEqual(schema["properties"]["viewing"]["enum"], ["desktop", "phone"])
        self.assertEqual(schema["properties"]["viewing"]["default"], "desktop")


# ------------------------------------------------------------------------------------- W38

def script(turns: list[tuple[str, str, str, int]]) -> dict:
    """turns: (segment, speaker, text, holdAfterMs)."""
    segs: dict[str, list] = {}
    for i, (seg, sp, text, hold) in enumerate(turns, 1):
        t = {"id": f"t{i:02d}", "speaker": sp, "text": text}
        if hold:
            t.update(holdAfterMs=hold, pause={"kind": "predict", "prompt": "Which keys move?"})
        segs.setdefault(seg, []).append(t)
    return {"version": 1, "id": "x", "title": "x", "targetMinutes": 1,
            "speakers": [{"id": "host", "name": "Nia", "voice": "Sulafat", "color": "#4F8CFF", "side": "left", "role": "learner"},
                         {"id": "guest", "name": "Theo", "voice": "Iapetus", "color": "#FFB020", "side": "right", "role": "expert"}],
            "segments": [{"id": s, "role": "example", "learningGoal": "g", "visualPlan": "v", "turns": ts} for s, ts in segs.items()]}


def w38(data: dict) -> list[dict]:
    rep = vs.Report("x")
    vs.check_script(data, None, 1, 45, "per-turn", rep, None, None)
    return [i for i in rep.items if i["code"] == "W38"]


class ExpertRun(unittest.TestCase):
    LONG = " ".join(["word"] * 35)

    def test_two_long_expert_turns_across_segments_warn(self):
        items = w38(script([("seg01", "host", "Why?", 0), ("seg01", "guest", self.LONG, 0), ("seg02", "guest", self.LONG, 0)]))
        self.assertEqual(len(items), 1, items)
        self.assertIn("t02, t03", items[0]["message"])
        self.assertIn("learner turn", items[0]["message"])

    def test_hold_counts_as_words(self):
        short = " ".join(["word"] * 20)
        self.assertEqual(w38(script([("s1", "guest", short, 0), ("s1", "guest", short, 0)])), [])  # 40 words
        items = w38(script([("s1", "guest", short + "?", 8000), ("s1", "guest", short, 0)]))  # 40 + 22
        self.assertEqual(len(items), 1)
        self.assertIn("22 for holds", items[0]["message"])

    def test_learner_turn_between_breaks_the_run(self):
        self.assertEqual(w38(script([("s1", "guest", self.LONG, 0), ("s1", "host", "So it moves?", 0), ("s1", "guest", self.LONG, 0)])), [])

    def test_code_in_the_table(self):
        self.assertIn("| W38 |", (SKILL / "references" / "script.md").read_text())


# ------------------------------------------------------------------------------------- labels.counts

class LabelCounts(Workspace):
    def run_labels(self, scenes, overlays=None) -> dict:
        ep = self.episode(scenes, overlays=overlays)
        c = qc.labels_counts(ep)[0]
        c["checked"] = ep.labels_checked
        return c

    def test_true_counts_pass(self):
        c = self.run_labels([table_scene([(1000, "moved: 9 of 12"), (2000, "9 of 12 keys miss at once"), (3000, "only 3 of 12 stay"),
                                          (4000, "In general: 5 to 6 moves about 5 in 6")],
                                         banners=[{"text": "Ring: 3 of 12 move. Mod N: 9 of 12 move.", "winner": "right", "atMs": 1500,
                                                   "labels": {"left": "moves 9 of 12", "right": "moves 3 of 12"}}])])
        self.assertEqual(c["status"], "pass", c)
        self.assertGreaterEqual(len(c["checked"]), 4)

    def test_wrong_count_fails_with_time_and_value(self):
        c = self.run_labels([table_scene([(61000 - 60000, "moved: 8 of 12")])])
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("00:01 sc04 left", c["detail"])
        self.assertIn("9 of 12 columns differing", c["detail"])

    def test_partial_fill_is_only_a_warning(self):
        sc = table_scene([(5000, "moved: 9 of 12")])
        sc["props"]["left"]["steps"].insert(0, {"atMs": 1000, "fill": {"r1": "all", "r2": [0, 1, 2, 3]}})
        c = self.run_labels([sc])
        self.assertEqual(c["status"], "warn", c)
        self.assertIn("only 4 of 12 filled", c["detail"])

    def test_server_counts_and_moduli(self):
        c = self.run_labels([table_scene([(1000, "5 to 6: about 5 keys in 6 move"), (2000, "100 → 101 servers: nearly all move")])])
        self.assertEqual(c["status"], "warn", c)
        self.assertIn("names 5 to 6", c["detail"])
        self.assertIn("names 100 to 101", c["detail"])
        c = self.run_labels([table_scene([(1000, "3 to 4 servers: 9 of 12 move")])])
        self.assertEqual(c["status"], "pass", c)

    def test_fixed_fleet_over_a_change(self):
        c = self.run_labels([table_scene([], banners=[{"text": "Fixed fleet: mod is simpler. Changing fleet: ring", "atMs": 1000,
                                                       "labels": {"left": "fixed fleet", "right": "changing fleet"}}],
                                         labels=("mod 4", "mod 5"))])
        self.assertEqual(c["status"], "warn", c)
        self.assertIn("'fixed fleet' -> says the fleet is fixed", c["detail"])
        self.assertNotIn("Changing fleet: ring' ->", c["detail"])

    def test_ring_clause_in_a_banner_is_not_the_table(self):
        c = self.run_labels([table_scene([], banners=[{"text": "Ring: 3 of 12 move.", "atMs": 1000}])])
        self.assertEqual(c["status"], "pass", c)

    def test_no_table_passes(self):
        c = self.run_labels([{"id": "w", "type": "world", "props": {}, "startMs": 0, "endMs": 1000}])
        self.assertEqual(c["status"], "pass")
        self.assertIn("no compare table", c["detail"])

    def test_coverage_runs_it(self):
        self.assertIn("out += labels_counts(ep)", (SCRIPTS / "qc.py").read_text())


# ------------------------------------------------------------------------------------- band layout

class BandLayoutPython(unittest.TestCase):
    def test_twelve_columns_wrap_into_two_bands_of_six(self):
        w, h = qc.compare_body(False)
        L = qc.table_layout(12, 2, w, h, True)
        self.assertEqual([len(b) for b in L["bands"]], [6, 6])
        self.assertGreaterEqual(L["font"], 36)
        self.assertLessEqual(L["perBand"], qc.MAX_BAND_COLS)
        self.assertGreaterEqual(L["cell"], L["font"] + 8)
        self.assertEqual(qc.table_layout(8, 2, w, h, True)["bands"], [list(range(8))])

    def test_constants_match_typescript(self):
        text = (SRC / "scenes" / "tableLayout.ts").read_text()
        for name, val in (("GRID_TEXT_PX", qc.GRID_TEXT_PX), ("CHAR_W", qc.CHAR_W), ("CELL_TEXT_PAD", qc.CELL_TEXT_PAD), ("TABLE_LABEL_W", qc.TABLE_LABEL_W),
                          ("TABLE_CELL_GAP", qc.TABLE_CELL_GAP), ("TABLE_ROW_PAD", qc.TABLE_ROW_PAD), ("TABLE_BAND_GAP", qc.TABLE_BAND_GAP),
                          ("TABLE_PAD_X", qc.TABLE_PAD_X), ("TABLE_PAD_TOP", qc.TABLE_PAD_TOP), ("TABLE_MAX_CELL", qc.TABLE_MAX_CELL)):
            self.assertIn(f"export const {name} = {val};", text)
        self.assertIn("grid: GRID_TEXT_PX", (SRC / "theme.ts").read_text())
        self.assertIn("panelTableLayout(panel, hasTitle)", (SRC / "scenes" / "CompareScene.tsx").read_text())


@unittest.skipUnless(HAVE_BUNDLER, "set PE_REMOTION_DIR to a Remotion project with node_modules (esbuild)")
class BandLayoutParity(unittest.TestCase):
    CASES = [(12, 2, True, False), (12, 2, True, True), (9, 3, True, False), (8, 2, True, False), (17, 2, False, False),
             (4, 1, True, True), (24, 2, True, False), (1, 0, False, False)]

    def test_typescript_and_python_agree(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "tl.mjs"
            r = subprocess.run([str(ESBUILD), str(SRC / "scenes" / "tableLayout.ts"), "--bundle", "--format=esm", "--platform=node",
                                f"--outfile={out}", "--log-level=warning"], capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            cases = [[n, rows, *qc.compare_body(titled), header] for n, rows, header, titled in self.CASES]
            h = Path(d) / "h.mjs"
            h.write_text("import { pathToFileURL } from 'node:url';\nconst [, , mod, data] = process.argv;\n"
                         "const { tableLayout } = await import(pathToFileURL(mod).href);\n"
                         "console.log(JSON.stringify(JSON.parse(data).map((c) => tableLayout(...c))));\n")
            r = subprocess.run(["node", str(h), str(out), json.dumps(cases)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
        ts = json.loads(r.stdout)
        for case, got in zip(cases, ts):
            self.assertEqual(got, qc.table_layout(*case), case)


if __name__ == "__main__":
    unittest.main()
