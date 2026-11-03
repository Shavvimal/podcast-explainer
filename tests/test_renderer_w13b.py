"""W13b renderer tests (judge v6, codex round 4 Q03, Q05, stumble 5): marks (spotlight, arcs, the
change band, tints, walk arrows) expire at the next step unless the step persists them; a walk
arrow also ends at its turn's end; speaksOf and the focus warning; virtual nodes (two points per
server); row labels that size their column or are refused with the numbers; count-claim text;
permanent node labels in labelSourcesAt; a five-line equation still. Run from the skill folder:

    PE_REMOTION_DIR=explainers/remotion python3 -m unittest tests.test_renderer_w13b -v

Without PE_REMOTION_DIR (a Remotion project with node_modules) the tests are skipped. Set
PE_STILLS_DIR to keep the stills.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
TEMPLATE = SKILL / "templates" / "remotion"
REMOTION = os.environ.get("PE_REMOTION_DIR")

ENTRY = """
export * from "./src/visibleText";
export { tableLayout, tableProblems, panelTableLayout, tableLabelW, TABLE_LABEL_MAX } from "./src/scenes/tableLayout";
export { claimText, claimTextProblems, compareClaimProblems } from "./src/scenes/compareState";
export {
  buildTimeline, placeNodes, resolveSteps, worldMarksAt, focusProblems, namesInWords, pointOf, labelWithPoint,
} from "./src/scenes/world/worldState";
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

OWNERS = [("A", 2, "#5BD69A"), ("B", 6, "#C792EA"), ("C", 10, "#FF7A7A"), ("D", 9, "#F2D16B")]


def ring_world(virtual=False):
    nodes = [{"id": f"k{i}", "label": str(i), "pos": i, "role": "item", "x": 0, "y": 0} for i in range(12)]
    for oid, pos, col in OWNERS:
        nodes.append({"id": oid, "label": oid, "pos": pos, "role": "owner", "ringOffset": 92, "color": col, "x": 0, "y": 0})
    if virtual:  # two points per server: A at 1 and 9, B at 3 and 7, C at 5 and 11 (the v6 world)
        for oid, pos in (("A1", 1), ("A2", 9), ("B1", 3), ("B2", 7), ("C1", 5), ("C2", 11)):
            nodes.append({"id": oid, "label": oid[0], "pos": pos, "role": "owner", "ringOffset": 92, "virtualOf": oid[0], "x": 0, "y": 0})
    nodes.append({"id": "count", "label": "keys per server", "x": 330, "y": 560, "w": 460})
    for n in nodes:  # hidden until a step reveals it (build_manifest.py writes revealAtMs the same way)
        n["revealAtMs"] = 10 ** 9
    return {"layout": "ring", "ring": {"positions": 12, "cx": 1100, "cy": 356, "r": 165}, "camera": {"zoom": 1.1},
            "nodes": nodes, "edges": []}


@unittest.skipUnless(REMOTION and (Path(REMOTION) / "node_modules" / "remotion").is_dir(),
                     "set PE_REMOTION_DIR to a Remotion project with node_modules to run the renderer tests")
