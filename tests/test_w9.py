"""W9a tests: renderer parity for the Python scripts.

- A09: build_manifest.py ENTER_MS is the renderer's motionConstants.ts ENTRANCE_MS.
- N05: qc.py caption_pages takes manifest holds; the captions.hold check.
- N07: build_manifest.py svg_problems mirrors svgSanitize.ts (accept / refuse parity in node).
- B06: pe_common.visible_texts_at mirrors visibleText.ts visibleTextsAt (parity in node).
- text.minsize: custom components and SVG files under 28 px.

Run from the skill folder:

    PE_REMOTION_DIR=explainers/remotion python3 -m unittest tests.test_w9 -v

The parity tests bundle templates/remotion/src/*.ts with the esbuild in PE_REMOTION_DIR's
node_modules and run the bundle in node. Without PE_REMOTION_DIR (or node) they are skipped.
"""
from __future__ import annotations

import copy
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
TEMPLATE = SKILL / "templates" / "remotion"
SRC = TEMPLATE / "src"
sys.path.insert(0, str(SCRIPTS))
import build_manifest as bm  # noqa: E402
import pe_common as pc  # noqa: E402
import qc  # noqa: E402

REMOTION = os.environ.get("PE_REMOTION_DIR")
ESBUILD = Path(REMOTION).resolve() / "node_modules" / ".bin" / "esbuild" if REMOTION else None
HAVE_BUNDLER = bool(shutil.which("node") and ESBUILD and ESBUILD.is_file())


def bundle(entry: Path, out: Path) -> None:
    r = subprocess.run([str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", f"--outfile={out}",
                        "--log-level=warning"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise AssertionError(f"esbuild could not bundle {entry.name}: {r.stderr[-800:]}")


def run_node(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    h = cwd / "h.mjs"
    h.write_text(script)
    return subprocess.run(["node", str(h), *args], capture_output=True, text=True, timeout=120)


def norm(texts: list) -> list[str]:
    """Drop what the renderer would not draw (null, undefined, ""); numbers as JS prints them."""
    out = []
    for x in texts:
        if x is None or x == "" or x is False:
            continue
        if isinstance(x, float) and x.is_integer():
            x = int(x)
        out.append(str(x))
    return out


# ------------------------------------------------------------------------------------- A09

class EntranceConstant(unittest.TestCase):
    def ts_ms(self, root: Path) -> int:
        return int(re.search(r"export const ENTRANCE_MS = (\d+)", (root / "src" / "motionConstants.ts").read_text()).group(1))

    def test_python_constant_equals_typescript(self):
        self.assertEqual(bm.ENTER_MS, self.ts_ms(TEMPLATE))
        self.assertEqual(bm.ENTER_MS, 233)
        self.assertEqual(bm.read_entrance_ms(TEMPLATE), self.ts_ms(TEMPLATE))

    def test_reads_the_synced_project_and_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / "src").mkdir()
            (proj / "src" / "motionConstants.ts").write_text("export const ENTRANCE_FRAMES = 6;\nexport const ENTRANCE_MS = 200;\n")
            self.assertEqual(bm.read_entrance_ms(proj), 200)
            self.assertEqual(bm.read_entrance_ms(proj / "missing"), self.ts_ms(TEMPLATE), "falls back to the skill template")
        with mock.patch.object(bm, "SKILL", Path("/nonexistent")):
            self.assertEqual(bm.read_entrance_ms(None), bm.ENTRANCE_MS_FALLBACK)

    def test_place_entrances_uses_the_given_length_and_sets_the_first_scene(self):
        turns = [{"id": "t01", "startMs": 150, "endMs": 3000}, {"id": "t02", "startMs": 4000, "endMs": 6000}]
        scenes = [{"id": "s1", "type": "title", "startMs": 0, "endMs": 4000}, {"id": "s2", "type": "diagram", "startMs": 4000, "endMs": 9000}]
        bm.place_entrances(scenes, turns, 200)
        self.assertEqual(scenes[0]["enterMs"], 133, "the first scene's fade fits the silence before the first word, in whole frames")
        self.assertEqual((scenes[1]["enterLeadMs"], scenes[1]["enterMs"]), (200, 200))
        scenes = [{"id": "s1", "type": "title", "startMs": 0, "endMs": 4000}, {"id": "s2", "type": "diagram", "startMs": 4000, "endMs": 9000}]
        bm.place_entrances(scenes, [{"id": "t01", "startMs": 0, "endMs": 3000}])
        self.assertEqual(scenes[0]["enterMs"], 0, "speech at 0: the first scene cuts in")
        self.assertEqual(scenes[1]["enterMs"], bm.ENTER_MS)

    def test_renderer_reads_enter_ms_per_scene(self):
        ep = (SRC / "Episode.tsx").read_text()
        self.assertIn("scene.enterMs", ep)
        self.assertIn("ENTRANCE_MS", (SRC / "motionConstants.ts").read_text())
        schema = json.dumps(json.loads((SKILL / "schemas" / "episode.schema.json").read_text()))
        self.assertIn("233", schema)
        self.assertNotIn("333", schema)
        self.assertNotIn("333", (SCRIPTS / "build_manifest.py").read_text())


# ------------------------------------------------------------------------------------- N05

def words(text: str, start: int, per: int = 250) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "startMs": t, "endMs": t + per - 40, "source": "asr"})
        t += per
    return out


