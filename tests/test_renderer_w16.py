"""W16 renderer tests: the matrix scene (matrixLayout.ts and MatrixScene.tsx), wide table cells
(tableLayout.ts cellW), the pill height (worldState.ts nodeSize) and their Python ports, a type
check, and stills of the matrix sample and of a pill with a sublabel and a value. Run from the
skill folder:

    PE_REMOTION_DIR=explainers/remotion python3 -m unittest tests.test_renderer_w16 -v

Without PE_REMOTION_DIR (a Remotion project with node_modules) the tests are skipped. Set
PE_STILLS_DIR to keep the stills.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
TEMPLATE = SKILL / "templates" / "remotion"
REMOTION = os.environ.get("PE_REMOTION_DIR")
sys.path.insert(0, str(SKILL / "scripts"))
import build_manifest as bm  # noqa: E402
import pe_common as pc  # noqa: E402

ENTRY = """
export { matrixLayout, matrixLayoutFor, matrixProblems, matrixStateAt, matrixTextsAt } from "./src/scenes/matrixLayout";
export { tableLayout } from "./src/scenes/tableLayout";
export { nodeSize } from "./src/scenes/world/worldState";
"""

HARNESS = (
    "import { readFileSync } from 'node:fs';\n"
    "import { pathToFileURL } from 'node:url';\n"
    "const [, , mod, file] = process.argv;\n"
    "const M = await import(pathToFileURL(mod).href);\n"
    "const D = JSON.parse(readFileSync(file, 'utf8'));\n"
    "const f = new Function('M', 'D', D.code);\n"
    "console.log(JSON.stringify(f(M, D)));\n"
)

PILL_SCENES = {
    "version": 1,
    "world": {"layout": "free", "nodes": [
        {"id": "query", "label": "query", "sublabel": "made from it", "x": 380, "y": 300, "shape": "pill", "w": 300},
        {"id": "scale", "label": "÷ 8", "sublabel": "scales scores", "x": 860, "y": 300, "shape": "pill", "w": 260},
        {"id": "softmax", "label": "softmax", "sublabel": "scores to weights", "x": 1360, "y": 300, "shape": "pill", "w": 320}],
        "edges": [{"id": "e1", "from": "query", "to": "scale"}, {"id": "e2", "from": "scale", "to": "softmax"}]},
    "scenes": [{"id": "s01", "type": "world", "anchor": {"from": {"turn": "t01"}},
                "props": {"steps": [{"at": {"turn": "t02", "word": "scores"}, "set": {"scale": {"value": "root 64 = 8"}}, "focus": ["scale"]}]}}],
}

MATRICES = [
    {"rows": ["brick", "fell", "it", "cracked"], "columns": ["brick", "fell", "it", "cracked"], "title": "W", "rowAxis": "q", "colAxis": "k"},
    {"rows": [f"w{i}" for i in range(10)], "columns": [f"w{i}" for i in range(10)], "cells": [["-inf"] * 10] * 10},
    {"rows": ["a"] * 8, "columns": [f"column w {i:02d}" for i in range(12)], "cells": [["twelve chars"] * 12] * 8},
    {"rows": ["x", "y"], "columns": ["p", "q", "r"], "heat": [[0.1, 2, 0.3], [0, 0, 0]], "cells": [["1", "2"], ["3", "4", "5"]],
     "steps": [{"atMs": 0, "highlight": [{"row": "z"}, {"col": 9}, {}]}]},
]


def build(ws: Path, slug: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    argv = sys.argv
    sys.argv = ["build_manifest.py", "--workspace", str(ws), "--slug", slug, "--placeholder-timing"]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = bm.main()
            except SystemExit as e:
                rc = e.code
    finally:
        sys.argv = argv
    return rc, out.getvalue() + err.getvalue()


@unittest.skipUnless(REMOTION and (Path(REMOTION) / "node_modules" / "remotion").is_dir(),
                     "set PE_REMOTION_DIR to a Remotion project with node_modules to run the renderer tests")
class W16Renderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="w16-remotion-"))
        cls.ws = cls.tmp
        cls.proj = cls.tmp / "remotion"
        shutil.copytree(TEMPLATE, cls.proj, ignore=shutil.ignore_patterns("node_modules", "out"))
        (cls.proj / "node_modules").symlink_to(Path(REMOTION).resolve() / "node_modules")
        (cls.proj / "w16-entry.ts").write_text(ENTRY)
        r = subprocess.run(["npx", "esbuild", "w16-entry.ts", "--bundle", "--format=esm", "--platform=node",
                            f"--outfile={cls.tmp / 'm.mjs'}", "--log-level=warning"], cwd=cls.proj, capture_output=True, text=True, timeout=120)
        cls.bundle_error = None if r.returncode == 0 else r.stderr
        cls.stills = Path(os.environ["PE_STILLS_DIR"]) if os.environ.get("PE_STILLS_DIR") else cls.tmp / "stills"
        cls.stills.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def js(self, code: str, **data):
        if self.bundle_error:
            self.fail(f"esbuild could not bundle the pure modules: {self.bundle_error[-800:]}")
        f = self.tmp / "in.json"
        f.write_text(json.dumps({"code": code, **data}))
        h = self.tmp / "h.mjs"
        h.write_text(HARNESS)
        r = subprocess.run(["node", str(h), str(self.tmp / "m.mjs"), str(f)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return json.loads(r.stdout)

    def still(self, slug: str, frame: int) -> Path:
        out = self.stills / f"w16-{slug}-{frame}.png"
        r = subprocess.run(["npx", "remotion", "still", "Episode", str(out), f"--props={json.dumps({'slug': slug})}", f"--frame={frame}"],
                           cwd=self.proj, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-1500:])
        self.assertTrue(out.is_file() and out.stat().st_size > 10_000)
        return out

    def test_typecheck(self):
        r = subprocess.run(["npx", "tsc", "--noEmit"], cwd=self.proj, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_matrix_layout_problems_and_texts_match_python(self):
        ts = self.js("return D.ms.map((p) => ({L: M.matrixLayout(p), P: M.matrixProblems(p),"
                     " S: [0, 30, 300].map((f) => { const s = M.matrixStateAt(p, 0, 30, f); return {cells: [...s.cells].sort(), rows: [...s.rows].sort(), cols: [...s.cols].sort(), note: s.note}; }),"
                     " T: M.matrixTextsAt(p, 0, 30, 100)}));", ms=MATRICES)
        for p, t in zip(MATRICES, ts):
            self.assertEqual(t["L"], pc.matrix_layout(p), p)
            self.assertEqual(t["P"], pc.matrix_problems(p), p)
            for f, s in zip((0, 30, 300), t["S"]):
                py = pc.matrix_state_at(p, 0, 30, f)
                self.assertEqual(s, {"cells": sorted(py["cells"]), "rows": sorted(py["rows"]), "cols": sorted(py["cols"]), "note": py["note"]})
            self.assertEqual(t["T"], pc.matrix_texts_at(p, 0, 30, 100))

    def test_table_cell_width_and_node_size_match_python(self):
        cases = [(2, 1, 828, 464, True, 12, 8), (12, 2, 828, 464, True, 2, 6), (4, 4, 828, 384, True, 6, 13), (14, 6, 828, 384, True, 4, 0)]
        ts = self.js("return D.cases.map((c) => M.tableLayout(...c));", cases=cases)
        for c, t in zip(cases, ts):
            self.assertEqual(t, pc.table_layout(*c), c)
        nodes = [{"shape": "pill"}, {"shape": "pill", "value": ""}, {"shape": "pill", "sublabel": "s", "value": "v"},
                 {"value": "v"}, {"shape": "circle", "value": "v"}, {"shape": "pill", "h": 90, "value": "v"}]
        ts = self.js("return D.nodes.map((n) => { const s = M.nodeSize({id: 'n', label: 'x', x: 0, y: 0, ...n}); return [s.w, s.h]; });", nodes=nodes)
        for n, t in zip(nodes, ts):
            self.assertEqual(tuple(t), pc.node_size(n), n)

    def test_matrix_and_pill_stills(self):
        for slug, src in (("sample-matrix", TEMPLATE / "sample-inputs" / "matrix"), ("w16-pill", None)):
            d = self.ws / slug
            d.mkdir(exist_ok=True)
            shutil.copy(TEMPLATE / "sample-inputs" / "matrix" / "script.json", d / "script.json")
            (d / "scenes.json").write_text((src / "scenes.json").read_text() if src else json.dumps(PILL_SCENES))
            rc, out = build(self.ws, slug)
            self.assertEqual(rc, 0, out)
        self.still("sample-matrix", 300)  # it -> brick highlighted, note shown
        self.still("w16-pill", 250)       # the scale pill with sublabel and value, 160 tall


if __name__ == "__main__":
    unittest.main()