class W13bRenderer(unittest.TestCase):
    proj: Path
    tmp: Path

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="w13b-remotion-"))
        cls.proj = cls.tmp / "remotion"
        shutil.copytree(TEMPLATE, cls.proj, ignore=shutil.ignore_patterns("node_modules", "out"))
        (cls.proj / "node_modules").symlink_to(Path(REMOTION).resolve() / "node_modules")
        (cls.proj / "w13b-entry.ts").write_text(ENTRY)
        cls.base = json.loads((cls.proj / "public" / "episodes" / "sample-ring" / "episode.json").read_text())
        r = subprocess.run(["npx", "esbuild", "w13b-entry.ts", "--bundle", "--format=esm", "--platform=node",
                            f"--outfile={cls.tmp / 'm.mjs'}", "--log-level=warning"],
                           cwd=cls.proj, capture_output=True, text=True, timeout=120)
        cls.bundle_error = None if r.returncode == 0 else r.stderr
        cls.stills = Path(os.environ["PE_STILLS_DIR"]) if os.environ.get("PE_STILLS_DIR") else cls.tmp / "stills"
        cls.stills.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers

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

    def episode(self, slug: str, scenes: list[dict], world=None, overlays=None, turns=None) -> dict:
        ep = copy.deepcopy(self.base)
        ep["scenes"] = scenes
        ep["overlays"] = overlays or []
        ep["world"] = world
        if turns is not None:
            ep["turns"] = turns
        d = self.proj / "public" / "episodes" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "episode.json").write_text(json.dumps(ep))
        return ep

    def whole(self, sid: str, typ: str, props: dict) -> dict:
        return {"id": sid, "type": typ, "startMs": 0, "endMs": self.base["audio"]["durationMs"], "props": props}

    def still(self, slug: str, frame: int) -> subprocess.CompletedProcess:
        out = self.stills / f"{slug}-{frame}.png"
        r = subprocess.run(["npx", "remotion", "still", "Episode", str(out), f"--props={json.dumps({'slug': slug})}",
                            f"--frame={frame}"], cwd=self.proj, capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            self.assertTrue(out.is_file() and out.stat().st_size > 10_000, r.stdout[-500:])
        return r

    def marks(self, ep: dict, *times: int) -> list[dict]:
        return self.js("return D.ts.map((t) => M.marksAt(D.ep, t));", ep=ep, ts=list(times))

    @staticmethod
    def turns(*spans):
        return [{"id": tid, "speaker": "host", "segment": "seg01", "text": text, "startMs": a, "endMs": b,
                 "words": [{"text": w, "startMs": a + i * 300, "endMs": a + i * 300 + 250, "source": "asr"}
                           for i, w in enumerate(text.split())]}
                for tid, a, b, text in spans]

    # ------------------------------------------------------------------------------- tests

    def test_typecheck(self):
        r = subprocess.run(["npx", "tsc", "--noEmit"], cwd=self.proj, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_arcs_spotlight_tint_expire_at_next_step(self):
        # judge v6 seg06 t105: arcs and a spotlight from an earlier step stayed while the list was counted.
        world = ring_world()
        steps = [{"atMs": 300, "reveal": ["k%d" % i for i in range(12)] + ["A", "B", "C"]},
                 {"atMs": 2000, "arcs": [{"from": 7, "to": 9}], "focus": ["C"], "tint": {"warn": ["k7"]}},
                 {"atMs": 5000, "note": "counting"},
                 {"atMs": 8000, "focus": ["A"]}]
        ep = self.episode("w13b-expire", [self.whole("w1", "world", {"steps": steps})], world=world)
        at_step, after, later = self.marks(ep, 3000, 6000, 9000)
        self.assertEqual(at_step["arcs"], [{"from": 7, "to": 9}])
        self.assertEqual(at_step["focus"], ["C"])
        self.assertEqual(at_step["tint"], {"k7": "warn"})
        self.assertEqual(after["arcs"], [])
        self.assertEqual(after["focus"], [])
        self.assertEqual(after["tint"], {})
        self.assertEqual(later["focus"], ["A"])
        r = self.still("w13b-expire", 180)  # 6.0 s: no arc band, no spotlight
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_persist_keeps_marks_until_set_again(self):
        world = ring_world()
        steps = [{"atMs": 300, "reveal": ["k%d" % i for i in range(12)] + ["A", "B", "C"]},
                 {"atMs": 2000, "arcs": [{"from": 7, "to": 9}], "focus": ["C"], "persist": ["arcs"]},
                 {"atMs": 5000, "note": "counting"},
                 {"atMs": 8000, "focus": ["A"]},
                 {"atMs": 11000, "arcs": []}]
        ep = self.episode("w13b-persist", [self.whole("w1", "world", {"steps": steps})], world=world)
        a, b, c = self.marks(ep, 6000, 9000, 12000)
        self.assertEqual(a["arcs"], [{"from": 7, "to": 9}])  # arcs persisted ...
        self.assertEqual(a["focus"], [])  # ... focus was not in the list
        self.assertEqual(b["arcs"], [{"from": 7, "to": 9}])
        self.assertEqual(c["arcs"], [])  # [] clears a persisted mark
        steps[1]["persist"] = True
        ep = self.episode("w13b-persist", [self.whole("w1", "world", {"steps": steps})], world=world)
        a, b = self.marks(ep, 6000, 9000)
        self.assertEqual(a["focus"], ["C"])
        self.assertEqual(b["focus"], ["A"])  # a later focus replaces it

    def test_change_band_expires_unless_persist_change(self):
        world = ring_world()
        steps = [{"atMs": 300, "reveal": ["k%d" % i for i in range(12)] + ["A", "B", "C"]},
                 {"atMs": 2000, "hide": ["B"]},
                 {"atMs": 5000, "note": "count them"},
                 {"atMs": 8000, "focus": ["A"]}]
        ep = self.episode("w13b-change", [self.whole("w1", "world", {"steps": steps})], world=world)
        a, b = self.marks(ep, 3000, 6000)
        self.assertIsNotNone(a["change"])
        self.assertEqual(a["change"]["moved"], ["k3", "k4", "k5", "k6"])
        self.assertIsNone(b["change"])
        steps[1]["persist"] = ["change"]
        ep = self.episode("w13b-change", [self.whole("w1", "world", {"steps": steps})], world=world)
        a, b = self.marks(ep, 6000, 9000)
        self.assertIsNotNone(a["change"])
        self.assertIsNotNone(b["change"])
        r = self.still("w13b-change", 180)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_walk_arrow_expires_at_turn_end_or_next_step(self):
        # judge v6 seg03 t20: key 11's walk arrow from t19 stayed into the next turn.
        world = ring_world()
        turns = self.turns(("t01", 250, 4000, "Key 11 wraps round to A, same as before."),
                           ("t02", 4250, 12000, "Right. So count it. Out of 12 keys, 3 changed owner."))
        steps = [{"atMs": 100, "reveal": ["k%d" % i for i in range(12)] + ["A", "B", "C"]},
                 {"at": {"turn": "t01", "word": "Key 11"}, "atMs": 300, "walk": ["k11"]},
                 {"at": {"turn": "t02", "word": "3 changed"}, "atMs": 9000, "note": "3 changed owner"}]
        ep = self.episode("w13b-walk", [self.whole("w1", "world", {"steps": steps})], world=world, turns=turns)
        during, after_turn, next_step = self.marks(ep, 2000, 5000, 9500)
        self.assertEqual(during["walks"], [{"item": "k11", "target": "A"}])
        self.assertEqual(after_turn["walks"], [])  # the turn ended at 4000 ms, before the next step
        self.assertEqual(next_step["walks"], [])
        r = self.still("w13b-walk", 150)  # 5.0 s: no arrow
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        steps[1]["persist"] = ["walk"]
        ep = self.episode("w13b-walk", [self.whole("w1", "world", {"steps": steps})], world=world, turns=turns)
        a, b = self.marks(ep, 5000, 9500)
        self.assertEqual(a["walks"], [{"item": "k11", "target": "A"}])
        self.assertEqual(b["walks"], [{"item": "k11", "target": "A"}])
        # without a turn (placeholder timing) the arrow lasts until the next step, as before
        steps[1]["persist"] = False
        steps[1].pop("at")
        ep = self.episode("w13b-walk", [self.whole("w1", "world", {"steps": steps})], world=world, turns=turns)
        a, b = self.marks(ep, 5000, 9500)
        self.assertEqual(a["walks"], [{"item": "k11", "target": "A"}])
        self.assertEqual(b["walks"], [])

    def test_speaks_of_warning(self):
        # judge v6 seg03 t23: "a key on A cannot move" while C and D were spotlit and A dimmed.
        world = ring_world()
        turns = self.turns(("t22", 250, 3000, "A new server can only cut into the stretch right behind it."),
                           ("t23", 3250, 7000, "Wait. So a key on A can't move at all?"))
        steps = [{"atMs": 100, "reveal": ["k%d" % i for i in range(12)] + ["A", "B", "C", "D"]},
                 {"at": {"turn": "t22", "word": "stretch"}, "atMs": 2000, "focus": ["C", "D"], "persist": ["focus"]}]
        ep = self.episode("w13b-speaks", [self.whole("w1", "world", {"steps": steps})], world=world, turns=turns)
        probs = self.js("return M.focusProblems(D.ep);", ep=ep)
        self.assertEqual(len(probs), 1, probs)  # "A new server" at the start of t22 is English, not a name
        self.assertIn('turn t23 names "A"', probs[0])
        self.assertIn("dims A", probs[0])
        fixed = copy.deepcopy(steps) + [{"at": {"turn": "t23", "word": "on A"}, "atMs": 4600, "focus": ["C", "D"], "speaksOf": ["A"]}]
        ep = self.episode("w13b-speaks", [self.whole("w1", "world", {"steps": fixed})], world=world, turns=turns)
        self.assertEqual(self.js("return M.focusProblems(D.ep);", ep=ep), [])
        self.assertEqual(self.marks(ep, 5000)[0]["speaksOf"], ["A"])
        r = self.still("w13b-speaks", 150)  # A is not dimmed while the step speaks of it
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        # a walk whose item or target the focus dims
        walk = copy.deepcopy(steps) + [{"atMs": 4000, "walk": ["k4"], "focus": ["D"]}]
        ep = self.episode("w13b-speaks", [self.whole("w1", "world", {"steps": walk})], world=world, turns=turns)
        probs = self.js("return M.focusProblems(D.ep);", ep=ep)
        self.assertTrue(any("the walk names k4, B" in p for p in probs), probs)
        words = self.js("return [M.namesInWords(['A','new','server'], 'A'), M.namesInWords(['A','and','B','lost'], 'A'),"
                        " M.namesInWords(['key','on','A','cannot'], 'A'), M.namesInWords(['the','Owner','rule.'], 'Owner rule')];")
        self.assertEqual(words, [[], [0], [2], [1]])

    def test_two_points_per_server_display(self):
        # judge v6 seg08 t110: "skipping extra points" was said over a one-point ring.
        world = ring_world(virtual=True)
        steps = [{"atMs": 100, "reveal": ["k%d" % i for i in range(12)] + ["A1", "A2", "B1", "B2", "C1", "C2", "count"]},
                 {"atMs": 1500, "walk": ["k2", {"item": "k2", "to": "C1", "overshoot": True}, {"item": "k2", "to": "A2", "overshoot": True}],
                  "tint": {"bad": ["B2"]}, "note": "copies of key 2: B, C, skip B again, A",
                  "set": {"count": {"label": "copies of key 2", "value": "B, C, A"}}}]
        ep = self.episode("w13b-virtual", [self.whole("w1", "world", {"steps": steps})], world=world)
        out = self.js("const n = M.placeNodes(D.ep.world); return { pts: n.filter((x) => x.virtualOf).map((x) => [x.id, M.pointOf(x, n), x.color]),"
                      " texts: M.visibleTextsAt(D.ep, 3000) };", ep=ep)
        self.assertEqual(out["pts"], [["A1", 1, "#5BD69A"], ["A2", 2, "#5BD69A"], ["B1", 1, "#C792EA"], ["B2", 2, "#C792EA"],
                                      ["C1", 1, "#FF7A7A"], ["C2", 2, "#FF7A7A"]])
        for t in ("A1", "A2", "B1", "B2", "C1", "C2", "copies of key 2: B, C, skip B again, A"):
            self.assertIn(t, out["texts"])
        r = self.still("w13b-virtual", 90)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def table_props(self, label, cols=12):
        columns = [str(i) for i in range(cols)]
        return {"left": {"title": "mod N", "kind": "table", "columns": columns,
                         "rows": [{"id": "r1", "label": label, "cells": ["A"] * cols},
                                  {"id": "r2", "label": "After", "cells": ["B"] * cols}]},
                "right": {"title": "notes", "kind": "text", "lines": [{"text": "x"}]}}

    def test_row_label_autosize_or_refusal(self):
        # codex round 4, stumble 5: "Before change" passed the early check and failed QC (257 vs 180 px).
        ok = self.table_props("Before change")
        lay = self.js("return { L: M.panelTableLayout(D.p.left, false), bad: M.tableProblems(D.p.left, false) };", p=ok)
        self.assertEqual(lay["bad"], [])
        L = lay["L"]
        self.assertEqual(L["labelW"], 291)  # ceil(13 * 0.62 * 36)
        self.assertGreaterEqual(L["labelFont"], 28)
        self.assertLessEqual(13 * 0.62 * L["labelFont"], L["labelW"])
        self.assertGreaterEqual(L["font"], 28)
        short = self.js("return M.panelTableLayout(D.p.left, false);", p=self.table_props("k mod 3"))
        self.assertEqual(short["labelW"], 180)  # short labels keep the old column
        bad = self.table_props("Before the change at 9")  # 22 characters: under 28 px even at 320 px
        probs = self.js("return M.tableProblems(D.p.left, false);", p=bad)
        self.assertTrue(any("needs" in p and "at most 320 px" in p and "18 characters or fewer" in p for p in probs), probs)
        self.episode("w13b-label-ok", [self.whole("c1", "compare", ok)])
        r = self.still("w13b-label-ok", 30)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.episode("w13b-label-bad", [self.whole("c1", "compare", bad)])
        r = self.still("w13b-label-bad", 30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("row label", r.stdout + r.stderr)

    def test_claim_text_and_placeholders(self):
        claim = {"kind": "count", "value": 3, "of": 4, "scope": "columns-changed"}
        out = self.js("return [M.claimTextProblems('0 of 4 move', D.c), M.claimTextProblems('3 of 4 move', D.c),"
                      " M.claimText('{value} of {of} move', D.c), M.claimTextProblems('{value} of {of} move', D.c),"
                      " M.claimTextProblems('{value} move'), M.claimTextProblems('none move', D.c)];", c=claim)
        self.assertEqual(len(out[0]), 1)
        self.assertEqual(out[1], [])
        self.assertEqual(out[2], "3 of 4 move")
        self.assertEqual(out[3], [])
        self.assertEqual(len(out[4]), 1)
        self.assertEqual(len(out[5]), 1)
        props = self.table_props("before", cols=4)
        props["left"]["rows"][1]["cells"] = ["A", "B", "B", "B"]
        props["left"]["steps"] = [{"atMs": 500, "stat": {"text": "{value} of {of} move", "claim": claim}}]
        ep = self.episode("w13b-claim", [self.whole("c1", "compare", props)])
        self.assertIn("3 of 4 move", self.js("return M.visibleTextsAt(D.ep, 1000);", ep=ep))
        props["left"]["steps"][0]["stat"]["text"] = "0 of 4 move"
        self.episode("w13b-claim-bad", [self.whole("c1", "compare", props)])
        r = self.still("w13b-claim-bad", 30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("but its claim says 3 of 4", r.stdout + r.stderr)

    def test_base_labels_are_label_sources(self):
        # codex round 4 Q03: a base label never expires, so QC must see it.
        world = {"nodes": [{"id": "n", "label": "4 keys per server", "sublabel": "3 servers", "x": 400, "y": 300, "revealAtMs": 10 ** 9},
                           {"id": "m", "label": "D", "value": "new", "x": 900, "y": 300, "revealAtMs": 10 ** 9}], "edges": []}
        steps = [{"atMs": 300, "reveal": ["n"]}, {"atMs": 2000, "reveal": ["m"]}, {"atMs": 6000, "focus": []}]
        ep = self.episode("w13b-labels", [self.whole("w1", "world", {"steps": steps})], world=world)
        a, b = self.js("return D.ts.map((t) => M.labelSourcesAt(D.ep, t).filter((s) => s.source.startsWith('node-')));", ep=ep, ts=[3000, 9000])
        lab = {(s["source"], s["text"]): s["expires"] for s in a}
        self.assertEqual(lab[("node-label", "4 keys per server")], False)
        self.assertEqual(lab[("node-sublabel", "3 servers")], False)
        self.assertEqual(lab[("node-value", "new")], True)
        texts = {s["text"] for s in b}
        self.assertIn("4 keys per server", texts)  # still drawn after a later reveal: QC can fail it
        self.assertNotIn("new", texts)  # the value expired at the next step

    def test_five_line_equation_still(self):
        # W12 fixed five KaTeX lines overflowing the stage; this still is the regression check.
        lines = [{"tex": r"h(k) = k \bmod N", "note": "mod N"},
                 {"tex": r"h(k) = \text{hash}(k) \bmod 2^{32}", "note": "ring position"},
                 {"tex": r"\text{owner}(k) = \min\{\, s : s \ge h(k) \,\}", "note": "successor"},
                 {"tex": r"\text{moved} \approx \frac{K}{N}", "note": "one join"},
                 {"tex": r"\sigma \approx 5\text{ to }10\%", "note": "100 to 200 points"}]
        for i, l in enumerate(lines):
            l["atMs"] = 300 + i * 400
        self.episode("w13b-eq", [self.whole("e1", "equation", {"title": "Five lines", "lines": lines})])
        r = self.still("w13b-eq", 120)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_stills_every_scene_type(self):
        for slug, frames in (("sample", "60,240,300,420,540,580,640,700,800"), ("sample-ring", "300,560,1000")):
            out = self.stills / f"w13b-{slug}"
            r = subprocess.run(["npx", "remotion", "render", "Episode", str(out), f"--props={json.dumps({'slug': slug})}",
                                f"--frames={frames}", "--image-format=png", "--log=error"],
                               cwd=self.proj, capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])
            self.assertEqual(len(list(out.glob("element-*.png"))), len(frames.split(",")))


if __name__ == "__main__":
    unittest.main()
