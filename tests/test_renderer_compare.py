"""W8b renderer tests: plain compare tables (N02), banners and panel title changes, ring tints,
captions around pause holds (N05), SVG CSS sanitising (N07), the pure visible-text function (B06)
and the entrance constant (A09). Run from the skill folder:

    python3 -m unittest tests.test_renderer_compare -v

The caption test needs only node (type stripping, Node 22.6 or later). The renderer tests need a
Remotion project with node_modules: set PE_REMOTION_DIR to one (for example explainers/remotion
after `npm install`). Without it they are skipped. They copy templates/remotion into a temporary
project that links that node_modules, type-check it, bundle src/visibleText.ts with esbuild, and
render stills with `npx remotion still` (about 5 to 10 s each on an M-series Mac).
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
TEMPLATE = SKILL / "templates" / "remotion"
SRC = TEMPLATE / "src"


def words(text: str, start: int, per: int = 300) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "startMs": t, "endMs": t + per - 40, "source": "asr"})
        t += per
    return out


def run_node(script: str, *args: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "h.mjs"
        h.write_text(script)
        return subprocess.run(["node", str(h), *args], capture_output=True, text=True, timeout=60)


class Constants(unittest.TestCase):
    def test_entrance_fits_default_gap(self):
        # A09: one entrance constant, at or below the 250 ms default gap, consistent with its frames.
        text = (SRC / "motionConstants.ts").read_text()
        ms = int(re.search(r"ENTRANCE_MS = (\d+)", text).group(1))
        frames = int(re.search(r"ENTRANCE_FRAMES = (\d+)", text).group(1))
        self.assertLessEqual(ms, 250)
        self.assertEqual(ms, round(frames * 1000 / 30))
        self.assertIn("enterFrames: ENTRANCE_FRAMES", (SRC / "theme.ts").read_text())


@unittest.skipUnless(shutil.which("node"), "node not installed")
class CaptionHolds(unittest.TestCase):
    """N05: the early-start pass never moves an answer page into a pause-and-think hold."""

    HARNESS = (
        "import { pathToFileURL } from 'node:url';\n"
        "const [, , mod, data] = process.argv;\n"
        "const { buildCaptionPages } = await import(pathToFileURL(mod).href);\n"
        "const d = JSON.parse(data);\n"
        "const pages = buildCaptionPages(d.turns, 'karaoke', 17, 700, d.holds);\n"
        "console.log(JSON.stringify(pages.map((p) => [p.turnId, p.startMs, p.endMs])));\n"
    )

    def pages(self, holds):
        q = {"id": "t01", "speaker": "host", "segment": "s", "text": "", "startMs": 0, "endMs": 1000,
             "words": words("Which algorithm is it?", 0, per=250)}
        # A fast answer 250 ms after the 7 s hold: without the fix it starts 500 ms early, at 7750.
        a = {"id": "t02", "speaker": "guest", "segment": "s", "text": "", "startMs": 8250, "endMs": 9000,
             "words": words("The algorithm is consistent hashing.", 8250, per=150)}
        # The next turn follows at once, so the answer page is too fast to read and wants an early start.
        n = {"id": "t03", "speaker": "host", "segment": "s", "text": "", "startMs": 9200, "endMs": 10500,
             "words": words("Right, the ring.", 9200, per=400)}
        r = run_node(self.HARNESS, str(SRC / "components" / "captionPages.ts"), json.dumps({"turns": [q, a, n], "holds": holds}))
        if r.returncode != 0 and "Unknown file extension" in r.stderr:
            self.skipTest("this node cannot strip TypeScript types")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_answer_page_waits_for_hold_end(self):
        pages = self.pages([{"startMs": 1000, "endMs": 8000}])
        first_answer = min(p[1] for p in pages if p[0] == "t02")
        self.assertGreaterEqual(first_answer, 8000, pages)

    def test_without_hold_page_may_start_early(self):
        # Control: the same turns without a hold use the early start, so the test above is meaningful.
        pages = self.pages([])
        self.assertLess(min(p[1] for p in pages if p[0] == "t02"), 8000, pages)


REMOTION = os.environ.get("PE_REMOTION_DIR")


@unittest.skipUnless(REMOTION and (Path(REMOTION) / "node_modules" / "remotion").is_dir(),
                     "set PE_REMOTION_DIR to a Remotion project with node_modules to run the renderer tests")
class Renderer(unittest.TestCase):
    proj: Path
    tmp: Path

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="w8b-remotion-"))
        cls.proj = cls.tmp / "remotion"
        shutil.copytree(TEMPLATE, cls.proj, ignore=shutil.ignore_patterns("node_modules", "out"))
        (cls.proj / "node_modules").symlink_to(Path(REMOTION).resolve() / "node_modules")
        cls.base = json.loads((cls.proj / "public" / "episodes" / "sample-ring" / "episode.json").read_text())
        r = subprocess.run(["npx", "esbuild", "src/visibleText.ts", "--bundle", "--format=esm", "--platform=node",
                            f"--outfile={cls.tmp / 'vt.mjs'}", "--log-level=warning"],
                           cwd=cls.proj, capture_output=True, text=True, timeout=120)
        cls.vt_error = None if r.returncode == 0 else r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def npx(self, *args, timeout=300):
        return subprocess.run(["npx", *args], cwd=self.proj, capture_output=True, text=True, timeout=timeout)

    def episode(self, slug: str, scenes: list[dict], files: dict[str, str] | None = None, world=None) -> dict:
        ep = copy.deepcopy(self.base)
        ep["scenes"] = scenes
        ep["overlays"] = []
        if world is not None:
            ep["world"] = world
        d = self.proj / "public" / "episodes" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "episode.json").write_text(json.dumps(ep))
        for name, text in (files or {}).items():
            (d / name).parent.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(text)
        return ep

    def still(self, slug: str, frame: int) -> subprocess.CompletedProcess:
        out = self.tmp / f"{slug}-{frame}.png"
        r = self.npx("remotion", "still", "Episode", str(out), f"--props={json.dumps({'slug': slug})}", f"--frame={frame}")
        if r.returncode == 0:
            self.assertTrue(out.is_file() and out.stat().st_size > 10_000, r.stdout[-500:])
        return r

    def visible(self, ep: dict, *times: int) -> list[list[str]]:
        if self.vt_error:
            self.fail(f"esbuild could not bundle src/visibleText.ts: {self.vt_error[-800:]}")
        script = (
            "import { readFileSync } from 'node:fs';\n"
            "import { pathToFileURL } from 'node:url';\n"
            "const [, , mod, file, ...ts] = process.argv;\n"
            "const { visibleTextsAt } = await import(pathToFileURL(mod).href);\n"
            "const m = JSON.parse(readFileSync(file, 'utf8'));\n"
            "console.log(JSON.stringify(ts.map((t) => visibleTextsAt(m, Number(t)))));\n"
        )
        f = self.tmp / "vt-input.json"
        f.write_text(json.dumps(ep))
        r = run_node(script, str(self.tmp / "vt.mjs"), str(f), *map(str, times))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def compare(self, props: dict) -> list[dict]:
        return [{"id": "c1", "type": "compare", "startMs": 0, "endMs": self.base["audio"]["durationMs"], "props": props}]

    # ----------------------------------------------------------------------------------- tests

    def test_typecheck(self):
        r = self.npx("tsc", "--noEmit")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_plain_table_renders(self):
        # N02: rows with no `at` and no fill steps (schema-valid) must render, not throw. (W11b: every
        # row has one cell per column; a short row is rejected, see test_renderer_w11b.)
        props = {"left": {"title": "plain", "kind": "table", "columns": ["A", "B", "C"],
                          "rows": [{"id": "r1", "label": "Keys", "cells": ["3", "5", "4"]}, {"id": "r2", "label": "Load", "cells": ["4", "4", "4"]}]},
                 "right": {"title": "lines", "kind": "text", "lines": [{"text": "visible from the start"}]}}
        ep = self.episode("w8b-plain", self.compare(props))
        r = self.still("w8b-plain", 30)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertNotIn("inputRange must contain only finite numbers", r.stderr)
        texts = self.visible(ep, 500)[0]
        for t in ("Keys", "3", "Load", "4", "visible from the start"):
            self.assertIn(t, texts)

    def test_enter_ms_cut_and_short_fade_render(self):
        # A09: build_manifest.py writes scenes[].enterMs (0 = cut); the template reads it per scene.
        props = {"left": {"title": "a", "kind": "text", "lines": [{"text": "x"}]}, "right": {"title": "b", "kind": "text", "lines": [{"text": "y"}]}}
        for slug, ms in (("w8b-cut", 0), ("w8b-short", 120)):
            sc = self.compare(props)
            sc[0]["enterMs"] = ms
            self.episode(slug, sc)
            r = self.still(slug, 1)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_fill_and_banners(self):
        mod3, mod4 = ["A", "B", "C"] * 4, ["A", "B", "C", "D"] * 3
        props = {
            "left": {"title": "hash mod N", "tag": "naive", "kind": "table", "columns": [str(i) for i in range(12)],
                     "rows": [{"id": "m3", "label": "mod 3", "cells": mod3}, {"id": "m4", "label": "mod 4", "cells": mod4, "atMs": 2000}],
                     "steps": [{"atMs": 1000, "fill": {"m3": "all", "m4": []}},
                               {"atMs": 3000, "fill": {"m4": "all"}, "stat": "moved: 9 of 12"},
                               {"atMs": 9000, "title": "mod, fixed N", "tag": ""}]},
            "right": {"title": "notes", "kind": "text", "lines": [{"text": "ring", "atMs": 2500}]},
            "verdict": {"text": "Ring: one stretch, one neighbour", "winner": "right", "atMs": 4000},
            "banners": [{"text": "2 points: 2 neighbours", "labels": {"left": "moves 9", "right": "moves 3"}, "atMs": 7000},
                        {"text": "", "atMs": 11000}],
        }
        ep = self.episode("w8b-banner", self.compare(props))
        at = dict(zip((500, 2200, 3500, 5000, 8000, 12000), self.visible(ep, 500, 2200, 3500, 5000, 8000, 12000)))
        self.assertNotIn("mod 4", at[500])  # row cue not reached
        self.assertIn("?", at[2200])  # m4 visible, not yet filled
        self.assertNotIn("D", at[2200])
        self.assertIn("D", at[3500])  # filled on its word
        self.assertIn("moved: 9 of 12", at[3500])
        self.assertNotIn("Ring: one stretch, one neighbour", at[3500])  # verdict not before its word
        self.assertIn("Ring: one stretch, one neighbour", at[5000])
        self.assertIn("wrong", at[5000])
        self.assertNotIn("Ring: one stretch, one neighbour", at[8000])  # replaced
        self.assertIn("2 points: 2 neighbours", at[8000])
        self.assertIn("moves 9", at[8000])
        self.assertNotIn("wrong", at[8000])  # winner none: neutral
        self.assertNotIn("2 points: 2 neighbours", at[12000])  # hidden
        self.assertIn("mod, fixed N", at[12000])
        self.assertNotIn("naive", at[12000])
        for frame in (60, 150, 240, 330):
            r = self.still("w8b-banner", frame)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_hide_removes_world_text_and_tint_renders(self):
        world = copy.deepcopy(self.base["world"])
        sc = copy.deepcopy(self.base["scenes"][0])
        last = max(s.get("atMs", 0) for s in sc["props"]["steps"])
        sc["props"]["steps"] += [{"atMs": last + 500, "tint": {"warn": ["k5", "k6"], "bad": ["k1", "k2"]}},
                                 {"atMs": last + 1500, "hide": ["B"]}]
        sc["startMs"], sc["endMs"] = 0, self.base["audio"]["durationMs"]
        ep = self.episode("w8b-tint", [sc], world=world)
        before, after = self.visible(ep, last + 1000, last + 2500)
        self.assertIn("B", before)
        self.assertNotIn("B", after)
        r = self.still("w8b-tint", round((last + 1000) * 30 / 1000))
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def svg(self, slug: str, body: str) -> subprocess.CompletedProcess:
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" id="m1" viewBox="0 0 300 100">{body}<rect class="n" x="1" y="1" width="90" height="50"/></svg>'
        self.episode(slug, [{"id": "d1", "type": "diagram", "startMs": 0, "endMs": self.base["audio"]["durationMs"],
                             "props": {"title": "SVG", "svg": "diagrams/x.svg"}}], files={"diagrams/x.svg": svg})
        return self.still(slug, 30)

    def test_svg_scoped_style_renders(self):
        r = self.svg("w8b-svg-ok", "<style>#m1 .n{fill:#202736;stroke:#7CC4FF;stroke-width:4px;cursor:pointer} svg text{font-size:28px}</style>")
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_svg_css_escapes_and_global_rules_fail(self):
        # N07: the three Codex round-2 payloads.
        for slug, css in [("w8b-svg-url", "svg {filter:u\\72l(https://invalid.example/test.svg#x)}"),
                          ("w8b-svg-import", '@\\69mport "https://invalid.example/test.css";'),
                          ("w8b-svg-global", "div {display:none !important}")]:
            r = self.svg(slug, f"<style>{css}</style>")
            self.assertNotEqual(r.returncode, 0, slug)
            self.assertIn("not safe to insert", r.stdout + r.stderr, slug)


if __name__ == "__main__":
    unittest.main()
