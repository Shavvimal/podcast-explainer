"""W14a: Python port of the W13b mark-expiry rules (worldState.ts resolveSteps, changeVisible,
worldMarksAt; visibleText.ts marksAt) and of the node part of labelSourcesAt, plus the qc.py
marks.focus check and the per-still marks in qc/stills/index.json.

Run from the skill folder:

    python3 -m unittest tests.test_w14a -v
    PE_REMOTION_DIR=explainers/remotion python3 -m unittest tests.test_w14a -v   # with the parity tests

The parity tests bundle templates/remotion/src/visibleText.ts with the esbuild in PE_REMOTION_DIR
and compare marksAt and labelSourcesAt (node sources) with the Python port at many times.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_w9 import HAVE_BUNDLER, SRC, TEMPLATE, bundle, run_node  # noqa: E402

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
sys.path.insert(0, str(SKILL / "scripts"))
import pe_common as pc  # noqa: E402
import qc  # noqa: E402

# A ring of 12 positions: owners A (3), B (7), C (11), D (5, joins later); items k1, k4, k9, k10.
# Virtual points A1, A2 of server A (virtualOf). Turns give the walk arrows their turn ends.
RING = {
    "layout": "ring", "ring": {"positions": 12, "r": 220},
    "nodes": [
        {"id": "k1", "label": "1", "pos": 1, "role": "item"},
        {"id": "k4", "label": "4", "pos": 4, "role": "item"},
        {"id": "k9", "label": "9", "pos": 9, "role": "item"},
        {"id": "k10", "label": "10", "pos": 10, "role": "item"},
        {"id": "A", "label": "A", "pos": 3, "role": "owner"},
        {"id": "B", "label": "B", "pos": 7, "role": "owner"},
        {"id": "C", "label": "C", "pos": 11, "role": "owner"},
        {"id": "D", "label": "D", "pos": 5, "role": "owner", "revealAtMs": 999999},
        {"id": "A1", "label": "A", "virtualOf": "A", "pos": 2, "role": "owner", "revealAtMs": 999999},
        {"id": "A2", "label": "A", "virtualOf": "A", "pos": 8, "role": "owner", "revealAtMs": 999999},
        {"id": "rule", "label": "Owner rule", "sublabel": "walk clockwise", "value": "3 servers", "x": 120, "y": 120},
        {"id": "load", "label": "Keys per server", "x": 120, "y": 600, "revealAtMs": 999999},
    ],
    "edges": [],
}

TURNS = [
    {"id": "t01", "speaker": "host", "segment": "s1", "text": "Key 1 goes to A.", "startMs": 0, "endMs": 2600,
     "words": [{"text": "Key", "startMs": 0, "endMs": 300}, {"text": "1", "startMs": 300, "endMs": 600},
               {"text": "goes", "startMs": 600, "endMs": 900}, {"text": "to", "startMs": 900, "endMs": 1100},
               {"text": "A.", "startMs": 1100, "endMs": 1500}]},
    {"id": "t02", "speaker": "guest", "segment": "s1", "text": "Now B and C.", "startMs": 2850, "endMs": 6000, "holdAfterMs": 2000,
     "words": [{"text": "Now", "startMs": 2850, "endMs": 3100}, {"text": "B", "startMs": 3100, "endMs": 3400},
               {"text": "and", "startMs": 3400, "endMs": 3600}, {"text": "C.", "startMs": 3600, "endMs": 4000}]},
    {"id": "t03", "speaker": "host", "segment": "s1", "text": "D joins.", "startMs": 8250, "endMs": 12000},
    {"id": "t04", "speaker": "guest", "segment": "s1", "text": "Points.", "startMs": 12250, "endMs": 20000},
]

STEPS = [
    {"atMs": 500, "at": {"turn": "t01"}, "focus": ["k1", "A"], "walk": ["k1"], "arcs": [{"from": 11, "to": 3, "color": "accent"}]},
    {"atMs": 1200, "at": {"turn": "t01", "word": "A."}, "tint": {"warn": ["k4"]}},
    {"atMs": 3000, "at": {"turn": "t02"}, "focus": ["B"], "persist": ["focus", "walk"], "walk": ["k4"],
     "set": {"rule": {"value": "B owns 4"}}},
    {"atMs": 5000, "at": {"turn": "t02", "word": "C."}, "arcs": [{"from": 7, "to": 11}], "persist": True},
    {"atMs": 6500, "freeze": True, "note": "predict"},
    {"atMs": 8500, "at": {"turn": "t03"}, "reveal": ["D", "load"]},
    {"atMs": 9500, "at": {"turn": "t03"}, "freeze": False},
    {"atMs": 10500, "at": {"turn": "t03"}, "focus": []},
    {"atMs": 12500, "at": {"turn": "t04"}, "hide": ["A"], "reveal": ["A1", "A2"], "persist": ["change"],
     "set": {"rule": {"label": "Owner rule 2", "value": "4 servers", "persist": True}}},
    {"atMs": 14000, "at": {"turn": "t04"}, "focusEdges": [], "speaksOf": ["A1"]},
    {"atMs": 16000, "at": {"turn": "t04"}, "arcs": []},
]


def manifest(steps=None, turns=None) -> dict:
    return {
        "video": {"fps": 30}, "world": copy.deepcopy(RING), "turns": copy.deepcopy(turns if turns is not None else TURNS),
        "scenes": [
            {"id": "w1", "type": "world", "startMs": 0, "endMs": 11000, "props": {"steps": copy.deepcopy(STEPS[:8] if steps is None else steps[:8])}},
            {"id": "w2", "type": "world", "startMs": 11000, "endMs": 20000, "props": {"steps": copy.deepcopy(STEPS[8:] if steps is None else steps[8:])}},
        ],
        "overlays": [],
    }


def marks(m: dict, t: float) -> dict:
    return pc.marks_at(m, t)


class ResolveSteps(unittest.TestCase):
    """The W13b rules, without node."""

    def setUp(self):
        self.m = manifest()

    def test_timeline_carries_turn_end_plus_hold(self):
        tl = pc.world_timeline(self.m)
        self.assertEqual(pc.turn_ends(self.m)["t02"], 8000)
        self.assertEqual(tl[2]["turnEndMs"], 8000)
        self.assertNotIn("turnEndMs", tl[4], "a step without at.turn has no turn end")

    def test_focus_and_arcs_end_at_the_next_step(self):
        self.assertEqual(sorted(marks(self.m, 600)["focus"]), ["A", "k1"])
        mk = marks(self.m, 1300)
        self.assertEqual(mk["focus"], [], "focus without persist ends at the next step")
        self.assertEqual(mk["arcs"], [], "arcs without persist end at the next step")
        self.assertEqual(mk["tint"], {"k4": "warn"})
        self.assertEqual(marks(self.m, 3100)["tint"], {}, "tint ends at the next step")

    def test_persist_list_keeps_focus_until_a_later_step_sets_it(self):
        for t in (3100, 5100, 7000, 9000):
            self.assertEqual(marks(self.m, t)["focus"], ["B"], t)
        self.assertEqual(marks(self.m, 10600)["focus"], [], "[] always clears")

    def test_walk_arrow_ends_at_turn_end_but_lasts_1500_ms(self):
        # k1's walk at 500: next step at 1200, turn end 2600; the arrow lasts until max(2600, 2000) but the
        # next step (1200) resolves a new step without walk, so it ends at 1200.
        self.assertEqual(marks(self.m, 700)["walks"], [{"item": "k1", "target": "A"}])
        self.assertEqual(marks(self.m, 1300)["walks"], [])
        # k4's walk persists: it stays through later steps until a later step walks.
        self.assertEqual(marks(self.m, 12000)["walks"], [{"item": "k4", "target": "B"}])

    def test_walk_until_uses_turn_end_and_min(self):
        tl = pc.world_timeline(manifest([{"atMs": 500, "at": {"turn": "t01"}, "walk": ["k1"]}]))
        r = pc.resolve_steps(tl, RING)[0]
        self.assertEqual(r["walkUntil"], 2600)
        tl = pc.world_timeline(manifest([{"atMs": 2000, "at": {"turn": "t01"}, "walk": ["k1"]}]))
        self.assertEqual(pc.resolve_steps(tl, RING)[0]["walkUntil"], 3500, "at least WALK_MIN_MS after the step")
        tl = pc.world_timeline(manifest([{"atMs": 2000, "walk": ["k1"]}]))
        self.assertEqual(pc.resolve_steps(tl, RING)[0]["walkUntil"], float("inf"), "no anchor turn: until the next step")
        only = manifest([{"atMs": 500, "at": {"turn": "t01"}, "walk": ["k1"]}])
        self.assertEqual(marks(only, 2500)["walks"], [{"item": "k1", "target": "A"}])
        self.assertEqual(marks(only, 2700)["walks"], [], "the arrow ends at the turn end")

    def test_persist_true_keeps_arcs(self):
        self.assertEqual(marks(self.m, 5100)["arcs"], [{"from": 7, "to": 11}])
        self.assertEqual(marks(self.m, 15000)["arcs"], [{"from": 7, "to": 11}])
        self.assertEqual(marks(self.m, 16100)["arcs"], [])

    def test_change_band_after_freeze_until_next_step(self):
        # D revealed inside the freeze: the change shows at the freeze end (9500) until the next step (10500).
        mk = marks(self.m, 9600)
        self.assertIsNotNone(mk["change"])
        self.assertEqual(mk["change"]["moved"], ["k4"])
        self.assertIsNone(marks(self.m, 9000)["change"], "frozen: no change yet")
        # The arcs set at 5000 persist (arcsSetAt 5000 < changedAt 9500), so they do not hide it.
        self.assertIsNone(marks(self.m, 10600)["change"], "the change band ends at the next step")

    def test_change_persist_and_later_arcs_hide_it(self):
        mk = marks(self.m, 15000)
        self.assertIsNotNone(mk["change"], "persist 'change' keeps the band past the next step")
        self.assertIsNone(marks(self.m, 16100)["change"], "a later step that sets arcs hides it")

    def test_speaks_of_and_camera(self):
        self.assertEqual(marks(self.m, 14100)["speaksOf"], ["A1"])
        r = pc.resolve_steps(pc.world_timeline(self.m), RING)
        self.assertEqual(r[0]["camera"]["zoom"], 1)

    def test_no_world_scene_no_marks(self):
        m = manifest()
        m["scenes"][0]["type"] = "title"
        self.assertIsNone(pc.marks_at(m, 600))
        self.assertIsNotNone(pc.marks_at(m, 12000))

    def test_resolve_focus_matches_resolve_steps(self):
        tl = pc.world_timeline(self.m)
        self.assertEqual([r["focus"] for r in pc.resolve_focus(tl)], [r["focus"] for r in pc.resolve_steps(tl, RING)])


class NodeLabelSources(unittest.TestCase):
    def test_base_label_never_expires_set_value_does(self):
        m = manifest()
        src = {(x["nodeId"], x["source"]): x for x in pc.node_label_sources_at(m, 3500)}
        self.assertFalse(src[("rule", "node-label")]["expires"])
        self.assertFalse(src[("rule", "node-sublabel")]["expires"])
        self.assertEqual(src[("rule", "node-value")]["text"], "B owns 4")
        self.assertTrue(src[("rule", "node-value")]["expires"])
        later = {(x["nodeId"], x["source"]): x for x in pc.node_label_sources_at(m, 13000)}
        self.assertEqual(later[("rule", "node-label")]["text"], "Owner rule 2")
        self.assertTrue(later[("rule", "node-label")]["expires"], "a `set` label is not the base label")
        self.assertFalse(later[("rule", "node-value")]["expires"], "a persist value lasts")
        self.assertEqual(later[("A1", "node-label")]["text"], "A1", "a virtual node reads with its point")
        self.assertEqual(later[("A2", "node-label")]["text"], "A2")


class MarksFocusCheck(unittest.TestCase):
    def ep(self, m: dict):
        class E:
            manifest = m

            def need_manifest(self):
                return m
        return E()

    def test_warns_when_the_spotlight_dims_the_named_server(self):
        steps = copy.deepcopy(STEPS)
        steps[0]["focus"] = ["k1"]  # the walk ends at A, which the focus dims; t01 names A too
        c = qc.marks_focus(self.ep(manifest(steps)))[0]
        self.assertEqual(c["status"], "warn")
        self.assertIn("walk names A", c["detail"])

    def test_passes_and_names_persisted_kinds(self):
        steps = copy.deepcopy(STEPS)
        steps[2]["focus"] = ["B", "k4"]
        steps[2]["speaksOf"] = ["C"]
        c = qc.marks_focus(self.ep(manifest(steps)))[0]
        self.assertEqual(c["status"], "pass", c["detail"])
        self.assertIn("persisted kinds: arcs, change", c["detail"])

    def test_still_plan_records_marks(self):
        src = (SKILL / "scripts" / "qc.py").read_text()
        self.assertIn('p["marks"]', src)
        self.assertIn("out += marks_focus(ep)", src)


def sample_times(m: dict) -> list[int]:
    end = max(sc["endMs"] for sc in m["scenes"])
    times = set(range(0, end, 97))
    vals = []
    for st in pc.world_timeline(m):
        vals += [st["t"]] + ([st["turnEndMs"]] if "turnEndMs" in st else [])
    for t in m.get("turns") or []:
        vals += [t["endMs"], t["endMs"] + (t.get("holdAfterMs") or 0)]
    for v in vals:
        for d in (-101, -1, 0, 1, 99, 1499, 1500, 1501):
            if 0 <= v + d < end:
                times.add(int(v + d))
    return sorted(times)


def canon(mk):
    if mk is None:
        return None
    return {"focus": sorted(mk["focus"]), "focusEdges": sorted(mk["focusEdges"]), "speaksOf": sorted(mk["speaksOf"]),
            "arcs": mk["arcs"], "tint": dict(sorted(mk["tint"].items())), "walks": mk["walks"],
            "change": None if mk["change"] is None else {"moved": sorted(mk["change"]["moved"]),
                                                         "arcs": [{k: round(v, 6) for k, v in a.items()} for a in mk["change"]["arcs"]]}}


@unittest.skipUnless(HAVE_BUNDLER, "set PE_REMOTION_DIR to a Remotion project with node_modules (esbuild) to run the parity tests")
class MarksParity(unittest.TestCase):
    """pe_common.marks_at == visibleText.ts marksAt, and node_label_sources_at == the node sources of
    labelSourcesAt, at many sample times."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="w14a-marks-"))
        bundle(SRC / "visibleText.ts", cls.tmp / "vt.mjs")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ts(self, m: dict, times: list[int]) -> list:
        (self.tmp / "m.json").write_text(json.dumps(m))
        (self.tmp / "t.json").write_text(json.dumps(times))
        script = (
            "import { readFileSync } from 'node:fs';\n"
            "import { pathToFileURL } from 'node:url';\n"
            "const [, , mod, file, tfile] = process.argv;\n"
            "const { marksAt, labelSourcesAt } = await import(pathToFileURL(mod).href);\n"
            "const m = JSON.parse(readFileSync(file, 'utf8'));\n"
            "const ts = JSON.parse(readFileSync(tfile, 'utf8'));\n"
            "console.log(JSON.stringify(ts.map((t) => [marksAt(m, t), labelSourcesAt(m, t).filter((x) => x.source.startsWith('node-'))])));\n"
        )
        r = run_node(script, str(self.tmp / "vt.mjs"), str(self.tmp / "m.json"), str(self.tmp / "t.json"), cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return json.loads(r.stdout)

    def check(self, m: dict) -> None:
        times = sample_times(m)
        bad = []
        for t, (want_marks, want_src) in zip(times, self.ts(m, times)):
            got = canon(pc.marks_at(m, t))
            if got != canon(want_marks):
                bad.append(("marks", t, canon(want_marks), got))
            key = lambda x: (x.get("sceneId") or "", x.get("nodeId") or "", x["source"], x.get("side") or "")
            g_src = sorted(({k: v for k, v in x.items()} for x in pc.node_label_sources_at(m, t)), key=key)
            w_src = sorted(want_src, key=key)
            if g_src != w_src:
                bad.append(("labels", t, w_src[:3], g_src[:3]))
        self.assertEqual(bad[:3], [], f"{len(bad)} of {2 * len(times)} samples differ")

    def test_ring_fixture_with_persist_walks_freeze_virtual_points(self):
        self.check(manifest())

    def test_template_samples(self):
        for slug in ("sample", "sample-ring"):
            with self.subTest(slug):
                self.check(json.loads((TEMPLATE / "public" / "episodes" / slug / "episode.json").read_text()))


class W49Scope(unittest.TestCase):
    """W14a: W49 skips questions, named-case sentences and same-input determinism statements."""

    def test_exemptions_and_real_warnings(self):
        import validate_script as vs
        quiet = ["Is that luck, or always like that?", "Key 4 still walks to 5, then 6. It never gets as far as D.",
                 "Exactly. Its walk never crosses D.", "That is a hash function: the same name always gives the same number."]
        loud = ["Two names on one spot always get rehashed.", "A new server always takes a quarter.",
                "Servers always get the same load.", "Is it fair? It never is."]
        for t in quiet:
            self.assertIsNone(vs.unscoped_absolute(t), t)
        for t in loud:
            self.assertIsNotNone(vs.unscoped_absolute(t), t)


if __name__ == "__main__":
    unittest.main()
