"""W10 integrator tests: a diagram step's `hide` removes an element's text from the visible-text
replay (Python port), the scenes schema accepts `hide` and a world of up to 48 nodes, and the
build_manifest gap warning names the video end for the last scene.

    python3 -m unittest tests.test_w10b -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
sys.path.insert(0, str(SKILL / "scripts"))

import pe_common as pc  # noqa: E402


def manifest(steps: list[dict]) -> dict:
    scene = {
        "id": "sc01", "type": "diagram", "startMs": 0, "endMs": 10000,
        "props": {
            "elements": [
                {"id": "even", "kind": "text", "x": 10, "y": 10, "text": "evenly spaced"},
                {"id": "rand", "kind": "text", "x": 10, "y": 60, "text": "random arcs"},
            ],
            "steps": steps,
        },
    }
    return {"video": {"fps": 30, "width": 1920, "height": 1080}, "scenes": [scene], "turns": []}


class DiagramHide(unittest.TestCase):
    def test_hide_drops_text_after_its_cue(self):
        m = manifest([{"atMs": 2000, "reveal": ["rand"], "hide": ["even"]}])
        sc = m["scenes"][0]
        before = pc.scene_texts_at(m, sc, 1000, timeline=[])
        after = pc.scene_texts_at(m, sc, 3000, timeline=[])
        self.assertIn("evenly spaced", before)
        self.assertNotIn("random arcs", before)
        self.assertNotIn("evenly spaced", after)
        self.assertIn("random arcs", after)

    def test_no_hide_keeps_text(self):
        m = manifest([{"atMs": 2000, "reveal": ["rand"]}])
        self.assertIn("evenly spaced", pc.scene_texts_at(m, m["scenes"][0], 3000, timeline=[]))


class Schema(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((SKILL / "schemas" / "scenes.schema.json").read_text())

    def test_diagram_step_has_hide(self):
        steps = self.schema["$defs"]["diagramProps"]["properties"]["steps"]["items"]["properties"]
        self.assertIn("hide", steps)

    def test_world_allows_48_nodes(self):
        text = json.dumps(self.schema)
        self.assertIn('"maxItems": 48', text)


class GapMessage(unittest.TestCase):
    def test_last_scene_gap_names_video_end(self):
        src = (SKILL / "scripts" / "build_manifest.py").read_text()
        self.assertIn("the end of the video (tail pad and video.tailMs)", src)


class DurationRounding(unittest.TestCase):
    """probe.duration compares the mp4 with the composition's whole-frame length (Root.tsx ceil)."""

    def test_frame_rounded_want(self):
        import qc

        class Ep:
            def total_ms(self):
                return 834670  # audio 833170 + tail 1500: 25040.1 frames, so Remotion renders 25041

        src = Path(qc.__file__).read_text()
        self.assertIn("math.ceil(ep.total_ms() / 1000 * 30", src)
        want = round(qc.math.ceil(Ep().total_ms() / 1000 * 30 - 1e-9) * 1000 / 30)
        self.assertEqual(want, 834700)
        self.assertLessEqual(abs(834709 - want), qc.FRAME_MS + 0.1)


if __name__ == "__main__":
    unittest.main()