class CaptionHoldCheck(unittest.TestCase):
    def manifest(self) -> dict:
        q = {"id": "t01", "speaker": "host", "startMs": 0, "endMs": 1000, "words": words("Which algorithm is it?", 0)}
        a = {"id": "t02", "speaker": "guest", "startMs": 8250, "endMs": 9000, "words": words("The algorithm is consistent hashing.", 8250, per=150)}
        n = {"id": "t03", "speaker": "host", "startMs": 9200, "endMs": 10500, "words": words("Right, the ring.", 9200, per=400)}
        return {"turns": [q, a, n], "holds": [{"turn": "t01", "startMs": 1000, "endMs": 8000}], "scenes": [], "overlays": [],
                "captions": {"mode": "karaoke", "maxCharsPerSecond": 17, "minPageMs": 700}}

    def run_captions(self, m: dict) -> dict:
        ep = mock.Mock()
        ep.need_manifest.return_value = m
        return {c["id"]: c for c in qc.captions(ep)}

    def test_hold_check_passes_with_the_port(self):
        c = self.run_captions(self.manifest())["captions.hold"]
        self.assertEqual(c["status"], "pass", c)

    def test_hold_check_fails_when_a_page_starts_inside_the_hold(self):
        real = qc.caption_pages
        with mock.patch.object(qc, "caption_pages", lambda t, mo, c, mi, holds=(): real(t, mo, c, mi)):
            c = self.run_captions(self.manifest())["captions.hold"]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("t02", c["detail"])

    def test_every_caller_passes_holds(self):
        src = (SCRIPTS / "qc.py").read_text()
        calls = re.findall(r"caption_pages\(([^\n]*)\)", src)
        calls = [c for c in calls if not c.startswith("turns: list")]
        self.assertTrue(calls)
        for c in calls:
            self.assertIn("holds", c)


# ------------------------------------------------------------------------------------- N07

# A minimal DOMParser for node: enough XML for sanitizeSvg (elements, attributes, text, CDATA,
# comments, entities); a mismatched tag gives a <parsererror>, like the browser.
DOM_POLYFILL = r"""
const ENT = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };
const dec = (s) => s.replace(/&(#x[0-9a-fA-F]+|#\d+|\w+);/g, (m, e) =>
  e[0] === '#' ? String.fromCodePoint(e[1] === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : (ENT[e] ?? m));
class El {
  constructor(tag, parent) { this.tagName = tag; this.localName = tag.includes(':') ? tag.split(':').pop() : tag; this.attrs = []; this.kids = []; this.parent = parent; }
  get attributes() { return this.attrs.slice(); }
  get children() { return this.kids.filter((k) => k instanceof El); }
  removeAttribute(n) { this.attrs = this.attrs.filter((a) => a.name !== n); }
  setAttribute(n, v) { const a = this.attrs.find((x) => x.name === n); if (a) a.value = v; else this.attrs.push({ name: n, value: v }); }
  remove() { if (this.parent) this.parent.kids = this.parent.kids.filter((k) => k !== this); }
  get textContent() { return this.kids.map((k) => (typeof k === 'string' ? k : k.textContent)).join(''); }
  set textContent(v) { this.kids = [v]; }
}
globalThis.DOMParser = class {
  parseFromString(s) {
    const root = new El('#doc', null);
    let cur = root, bad = false;
    const re = /<!--[\s\S]*?-->|<!\[CDATA\[([\s\S]*?)\]\]>|<\?[\s\S]*?\?>|<![^>]*>|<\/([^\s>]+)\s*>|<([^\s/>]+)((?:\s+[^\s=/>]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>|([^<]+)|(<)/g;
    for (const m of s.matchAll(re)) {
      if (m[1] !== undefined) cur.kids.push(m[1]);
      else if (m[2] !== undefined) { if (cur.tagName !== m[2]) { bad = true; break; } cur = cur.parent; }
      else if (m[3] !== undefined) {
        const el = new El(m[3], cur);
        for (const a of (m[4] || '').matchAll(/([^\s=/>]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)) el.attrs.push({ name: a[1], value: dec(a[2] ?? a[3]) });
        cur.kids.push(el);
        if (!m[5]) cur = el;
      } else if (m[6] !== undefined) { if (cur !== root) cur.kids.push(dec(m[6])); }
      else if (m[7] !== undefined) { bad = true; break; }
    }
    if (cur !== root) bad = true;
    const top = root.children[0];
    return { documentElement: bad ? new El('parsererror', null) : top,
             getElementsByTagName: (n) => (bad && n === 'parsererror' ? [1] : []) };
  }
};
globalThis.XMLSerializer = class { serializeToString() { return ''; } };
"""

