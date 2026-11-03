"""W11b renderer tests: stale labels expire at the next step unless `persist` (judge v3 to v5),
a ring that is a true circle, walk arrows that end at their successor, table geometry and row
lengths that fail loudly (R01, R03), entrance frames that finish before speech (A09), structured
count claims and label sources (R02). Run from the skill folder:

    PE_REMOTION_DIR=explainers/remotion python3 -m unittest tests.test_renderer_w11b -v

PE_REMOTION_DIR must be a Remotion project with node_modules (npm install done). Without it the
tests are skipped. They copy templates/remotion into a temporary project that links that
node_modules, bundle the pure modules with esbuild, run them in node, and render stills with
`npx remotion still` / `npx remotion render --frames`. Set PE_STILLS_DIR to keep the stills.
"""
from __future__ import annotations

import copy
import json
import math
import os
import random
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
export * from "./src/overlayState";
export { entranceFrames, msToFrame } from "./src/frames";
export { tableLayout, tableProblems, panelTableLayout, compareBodySize } from "./src/scenes/tableLayout";
export { bannerAt, panelStateAt, countClaim } from "./src/scenes/compareState";
export {
  buildTimeline, placeNodes, ringGeometry, ringProblems, ringTracks, ringFaceRadius, walkPlan, walkPoints,
  walkProblems, nodeSize, fitCamera, viewScale, ringInsetFilter,
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

FPS = 30


def ring_world(owner_offsets=None, with_d=True, positions=12):
    nodes = [{"id": f"k{i}", "label": str(i), "pos": i, "role": "item"} for i in range(positions)]
    owners = [("A", 2, "#5BD69A"), ("B", 6, "#C792EA"), ("C", 10, "#FF7A7A")] + ([("D", 9, "#F2D16B")] if with_d else [])
    for j, (oid, pos, col) in enumerate(owners):
        off = (owner_offsets or {}).get(oid, 92)
        nodes.append({"id": oid, "label": oid, "pos": pos, "role": "owner", "ringOffset": off, "color": col})
    # placeholder x, y: the renderer places ring nodes from pos (build_manifest.py writes the same)
    for n in nodes:
        n.setdefault("x", 0)
        n.setdefault("y", 0)
    return {"layout": "ring", "ring": {"positions": positions, "cx": 864, "cy": 356, "r": 165}, "camera": {"zoom": 1.1},
            "nodes": nodes, "edges": []}


@unittest.skipUnless(REMOTION and (Path(REMOTION) / "node_modules" / "remotion").is_dir(),
                     "set PE_REMOTION_DIR to a Remotion project with node_modules to run the renderer tests")
class W11bRenderer(unittest.TestCase):
    proj: Path
    tmp: Path

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="w11b-remotion-"))
        cls.proj = cls.tmp / "remotion"
        shutil.copytree(TEMPLATE, cls.proj, ignore=shutil.ignore_patterns("node_modules", "out"))
        (cls.proj / "node_modules").symlink_to(Path(REMOTION).resolve() / "node_modules")
        (cls.proj / "w11b-entry.ts").write_text(ENTRY)
        cls.base = json.loads((cls.proj / "public" / "episodes" / "sample-ring" / "episode.json").read_text())
        r = subprocess.run(["npx", "esbuild", "w11b-entry.ts", "--bundle", "--format=esm", "--platform=node",
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

    def episode(self, slug: str, scenes: list[dict], world=None, overlays=None) -> dict:
        ep = copy.deepcopy(self.base)
        ep["scenes"] = scenes
        ep["overlays"] = overlays or []
        ep["world"] = world
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

    def visible(self, ep: dict, *times: int) -> list[list[str]]:
        return self.js("return D.ts.map((t) => M.visibleTextsAt(D.ep, t));", ep=ep, ts=list(times))

    # ------------------------------------------------------------------------------- tests

    def test_typecheck(self):
        r = subprocess.run(["npx", "tsc", "--noEmit"], cwd=self.proj, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_chip_expires_at_next_step_unless_persist(self):
        world = {"nodes": [{"id": "a", "label": "alpha", "x": 400, "y": 300}], "edges": []}
        steps = [{"atMs": 2000, "reveal": ["a"]}, {"atMs": 6000, "focus": ["a"]}, {"atMs": 12000, "focus": []}]
        chips = [{"id": "c1", "type": "chip", "startMs": 3000, "endMs": 9000, "props": {"text": "keys per server 4"}},
                 {"id": "c2", "type": "chip", "startMs": 3000, "endMs": 9000, "props": {"text": "hash ring", "persist": True}}]
        ep = self.episode("w11b-chip", [self.whole("w1", "world", {"steps": steps})], world=world, overlays=chips)
        at4, at6_5, at8_5 = self.visible(ep, 4000, 6500, 8500)
        self.assertIn("keys per server 4", at4)
        self.assertNotIn("keys per server 4", at6_5)  # the step at 6000 changed the state
        self.assertIn("hash ring", at6_5)  # persist keeps it to its own end
        self.assertIn("hash ring", at8_5)
        win = self.js("const t = M.visualStepTimes(D.ep); return D.ep.overlays.map((o) => M.chipFrames(o, t, 30));", ep=ep)
        self.assertEqual(win[0]["expiredBy"], 6000)
        self.assertEqual(win[0]["end"], 6000 * FPS // 1000 - 3)  # the next step's cue frame
        self.assertIsNone(win[1]["expiredBy"])
        for f in (120, 195):
            r = self.still("w11b-chip", f)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_node_value_expires_never_reverts_and_persist_keeps(self):
        world = {"nodes": [{"id": "n1", "label": "keys per server", "value": "4 each", "x": 500, "y": 250, "w": 460, "revealAtMs": 1000},
                           {"id": "n2", "label": "keys moved", "value": "0 of 12", "persist": True, "x": 500, "y": 500, "w": 460, "revealAtMs": 1000}],
                 "edges": []}
        steps = [{"atMs": 1000, "reveal": ["n1", "n2"]}, {"atMs": 3000, "focus": ["n1"]},
                 {"atMs": 5000, "set": {"n1": {"value": "3 each"}, "n2": {"value": "3 of 12", "persist": True}}},
                 {"atMs": 7000, "focus": []}]
        ep = self.episode("w11b-value", [self.whole("w1", "world", {"steps": steps})], world=world)
        a, b, c, d = self.visible(ep, 2000, 4000, 6000, 8000)
        self.assertIn("4 each", a)
        self.assertIn("0 of 12", a)
        self.assertNotIn("4 each", b)  # own value expired at the next step
        self.assertIn("0 of 12", b)  # persist
        self.assertIn("3 each", c)
        self.assertIn("3 of 12", c)
        self.assertNotIn("3 each", d)  # set value expired
        self.assertNotIn("4 each", d)  # and never reverts to the older value
        self.assertIn("3 of 12", d)
        self.assertIn("keys per server", d)  # the structural label stays
        r = self.still("w11b-value", 240)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_banner_and_stat_expire_unless_persist(self):
        props = {
            "left": {"title": "before", "kind": "table", "columns": ["0", "1", "2", "3"],
                     "rows": [{"id": "r1", "label": "old", "cells": ["A", "B", "C", "A"]}, {"id": "r2", "label": "new", "cells": ["D", "D", "B", "A"]}],
                     "steps": [{"atMs": 1000, "fill": {"r2": "all"}}, {"atMs": 3000, "stat": "moved: 3 of 4"},
                               {"atMs": 6000, "marks": {"r2": [0]}}, {"atMs": 8000, "stat": {"text": "kept: 1 of 4", "persist": True}},
                               {"atMs": 9000, "marks": {}}]},
            "right": {"title": "notes", "kind": "text", "lines": [{"text": "a line"}]},
            "verdict": {"text": "first verdict", "winner": "right", "atMs": 4000},
            "banners": [{"text": "kept banner", "winner": "none", "atMs": 7000, "persist": True}],
        }
        ep = self.episode("w11b-banner", [self.whole("c1", "compare", props)])
        t35, t45, t65, t75, t95 = self.visible(ep, 3500, 4500, 6500, 7500, 9500)
        self.assertIn("moved: 3 of 4", t35)
        self.assertIn("first verdict", t45)
        self.assertIn("wrong", t45)
        self.assertNotIn("moved: 3 of 4", t65)  # the left panel's next step at 6000
        self.assertNotIn("first verdict", t65)  # any panel's next step at 6000
        self.assertNotIn("wrong", t65)  # neutral again
        self.assertIn("kept banner", t75)
        self.assertIn("kept banner", t95)  # persist outlives the step at 9000
        self.assertIn("kept: 1 of 4", t95)
        for f in (135, 195):
            r = self.still("w11b-banner", f)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_count_claim_and_label_sources(self):
        claim = {"kind": "count", "value": 2, "of": 4, "scope": "cells-changed-to", "to": "D"}
        props = {"left": {"title": "mod", "tag": "0 of 4 move", "kind": "table", "columns": ["0", "1", "2", "3"],
                          "rows": [{"id": "r1", "label": "before", "cells": ["A", "B", "C", "A"]},
                                   {"id": "r2", "label": "after", "cells": ["D", "D", "B", "A"]}],
                          "steps": [{"atMs": 1000, "stat": {"text": "2 of 4 move to D", "claim": claim}}]},
                 "right": {"title": "notes", "kind": "text", "lines": [{"text": "x"}]}}
        ep = self.episode("w11b-claim", [self.whole("c1", "compare", props)])
        out = self.js(
            "const sc = D.ep.scenes[0]; const p = sc.props.left; const st = M.panelStateAt(p, 0, 30, 60);"
            "return { labels: M.labelSourcesAt(D.ep, 2000), to: M.countClaim(p, st, D.claim),"
            " changed: M.countClaim(p, st, {kind: 'count', value: 3, of: 4, scope: 'columns-changed'}),"
            " wrong: M.countClaim(p, st, {kind: 'count', value: 0, of: 4, scope: 'columns-changed'}) };",
            ep=ep, claim=claim)
        self.assertEqual(out["to"]["value"], 2)
        self.assertTrue(out["to"]["ok"] and out["to"]["exact"])
        self.assertEqual(out["changed"]["value"], 3)
        self.assertTrue(out["changed"]["ok"])
        self.assertFalse(out["wrong"]["ok"])
        src = {(x["source"], x["text"]) for x in out["labels"]}
        self.assertIn(("tag", "0 of 4 move"), src)  # R02: the tag is a label source
        self.assertIn(("title", "mod"), src)
        stat = next(x for x in out["labels"] if x["source"] == "stat")
        self.assertEqual(stat["claim"], claim)

    def test_ring_is_a_true_circle(self):
        world = ring_world()
        world["nodes"].append({"id": "k12", "label": "x", "angle": 45, "role": "item", "x": 0, "y": 0})
        out = self.js("return { nodes: M.placeNodes(D.w), face: M.ringFaceRadius(D.w), problems: M.ringProblems(D.w) };", w=world)
        self.assertEqual(out["problems"], [])
        for n in out["nodes"]:
            if n.get("role") is None:
                continue
            dx, dy = n["x"] - 864, n["y"] - 356
            radius = math.hypot(dx, dy)
            want_r = 165 + (92 if n["role"] == "owner" else 0)
            self.assertAlmostEqual(radius, want_r, places=6, msg=n["id"])
            angle = math.degrees(math.atan2(dx, -dy)) % 360  # clockwise from 12 o'clock
            want_a = n["angle"] if "angle" in n else n["pos"] * 360 / 12
            self.assertAlmostEqual(angle, want_a % 360, places=6, msg=n["id"])
        # keys 3 and 9 sit exactly on the horizontal diameter, as far out as keys 0 and 6
        k = {n["id"]: n for n in out["nodes"]}
        self.assertAlmostEqual(k["k3"]["x"] - 864, 165, places=6)
        self.assertAlmostEqual(864 - k["k9"]["x"], 165, places=6)
        self.assertAlmostEqual(out["face"], 165 + 92)  # the clock face rim is the owner track
        bent = ring_world(owner_offsets={"B": 40})
        self.assertTrue(self.js("return M.ringProblems(D.w);", w=bent))
        clock = ring_world()
        steps = [{"atMs": 500, "reveal": [n["id"] for n in clock["nodes"]]}]
        self.episode("w11b-ring", [self.whole("w1", "world", {"steps": steps})], world=clock)
        r = self.still("w11b-ring", 60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.episode("w11b-ring-bent", [self.whole("w1", "world", {"steps": steps})], world=bent)
        r = self.still("w11b-ring-bent", 60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ringOffset", r.stdout + r.stderr)

    def walk_world_steps(self, walk2):
        world = ring_world()
        keys = [f"k{i}" for i in range(12)]
        steps = [{"atMs": 500, "reveal": keys + ["A", "B", "C"]}, {"atMs": 1500, "walk": ["k4"]},
                 {"atMs": 3000, "reveal": ["D"]}, {"atMs": 4000, "walk": walk2}]
        for n in world["nodes"]:  # build_manifest.py default: revealed by the first step that names it
            n["revealAtMs"] = 3000 if n["id"] == "D" else 500
        return world, steps

    def test_walk_arrow_ends_at_successor(self):
        world, steps = self.walk_world_steps(["k7", {"item": "k4", "to": "B"}])
        out = self.js(
            "const nodes = M.placeNodes(D.w); const tl = D.steps.map((s) => ({...s, t: s.atMs, sceneId: 'w1'}));"
            "const g = M.ringGeometry(D.w); const tr = M.ringTracks(D.w);"
            "const plans = M.walkPlan(D.w, nodes, tl, tl[3]);"
            "return { plans, problems: M.walkProblems(D.w, tl), ends: plans.map((p) => { const pts = M.walkPoints(p, nodes, g, tr); return pts[pts.length - 1]; }),"
            " nodes: Object.fromEntries(nodes.map((n) => [n.id, [n.x, n.y, M.nodeSize(n).w]])) };",
            w=world, steps=steps)
        self.assertEqual(out["problems"], [])
        plans = {p["item"]: p for p in out["plans"]}
        self.assertEqual(plans["k7"]["target"], "D")  # D at 9 is k7's successor once revealed
        self.assertEqual(plans["k4"]["target"], "B")  # key 4 never gets as far as D
        for p, end in zip(out["plans"], out["ends"]):
            tx, ty, tw = out["nodes"][p["target"]]
            dist = math.hypot(end["x"] - tx, end["y"] - ty)
            self.assertLess(dist, tw / 2 + 20, f"{p['item']} arrow ends {dist:.1f} units from {p['target']}")
            for other in ("A", "B", "C", "D"):
                if other != p["target"]:
                    ox, oy, _ = out["nodes"][other]
                    self.assertGreater(math.hypot(end["x"] - ox, end["y"] - oy), dist + 40)
        bad_world, bad_steps = self.walk_world_steps([{"item": "k4", "to": "D"}])
        tl = "D.steps.map((s) => ({...s, t: s.atMs, sceneId: 'w1'}))"
        bad = self.js(f"return M.walkProblems(D.w, {tl});", w=bad_world, steps=bad_steps)
        self.assertEqual(len(bad), 1)
        self.assertIn("successor is B", bad[0])
        _, over_steps = self.walk_world_steps([{"item": "k4", "to": "C", "overshoot": True}])
        self.assertEqual(self.js(f"return M.walkProblems(D.w, {tl});", w=bad_world, steps=over_steps), [])
        self.episode("w11b-walk", [self.whole("w1", "world", {"steps": steps})], world=world)
        r = self.still("w11b-walk", 150)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.episode("w11b-walk-over", [self.whole("w1", "world", {"steps": over_steps})], world=bad_world)
        r = self.still("w11b-walk-over", 150)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.episode("w11b-walk-bad", [self.whole("w1", "world", {"steps": bad_steps})], world=bad_world)
        r = self.still("w11b-walk-bad", 150)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("successor is B", r.stdout + r.stderr)

    def table_props(self, columns, rows, title=None):
        p = {"left": {"title": "wide", "kind": "table", "columns": columns, "rows": rows},
             "right": {"title": "notes", "kind": "text", "lines": [{"text": "x"}]}}
        if title:
            p["title"] = title
        return p

    def test_fourteen_column_table_rejected_or_28px(self):
        # R01: 14 columns with two-character headers and 6 rows under a title: 13 px cells before W11b.
        cols = [str(i) for i in range(14)]
        rows = [{"id": f"r{j}", "label": f"row {j}", "cells": ["A"] * 14} for j in range(6)]
        props = self.table_props(cols, rows, title="Fourteen columns")
        bad = self.js("return M.tableProblems(D.p.left, true);", p=props)
        self.assertTrue(bad)
        self.assertIn("must be at least 28 px", bad[-1])
        # with 2-character headers no column count fits 6 rows under a title; the message says so
        self.assertTrue("At most" in bad[-1] or "No column count fits 6 rows" in bad[-1], bad[-1])
        self.episode("w11b-table-bad", [self.whole("c1", "compare", props)])
        r = self.still("w11b-table-bad", 30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("must be at least 28 px", r.stdout + r.stderr)
        # One-character headers fit in one band of 14 at 28 px or more.
        ok_cols = [chr(97 + i) for i in range(14)]
        ok = self.table_props(ok_cols, rows, title="Fourteen columns")
        lay = self.js("return { L: M.panelTableLayout(D.p.left, true), bad: M.tableProblems(D.p.left, true) };", p=ok)
        self.assertEqual(lay["bad"], [])
        self.assertGreaterEqual(lay["L"]["font"], 28)
        self.assertGreaterEqual(lay["L"]["cell"], lay["L"]["font"])
        self.assertEqual(sorted(i for b in lay["L"]["bands"] for i in b), list(range(14)))
        ep = self.episode("w11b-table-ok", [self.whole("c1", "compare", ok)])
        texts = self.visible(ep, 1000)[0]
        self.assertEqual(texts.count("A"), 14 * 6)
        r = self.still("w11b-table-ok", 30)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_mismatched_row_rejected_and_not_counted(self):
        props = self.table_props(["col"], [{"id": "r1", "label": "keys", "cells": ["A", "LOST"]}])
        bad = self.js("return M.tableProblems(D.p.left, false);", p=props)
        self.assertTrue(any("row r1 has 2 cells for 1 columns" in b for b in bad), bad)
        ep = self.episode("w11b-row-bad", [self.whole("c1", "compare", props)])
        self.assertNotIn("LOST", self.visible(ep, 1000)[0])  # R03: only drawn indexes count
        r = self.still("w11b-row-bad", 30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("give every row exactly one cell per column", r.stdout + r.stderr)

    def test_entrance_frames_finish_before_speech(self):
        cases = [{"start": 3017, "enter": 233, "turns": [{"startMs": 3250, "endMs": 6000}]},  # Codex A09 case
                 {"start": 4000, "enter": None, "turns": [{"startMs": 3500, "endMs": 6000}]},  # inside speech: cut
                 {"start": 1000, "enter": None, "turns": [{"startMs": 1040, "endMs": 3000}]}]  # 1 frame of room: cut
        rng = random.Random(11)
        for _ in range(400):
            s = rng.randint(0, 20000)
            cases.append({"start": s, "enter": rng.choice([None, 0, 100, 150, 233, 250]),
                          "turns": [{"startMs": s + rng.randint(0, 400), "endMs": s + 5000}]})
        out = self.js("return D.cases.map((c) => M.entranceFrames(c.start, c.enter ?? undefined, c.turns, 30));", cases=cases)
        self.assertEqual(out[0], 6)
        self.assertLessEqual((round(3017 * FPS / 1000) + 6) * 1000 / FPS, 3250)
        self.assertEqual(out[1], 0)
        self.assertEqual(out[2], 0)
        for c, n in zip(cases, out):
            self.assertLessEqual(n, 7)
            if n:
                frm = round(c["start"] * FPS / 1000)
                self.assertLessEqual((frm + n) * 1000 / FPS, c["turns"][0]["startMs"], c)
        self.assertIn("entranceFrames(scene.startMs, scene.enterMs, manifest.turns, fps)", (self.proj / "src" / "Episode.tsx").read_text())

    def test_panel_ring_text_and_centre_label(self):
        world = ring_world(with_d=False)
        world["nodes"].append({"id": "centre", "label": "hash ring", "x": 864, "y": 356, "shape": "pill", "w": 200, "h": 76})
        out = self.js(
            "const b = M.compareBodySize(false); const cam = M.fitCamera(D.w, b.w, b.h); const s = M.viewScale(D.w, b.w, b.h, cam);"
            "const keep = M.ringInsetFilter(D.w, s); return { s, centre: keep(D.w.nodes.find((n) => n.id === 'centre')),"
            " full: M.ringInsetFilter(D.w)(D.w.nodes.find((n) => n.id === 'centre')) };", w=world)
        self.assertGreaterEqual(max(42, 32 / out["s"]) * out["s"], 32 - 1e-9)  # numerals at 32 px or more in a panel
        self.assertFalse(out["centre"])  # "hash ring" cannot fit inside the panel ring at 28 px: not drawn
        self.assertTrue(out["full"])
        props = {"left": {"title": "ring", "kind": "world", "world": world,
                          "steps": [{"atMs": 300, "reveal": [n["id"] for n in world["nodes"]]}]},
                 "right": {"title": "notes", "kind": "text", "lines": [{"text": "x"}]}}
        ep = self.episode("w11b-panel-ring", [self.whole("c1", "compare", props)])
        self.assertNotIn("hash ring", self.visible(ep, 2000)[0])
        r = self.still("w11b-panel-ring", 60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_stills_every_scene_type(self):
        # sample: title, world, equation, code, world (set), diagram, custom, recap, check;
        # sample-ring: ring world with a walk, custom RingLoad, compare (table + shared ring).
        for slug, frames in (("sample", "60,240,300,420,540,580,640,700,800"), ("sample-ring", "300,560,1000")):
            out = self.stills / slug
            r = subprocess.run(["npx", "remotion", "render", "Episode", str(out), f"--props={json.dumps({'slug': slug})}",
                                f"--frames={frames}", "--image-format=png", "--log=error"],
                               cwd=self.proj, capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])
            self.assertEqual(len(list(out.glob("element-*.png"))), len(frames.split(",")))


if __name__ == "__main__":
    unittest.main()