SVG_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" id="m1" viewBox="0 0 300 100">'
SVG_TAIL = '<rect class="n" x="1" y="1" width="90" height="50"/><text x="10" y="40">ok</text></svg>'


def svg(body: str) -> str:
    return SVG_HEAD + body + SVG_TAIL


SVG_PAYLOADS = {
    # The three review payloads (Codex round 2).
    "escaped url": svg("<style>svg {filter:u\\72l(https://invalid.example/test.svg#x)}</style>"),
    "escaped import": svg('<style>@\\69mport "https://invalid.example/test.css";</style>'),
    "global div rule": svg("<style>div {display:none !important}</style>"),
    # Mermaid-style safe CSS.
    "mermaid style": svg("<style>#m1 .n{fill:#202736;stroke:#7CC4FF;stroke-width:4px;cursor:pointer} svg text{font-size:28px}"
                         " #m1 .edgePath .path{stroke:#fff} #m1 g > rect.node:first-child, #m1 [data-x=\"a\"]{opacity:0.9}</style>"),
    "local url ref": svg('<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
                         '<rect x="5" y="5" width="9" height="9" fill="url(#g)" style="stroke: url(\'#g\')"/>'),
    "comment in style": svg("<style>/* mermaid */ .n { fill: red }</style>"),
    "use local href": svg('<defs><circle id="c" r="4"/></defs><use xlink:href="#c" x="3" y="3"/>'),
    # Refusals.
    "font-face": svg("<style>@font-face { font-family: x; src: local(Arial) }</style>"),
    "media query": svg("<style>@media (min-width: 1px) { .n { fill: red } }</style>"),
    "image-set": svg("<style>.n { fill: image-set(\"a.png\" 1x) }</style>"),
    "src function": svg('<rect x="1" y="1" width="2" height="2" style="fill: src(foo)"/>'),
    "external url attribute": svg('<rect x="1" y="1" width="2" height="2" fill="url(https://x.example/a.svg#g)"/>'),
    "escape in attribute": svg('<rect x="1" y="1" width="2" height="2" fill="\\72 ed"/>'),
    "body selector": svg("<style>body .n { fill: red }</style>"),
    "bad selector shape": svg("<style>.n:not(.x) > a[href] { fill: red }</style>"),
    "loose css": svg("<style>.n { fill: red } stray</style>"),
    "nested braces": svg("<style>.n { fill: { red } }</style>"),
    "image element": svg('<image href="#x" width="5" height="5"/>'),
    "anchor element": svg('<a href="#x"><rect x="1" y="1" width="2" height="2"/></a>'),
    "event attribute": svg('<rect x="1" y="1" width="2" height="2" onclick="alert(1)"/>'),
    "external href": svg('<use href="https://x.example/s.svg#a"/>'),
    "javascript url": svg('<rect x="1" y="1" width="2" height="2" style="fill: javascript:alert(1)"/>'),
    "expression": svg('<rect x="1" y="1" width="2" height="2" style="width: expression(alert(1))"/>'),
    "binding": svg("<style>.n { behavior: url(#x) }</style>"),
    "script": svg("<script>alert(1)</script>"),
    "foreignObject": svg("<foreignObject><div>x</div></foreignObject>"),
    "doctype": '<!DOCTYPE svg [<!ENTITY x "y">]>' + svg(""),
    "malformed declaration": svg('<rect x="1" y="1" width="2" height="2" style="fill red"/>'),
}


@unittest.skipUnless(HAVE_BUNDLER, "set PE_REMOTION_DIR to a Remotion project with node_modules (esbuild) to run the parity tests")
class SvgSanitizeParity(unittest.TestCase):
    def test_same_accept_and_refuse_as_the_renderer(self):
        with tempfile.TemporaryDirectory(prefix="w9-svg-") as d:
            d = Path(d)
            bundle(SRC / "svgSanitize.ts", d / "svg.mjs")
            (d / "payloads.json").write_text(json.dumps(SVG_PAYLOADS))
            script = DOM_POLYFILL + (
                "import { readFileSync } from 'node:fs';\n"
                "import { pathToFileURL } from 'node:url';\n"
                "const [, , mod, file] = process.argv;\n"
                "const { sanitizeSvg } = await import(pathToFileURL(mod).href);\n"
                "const out = {};\n"
                "for (const [k, v] of Object.entries(JSON.parse(readFileSync(file, 'utf8')))) {\n"
                "  try { sanitizeSvg(v, k, 'scope'); out[k] = 'ok'; } catch (e) { out[k] = String(e.message); }\n"
                "}\n"
                "console.log(JSON.stringify(out));\n"
            )
            r = run_node(script, str(d / "svg.mjs"), str(d / "payloads.json"), cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            ts = json.loads(r.stdout)
            for name, text in SVG_PAYLOADS.items():
                f = d / "x.svg"
                f.write_text(text)
                py = bm.svg_problems(f)
                with self.subTest(name):
                    self.assertEqual(ts[name] == "ok", not py, f"TS: {ts[name][:300]}\nPython: {py}")
            # The payloads cover both outcomes, and the review payloads are refused.
            self.assertEqual(ts["mermaid style"], "ok")
            for name in ("escaped url", "escaped import", "global div rule"):
                self.assertNotEqual(ts[name], "ok")

    def test_python_refusal_reasons(self):
        with tempfile.TemporaryDirectory(prefix="w9-svg-") as d:
            f = Path(d) / "x.svg"
            f.write_text(SVG_PAYLOADS["global div rule"])
            self.assertTrue(any("non-SVG elements (div)" in p for p in bm.svg_problems(f)))
            f.write_text(SVG_PAYLOADS["escaped import"])
            self.assertTrue(any("CSS escape" in p for p in bm.svg_problems(f)))


class SvgSanitizePython(unittest.TestCase):
    """Runs without node: the Python side alone on the key payloads."""

    def problems(self, name: str) -> list[str]:
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x.svg"
            f.write_text(SVG_PAYLOADS[name])
            return bm.svg_problems(f)

    def test_review_payloads_refused_and_mermaid_accepted(self):
        for name in ("escaped url", "escaped import", "global div rule", "font-face", "image-set", "image element"):
            self.assertTrue(self.problems(name), name)
        for name in ("mermaid style", "local url ref", "comment in style", "use local href"):
            self.assertEqual(self.problems(name), [], name)

    def test_anchor_image_keeps_the_regex_scan(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "icon.svg"
            f.write_text(SVG_PAYLOADS["image element"])
            self.assertEqual(bm.svg_problems(f, markup=False), [], "an <Img> source is not inserted as markup")


# ------------------------------------------------------------------------------------- B06

RING_WORLD = {
    "layout": "ring", "ring": {"positions": 8, "r": 150},
    "nodes": [
        {"id": "k0", "label": "0", "pos": 0, "role": "item", "x": 864, "y": 206, "revealAtMs": 500},
        {"id": "k3", "label": "3", "pos": 3, "role": "item", "x": 970, "y": 462, "revealAtMs": 500},
        {"id": "A", "label": "A", "pos": 3, "role": "owner", "ringOffset": 92, "x": 1035, "y": 527, "revealAtMs": 1500},
        {"id": "B", "label": "B", "sublabel": "server", "pos": 7, "role": "owner", "x": 692, "y": 184},
        {"id": "far", "label": "Owner rule", "sublabel": "walks clockwise", "x": 200, "y": 356, "revealAtMs": 2000},
        {"id": "mid", "label": "hash(k)", "value": "17", "x": 864, "y": 356, "revealAtMs": 2500},
    ],
    "edges": [{"id": "e1", "from": "k0", "to": "A", "label": "owns", "revealAtMs": 3000}],
}

FIXTURE_WORLD = {
    "video": {"fps": 30}, "world": RING_WORLD,
    "scenes": [
        {"id": "s01", "type": "title", "startMs": 0, "endMs": 4000,
         "props": {"kicker": "Episode 1", "title": "Hashing", "subtitle": "rings", "question": "What moves?", "questionAtMs": 2000}},
        {"id": "s02", "type": "world", "startMs": 4000, "endMs": 12000, "props": {"steps": [
            {"atMs": 4200, "reveal": ["B"], "note": "a second owner"},
            {"atMs": 5000, "set": {"mid": {"value": "42", "label": "hash(key)"}}, "tint": {"warn": ["k0"]}},
            {"atMs": 6000, "hide": ["far", "e1"], "note": "owner rule hidden"},
            {"atMs": 7000, "hide": ["k3"], "reveal": ["k3"]},
            {"set": {"A": {"label": "A*"}}},
            {"note": "untimed note"},
            {"atMs": 9000, "tint": {}, "focus": ["A"]},
        ]}},
        {"id": "s03", "type": "world", "startMs": 12000, "endMs": 16000, "props": {"steps": [
            {"atMs": 12500, "reveal": ["far"], "set": {"mid": {"value": "7"}}},
            {"atMs": 14000, "hide": ["B"], "note": "B leaves"},
        ]}},
        {"id": "s04", "type": "custom", "startMs": 16000, "endMs": 22000, "props": {
            "component": "RingLoad", "caption": "keys per owner", "count": 12, "ratio": 0.5, "durationMs": 300,
            "owners": [{"id": "A", "label": "A", "load": 3.0}, {"id": "B", "label": "B", "atMs": 18000}],
            "answer": "B takes 3", "answerAtMs": 20000,
            "worldSteps": [{"atMs": 17000, "reveal": ["B"], "note": "B returns"}, {"note": "custom untimed"}]}},
        {"id": "s05", "type": "recap", "startMs": 22000, "endMs": 26000, "props": {"points": [
            {"text": "one ring", "atMs": 22500}, {"text": "owners clockwise"}, {"text": "few keys move", "atMs": 25000},
            {"text": "virtual nodes"}, {"text": "fifth point never shows"}]}},
        {"id": "s06", "type": "equation", "startMs": 26000, "endMs": 30000, "props": {"title": "Load", "lines": [
            {"tex": "K/N", "note": "keys per node", "atMs": 26500}, {"text": "1/N moves"}, {"tex": "x", "atMs": 29000}]}},
    ],
    "overlays": [{"id": "c1", "type": "chip", "startMs": 3000, "endMs": 6000, "props": {"text": "ring"}},
                 {"id": "c2", "type": "chip", "startMs": 20000, "endMs": 21000, "props": {"text": "load"}}],
}

LOCAL_WORLD = {"nodes": [{"id": "x", "label": "server X", "x": 100, "y": 100},
                         {"id": "y", "label": "server Y", "value": "3", "x": 300, "y": 100, "revealAtMs": 999999}],
               "edges": [{"id": "xy", "from": "x", "to": "y", "label": "copies"}]}

FIXTURE_COMPARE = {
    "video": {"fps": 30}, "world": RING_WORLD,
    "scenes": [
        {"id": "c1", "type": "compare", "startMs": 0, "endMs": 14000, "props": {
            "title": "Mod vs ring",
            "left": {"title": "hash mod N", "tag": "naive", "kind": "table", "columns": ["0", "1", "2", "3"],
                     "rows": [{"id": "m2", "label": "mod 2", "cells": ["A", "B", "A", "B"]},
                              {"id": "m3", "label": "mod 3", "cells": ["A", "B", "C", "A"], "atMs": 2000},
                              {"id": "plain", "label": "keys", "cells": ["k0", "k1", "k2", "k3"]},
                              {"id": "late", "label": "late row", "cells": ["1", "2", "3", "4"], "atMs": 9000}],
                     "steps": [{"atMs": 1000, "fill": {"m2": "all", "m3": []}},
                               {"atMs": 3000, "fill": {"m3": [0, 2]}, "stat": {"text": "moved: 2 of 4", "persist": True}, "marks": {"m3": [1]}},
                               {"fill": {"m3": "all"}, "title": "mod, untimed"},
                               {"atMs": 6000, "stat": "", "tag": ""},
                               {"atMs": 8000, "title": "mod, fixed N", "tag": "fixed", "stat": "moved: 0"}]},
            "right": {"title": "notes", "kind": "text",
                      "lines": [{"text": "ring line", "atMs": 2500}, {"text": "always there"}, {"text": "late line", "atMs": 12000}],
                      "steps": [{"atMs": 4000, "tag": "ring"}]},
            "verdict": {"text": "Ring wins", "winner": "right", "atMs": 4000},
            "banners": [{"text": "2 points: 2 neighbours", "labels": {"left": "moves 9", "right": "moves 3"}, "atMs": 7000, "persist": True},
                        {"text": "no cue, never shown"},
                        {"text": "", "winner": "left", "atMs": 10000, "persist": True},
                        {"text": "final", "winner": "none", "labels": {"right": ""}, "atMs": 12500}]}},
        {"id": "c2", "type": "compare", "startMs": 14000, "endMs": 24000, "props": {
            "left": {"title": "shared ring", "kind": "world", "world": "shared",
                     "steps": [{"atMs": 15000, "set": {"mid": {"value": "99"}}, "note": "shared note", "stat": "99 now"},
                               {"atMs": 17000, "hide": ["A"]}]},
            "right": {"title": "own world", "tag": "local", "kind": "world", "world": LOCAL_WORLD,
                      "steps": [{"atMs": 16000, "hide": ["x"], "note": "X gone"}, {"reveal": ["y"]},
                                {"atMs": 21000, "set": {"y": {"label": "server Y2", "value": "4"}}}]}}},
        {"id": "k1", "type": "check", "startMs": 24000, "endMs": 30000, "props": {
            "question": "Which keys move?", "options": ["all", "a few"], "answer": "a few", "answerAtMs": 27000}},
        {"id": "code1", "type": "code", "startMs": 30000, "endMs": 36000, "props": {
            "title": "ring.py", "filename": "ring.py", "language": "python",
            "code": "def owner(k):\n    h = hash(k)\n\n    return ring.next(h)\nprint(owner(1))\n\n\n",
            "steps": [{"atMs": 31000, "lines": "1-2"}, {"lines": [4]}, {"atMs": 34000, "lines": "5"}]}},
    ],
    "overlays": [],
}

FIXTURE_DIAGRAM = {
    "video": {"fps": 30}, "world": None,
    "scenes": [
        {"id": "d1", "type": "diagram", "startMs": 0, "endMs": 10000, "props": {
            "title": "Pipeline",
            "elements": [{"id": "a", "kind": "rect", "x": 0, "y": 0, "w": 10, "h": 10},
                         {"id": "at", "kind": "text", "text": "input", "x": 5, "y": 5},
                         {"id": "bt", "kind": "text", "text": "hash"},
                         {"id": "ct", "kind": "text", "text": "owner"},
                         {"id": "dt", "kind": "text", "text": "always"}],
            "steps": [{"atMs": 3000, "reveal": ["bt"]}, {"atMs": 1000, "reveal": ["at", "bt"]}, {"reveal": ["ct"]},
                      {"atMs": 6000, "highlight": ["ct"]}]}},
        {"id": "d2", "type": "diagram", "startMs": 10000, "endMs": 14000, "props": {"title": "From a file", "svg": "diagrams/x.svg"}},
        {"id": "k2", "type": "check", "startMs": 14000, "endMs": 18000, "props": {"question": "Explain the ring aloud."}},
        {"id": "t2", "type": "title", "startMs": 18000, "endMs": 22000, "props": {"title": "Next", "question": "Why rings?"}},
        {"id": "k3", "type": "check", "startMs": 22000, "endMs": 26000, "props": {"question": "Q", "correct": 1, "answer": "never cued"}},
    ],
    "overlays": [{"id": "o1", "type": "chip", "startMs": 500, "endMs": 1500, "props": {"text": "chip one"}}],
}


def sample_times(m: dict) -> list[int]:
    end = max(sc["endMs"] for sc in m["scenes"])
    times = set(range(0, end, 47))
    vals: list = []
    pc._ms_values(m, vals)
    for v in vals:
        for d in (-134, -101, -100, -99, -67, -34, -17, -1, 0, 1, 16, 17, 33):
            if 0 <= v + d < end:
                times.add(int(v + d))
    for sc in m["scenes"]:
        f0 = round(sc["startMs"] * 30 / 1000)
        for k in range(0, 400, 3):
            times.add(round((f0 + k) * 1000 / 30))
    return sorted(t for t in times if t < end)


@unittest.skipUnless(HAVE_BUNDLER, "set PE_REMOTION_DIR to a Remotion project with node_modules (esbuild) to run the parity tests")
class VisibleTextParity(unittest.TestCase):
    """B06: pe_common.visible_texts_at == visibleText.ts visibleTextsAt at many times."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="w9-vt-"))
        bundle(SRC / "visibleText.ts", cls.tmp / "vt.mjs")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ts_texts(self, m: dict, times: list[int]) -> list[list]:
        (self.tmp / "m.json").write_text(json.dumps(m))
        (self.tmp / "t.json").write_text(json.dumps(times))
        script = (
            "import { readFileSync } from 'node:fs';\n"
            "import { pathToFileURL } from 'node:url';\n"
            "const [, , mod, file, tfile] = process.argv;\n"
            "const { visibleTextsAt } = await import(pathToFileURL(mod).href);\n"
            "const m = JSON.parse(readFileSync(file, 'utf8'));\n"
            "const ts = JSON.parse(readFileSync(tfile, 'utf8'));\n"
            "console.log(JSON.stringify(ts.map((t) => visibleTextsAt(m, t) .map((x) => (x === undefined ? null : x)))));\n"
        )
        r = run_node(script, str(self.tmp / "vt.mjs"), str(self.tmp / "m.json"), str(self.tmp / "t.json"), cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return json.loads(r.stdout)

    def check_parity(self, m: dict) -> None:
        times = sample_times(m)
        ts = self.ts_texts(m, times)
        bad = []
        for t, want in zip(times, ts):
            got = pc.visible_texts_at(m, t)
            if norm(got) != norm(want):
                bad.append((t, norm(want), norm(got)))
        self.assertEqual(bad[:3], [], f"{len(bad)} of {len(times)} sample times differ")

    def test_world_custom_recap_equation_title(self):
        self.check_parity(FIXTURE_WORLD)

    def test_compare_banners_fill_panel_steps_check_code(self):
        self.check_parity(FIXTURE_COMPARE)

    def test_diagram_title_fallbacks_check_cards(self):
        self.check_parity(FIXTURE_DIAGRAM)

    def test_template_samples(self):
        for slug in ("sample", "sample-ring"):
            with self.subTest(slug):
                self.check_parity(json.loads((TEMPLATE / "public" / "episodes" / slug / "episode.json").read_text()))


class VisibleTextRules(unittest.TestCase):
    """Runs without node: spot checks of the rules on the shared fixtures."""

    def at(self, m: dict, t: int) -> list[str]:
        return norm(pc.visible_texts_at(m, t))

    def test_hide_set_and_lead(self):
        m = FIXTURE_WORLD
        self.assertIn("Owner rule", self.at(m, 5800))
        self.assertIn("Owner rule", self.at(m, 5899), "a hide lands 100 ms (3 frames) early: still visible here")
        self.assertNotIn("Owner rule", self.at(m, 5901))
        self.assertIn("42", self.at(m, 4950), "a set lands 3 frames early")
        self.assertNotIn("17", self.at(m, 5500))
        self.assertIn("hash(key)", self.at(m, 5500))

    def test_banners_one_list_latest_wins(self):
        m = FIXTURE_COMPARE
        self.assertNotIn("Ring wins", self.at(m, 3960), "a result never shows before its word (frame 119)")
        self.assertIn("Ring wins", self.at(m, 4000))
        self.assertIn("wrong", self.at(m, 4000))
        at8 = self.at(m, 8000)
        self.assertNotIn("Ring wins", at8)
        self.assertIn("moves 9", at8)
        at11 = self.at(m, 11000)
        self.assertNotIn("2 points: 2 neighbours", at11)
        self.assertIn("right", at11, "text '' shows no banner, but its winner labels still count")
        self.assertNotIn("no cue, never shown", " ".join(self.at(m, 13000)))

    def test_fill_and_panel_steps(self):
        m = FIXTURE_COMPARE
        at2 = self.at(m, 2100)
        self.assertIn("?", at2)
        self.assertNotIn("C", at2)
        self.assertIn("k2", at2, "a row no fill names shows at once")
        self.assertIn("mod, untimed", self.at(m, 4600), "untimed step 2 fires at frame 15 + 90")
        at7 = self.at(m, 7000)
        self.assertNotIn("moved: 2 of 4", at7, "stat '' clears")
        self.assertNotIn("naive", at7, "tag '' hides")
        self.assertIn("mod, fixed N", self.at(m, 8100))

    def test_visible_text_window_union(self):
        text = pc.visible_text(FIXTURE_COMPARE, 3500, 4100)
        self.assertIn("Ring wins", text)
        self.assertIn("moved: 2 of 4", text)
        self.assertNotIn("Ring wins", pc.visible_text(FIXTURE_COMPARE, 3000, 3960))

    def test_labels_expire_at_the_next_step_without_persist(self):
        # W11b/W11a: a stat or banner ends at the panel's next step unless persist (stale-label rule).
        m = json.loads(json.dumps(FIXTURE_COMPARE))
        left = m["scenes"][0]["props"]["left"]
        for st in left["steps"]:
            if isinstance(st.get("stat"), dict):
                st["stat"] = st["stat"]["text"]
        self.assertNotIn("moved: 2 of 4", pc.visible_text(m, 3500, 4100))
        self.assertIn("moved: 2 of 4", pc.visible_text(FIXTURE_COMPARE, 3500, 4100))

    def test_parity_list_names_the_typescript(self):
        src = (SCRIPTS / "pe_common.py").read_text()
        for name in ("visibleTextsAt", "sceneTextsAt", "panelStateAt", "bannerAt", "visibilityAt", "worldTextsAt"):
            self.assertIn(name, src)


# ------------------------------------------------------------------------------------- text.minsize

class TextSize(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w9-text-"))
        self.ws = self.tmp / "ws"
        self.ep = self.ws / "demo"
        (self.ep / "diagrams").mkdir(parents=True)
        self.rem = self.ws / "remotion"
        cdir = self.rem / "src" / "scenes" / "custom"
        cdir.mkdir(parents=True)
        shutil.copy(SRC / "theme.ts", self.rem / "src" / "theme.ts")
        (cdir / "index.ts").write_text('import { Small } from "./Small";\nimport { Fine } from "./Fine";\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_check(self, scenes: list[dict]) -> dict:
        (self.ep / "episode.json").write_text(json.dumps({"scenes": scenes, "turns": [], "overlays": []}))
        ep = qc.Episode(mock.Mock(workspace=str(self.ws), slug="demo", mp4=None, remotion_dir=None))
        return qc.text_size(ep)[0]

    def test_custom_component_literals(self):
        cdir = self.rem / "src" / "scenes" / "custom"
        (cdir / "Small.tsx").write_text('export const Small = () => (\n  <div style={{ fontSize: 22, color: "red" }}>\n'
                                        '    <span style={{ fontSize: type.label }}>ok</span>\n    <text fontSize={type.min - 6}>x</text>\n  </div>);\n')
        (cdir / "Fine.tsx").write_text("export const Fine = () => <div style={{ fontSize: type.body + 4 }}><b style={{fontSize: Math.max(type.min, s)}}>y</b></div>;\n")
        c = self.run_check([{"id": "s1", "type": "custom", "props": {"component": "Small"}},
                            {"id": "s2", "type": "custom", "props": {"component": "Fine"}}])
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("Small.tsx:2", c["detail"])
        self.assertIn("Small.tsx:4", c["detail"])
        self.assertNotIn("Fine.tsx", c["detail"])

    def test_computed_size_warns(self):
        (self.rem / "src" / "scenes" / "custom" / "Fine.tsx").write_text("export const Fine = ({s}) => <div style={{ fontSize: s * 2 }}>y</div>;\n")
        c = self.run_check([{"id": "s2", "type": "custom", "props": {"component": "Fine"}}])
        self.assertEqual(c["status"], "warn", c)

    def test_svg_scaled_to_the_stage(self):
        # viewBox 3456 wide: the stage halves it, so font-size 40 renders at 20 px (fail) and 60 at 30 px (pass).
        (self.ep / "diagrams" / "wide.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3456 600">\n<text font-size="40">a</text>\n'
            "<style>.big { font-size: 60px }</style></svg>")
        (self.ep / "diagrams" / "ok.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 864 300"><text style="font-size:16px">a</text></svg>')
        c = self.run_check([{"id": "d1", "type": "diagram", "props": {"title": "Wide", "svg": "diagrams/wide.svg"}}])
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("wide.svg:2", c["detail"])
        self.assertIn("20.0 px", c["detail"])
        c = self.run_check([{"id": "d2", "type": "diagram", "props": {"svg": "diagrams/ok.svg"}}])
        self.assertEqual(c["status"], "pass", c)  # 16 x 2 = 32 px

    def test_svg_relative_or_default_size_warns(self):
        (self.ep / "diagrams" / "rel.svg").write_text('<svg viewBox="0 0 1728 600"><text font-size="0.8em">a</text></svg>')
        (self.ep / "diagrams" / "none.svg").write_text('<svg viewBox="0 0 1728 600"><text>a</text></svg>')
        self.assertEqual(self.run_check([{"id": "d", "type": "diagram", "props": {"svg": "diagrams/rel.svg"}}])["status"], "warn")
        self.assertEqual(self.run_check([{"id": "d", "type": "diagram", "props": {"svg": "diagrams/none.svg"}}])["status"], "warn")

    def test_no_custom_or_svg_passes_and_names_what_it_read(self):
        # W10: text.minsize never skips; with nothing to compute it passes and says what it read.
        c = self.run_check([{"id": "t", "type": "title", "props": {"title": "x"}}])
        self.assertEqual(c["status"], "pass")
        self.assertIn("1 scene(s) (title)", c["detail"])

    def test_coverage_runs_it_and_the_template_components_pass(self):
        self.assertIn("text_size(ep)", (SCRIPTS / "qc.py").read_text())
        t = qc._theme_type(TEMPLATE)
        for f in (SRC / "scenes" / "custom").glob("*.tsx"):
            self.assertEqual(qc.custom_font_problems(f, t)[0], [], f.name)


if __name__ == "__main__":
    unittest.main()
