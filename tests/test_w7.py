"""Tests for the W7 renderer pieces: ring layout, compare scene, shared world, check-card variants,
caption flicker and reading rate, SVG sanitiser. Run from the skill folder:

    python3 -m unittest            (or: python3 -m unittest discover -s tests -v)

Python-only tests use the standard library. The renderer tests need a Remotion project with
node_modules: set PE_REMOTION_DIR to one (for example explainers/remotion after `npm install`).
Without it they are skipped, and the skip message says so. They copy templates/remotion/src into a
temporary project that links that node_modules, run `npx tsc --noEmit`, and render one still per
new scene type with `npx remotion still` (about 10 s each on an M-series Mac).
"""
from __future__ import annotations

import copy
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
SCRIPTS = SKILL / "scripts"
TEMPLATE = SKILL / "templates" / "remotion"
RING_INPUTS = TEMPLATE / "sample-inputs" / "ring"
sys.path.insert(0, str(SCRIPTS))

import build_manifest as bm  # noqa: E402
import qc  # noqa: E402


def run_build(ws: Path, slug: str, *extra: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    argv = sys.argv
    sys.argv = ["build_manifest.py", "--workspace", str(ws), "--slug", slug, "--placeholder-timing", "--no-sync", *extra]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = bm.main()
            except SystemExit as e:
                rc = e.code
    finally:
        sys.argv = argv
    return rc, out.getvalue() + err.getvalue()


class RingSampleBuild(unittest.TestCase):
    """The ring sample (ring world, custom scene with worldSteps, compare scene) builds and
    resolves ring positions, shared steps and panel cues."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w7-ring-"))
        (self.tmp / "sample-ring").mkdir()
        for f in ("script.json", "scenes.json"):
            shutil.copy(RING_INPUTS / f, self.tmp / "sample-ring" / f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scenes(self) -> dict:
        return json.loads((self.tmp / "sample-ring" / "scenes.json").read_text())

    def write_scenes(self, doc: dict) -> None:
        (self.tmp / "sample-ring" / "scenes.json").write_text(json.dumps(doc))

    def test_builds_and_places_ring_nodes(self):
        rc, log = run_build(self.tmp, "sample-ring")
        self.assertEqual(rc, 0, log)
        ep = json.loads((self.tmp / "sample-ring" / "episode.json").read_text())
        world = ep["world"]
        nodes = {n["id"]: n for n in world["nodes"]}
        cx, cy, r = 1728 / 2, 712 / 2, world["ring"]["r"]
        # pos 0 is 12 o'clock, pos 2 of 8 is 3 o'clock; owners sit ringOffset further out.
        self.assertAlmostEqual(nodes["k0"]["x"], cx, places=1)
        self.assertAlmostEqual(nodes["k0"]["y"], cy - r, places=1)
        self.assertAlmostEqual(nodes["k2"]["x"], cx + r, places=1)
        a = math.radians(3 * 360 / 8)
        self.assertAlmostEqual(nodes["A"]["x"], cx + (r + 92) * math.sin(a), places=1)
        self.assertIn("ownershipAtMs", world["ring"])
        types = [s["type"] for s in ep["scenes"]]
        self.assertEqual(types, ["world", "custom", "compare"])

    def test_shared_steps_from_custom_scene_set_reveal_time(self):
        rc, log = run_build(self.tmp, "sample-ring")
        self.assertEqual(rc, 0, log)
        ep = json.loads((self.tmp / "sample-ring" / "episode.json").read_text())
        custom = next(s for s in ep["scenes"] if s["type"] == "custom")
        c = next(n for n in ep["world"]["nodes"] if n["id"] == "C")
        # C is revealed only by the custom scene's worldSteps, so its reveal time comes from there.
        self.assertEqual(c["revealAtMs"], custom["props"]["worldSteps"][0]["atMs"])

    def test_compare_cues_resolve(self):
        rc, log = run_build(self.tmp, "sample-ring")
        self.assertEqual(rc, 0, log)
        ep = json.loads((self.tmp / "sample-ring" / "episode.json").read_text())
        cmp_ = next(s for s in ep["scenes"] if s["type"] == "compare")
        self.assertIn("atMs", cmp_["props"]["verdict"])
        self.assertTrue(all("atMs" in st for st in cmp_["props"]["left"]["steps"]))
        self.assertTrue(all("atMs" in r for r in cmp_["props"]["left"]["rows"]))

    def test_walk_on_owner_is_an_error(self):
        doc = self.scenes()
        doc["scenes"][0]["props"]["steps"][3]["walk"] = ["A"]
        self.write_scenes(doc)
        rc, log = run_build(self.tmp, "sample-ring")
        self.assertEqual(rc, 1)
        self.assertIn("not an item node on a ring", log)

    def test_fill_unknown_row_is_an_error(self):
        doc = self.scenes()
        doc["scenes"][2]["props"]["left"]["steps"][0]["fill"]["nope"] = [0]
        self.write_scenes(doc)
        rc, log = run_build(self.tmp, "sample-ring")
        self.assertEqual(rc, 1)
        self.assertIn("fill names unknown row 'nope'", log)

    def test_world_panel_needs_world(self):
        doc = self.scenes()
        del doc["scenes"][2]["props"]["right"]["world"]
        self.write_scenes(doc)
        rc, log = run_build(self.tmp, "sample-ring")
        self.assertEqual(rc, 1)
        self.assertIn("world", log)

    def test_pos_without_ring_layout_is_an_error(self):
        doc = self.scenes()
        del doc["world"]["layout"]
        self.write_scenes(doc)
        rc, log = run_build(self.tmp, "sample-ring")
        self.assertEqual(rc, 1)
        self.assertIn("needs x and y", log)

    def test_partial_world_camera_is_accepted(self):
        doc = self.scenes()
        doc["world"]["camera"] = {"zoom": 1.2}  # A03: merged with the default centre
        self.write_scenes(doc)
        rc, log = run_build(self.tmp, "sample-ring")
        self.assertEqual(rc, 0, log)
        ep = json.loads((self.tmp / "sample-ring" / "episode.json").read_text())
        self.assertTrue(qc.world_node_boxes(ep))


class SchemaRules(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((SKILL / "schemas" / "scenes.schema.json").read_text())

    def errors(self, doc):
        return bm._mini_validate(doc, self.schema)

    def check_doc(self, props):
        return {"version": 1, "scenes": [{"id": "s1", "type": "check", "anchor": {"from": {"turn": "t01"}}, "props": props}]}

    def test_answer_needs_answer_at(self):
        self.assertTrue(self.errors(self.check_doc({"question": "Why?", "answer": "Because."})))
        self.assertFalse(self.errors(self.check_doc({"question": "Why?", "answer": "Because.", "answerAt": {"turn": "t02"}})))

    def test_self_test_card_needs_no_answer(self):
        self.assertFalse(self.errors(self.check_doc({"question": "Explain it aloud."})))

    def test_correct_needs_answer_at(self):
        self.assertTrue(self.errors(self.check_doc({"question": "Q?", "options": ["a", "b"], "correct": 1})))

    def test_punctuation_only_anchor_word_fails(self):
        doc = self.check_doc({"question": "Q?"})
        doc["scenes"][0]["anchor"]["from"]["word"] = "?!"
        self.assertTrue(self.errors(doc))

    def test_ring_sample_validates(self):
        self.assertEqual(self.errors(json.loads((RING_INPUTS / "scenes.json").read_text())), [])

    def test_hash_map_sample_validates(self):
        self.assertEqual(self.errors(json.loads((TEMPLATE / "sample-inputs" / "scenes.json").read_text())), [])

    def test_evals_sample_validates(self):
        self.assertEqual(self.errors(json.loads((SKILL / "evals" / "files" / "sample-scenes.json").read_text())), [])


def words(text: str, start: int, per: int = 250, gap: int = 0) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "startMs": t, "endMs": t + per - gap, "source": "asr"})
        t += per
    return out


class Captions(unittest.TestCase):
    """qc.py caption_pages (Python port of captionPages.ts): flicker hold and reading rate."""

    def test_short_blank_between_turns_is_held(self):
        t1 = {"id": "t01", "speaker": "host", "startMs": 0, "endMs": 2000, "words": words("One two three four five six seven eight.", 0)}
        # next turn starts 2100 ms: the page would end at 2000 + 300 hold, capped at 2100; a 1-120 ms blank must not remain
        t2 = {"id": "t02", "speaker": "guest", "startMs": 2120, "endMs": 4000, "words": words("Nine ten eleven twelve thirteen.", 2120)}
        pages = qc.caption_pages([t1, t2], "karaoke", 17, 700)
        gaps = [b["startMs"] - a["endMs"] for a, b in zip(pages, pages[1:])]
        self.assertTrue(all(g <= 0 or g >= qc.HOLD_GAP_MS for g in gaps), gaps)

    def test_fast_page_starts_early_into_silence(self):
        t1 = {"id": "t01", "speaker": "host", "startMs": 0, "endMs": 1000, "words": words("Okay then.", 0, per=400)}
        # a 20-character question spoken in 0.6 s after 1.5 s of silence
        t2 = {"id": "t02", "speaker": "guest", "startMs": 2500, "endMs": 3100, "words": words("Do they have a name?", 2500, per=120)}
        t3 = {"id": "t03", "speaker": "host", "startMs": 3300, "endMs": 5000, "words": words("Virtual nodes, yes indeed.", 3300)}
        pages = qc.caption_pages([t1, t2, t3], "karaoke", 17, 700)
        q = next(p for p in pages if p["turn"] == "t02")
        self.assertLess(q["startMs"], 2500)
        self.assertLessEqual(q["chars"] / (q["endMs"] - q["startMs"]) * 1000, 21)

    def test_boundary_rebalance_lowers_peak(self):
        # A long first sentence, then a short fast question with no pause before it.
        ws = words("And those extra points, the ones that look like separate servers on the ring.", 0, per=330)
        last = ws[-1]["endMs"]
        ws += words("Do they have a name?", last, per=110)
        t = {"id": "t01", "speaker": "host", "startMs": 0, "endMs": ws[-1]["endMs"], "words": ws}
        t2 = {"id": "t02", "speaker": "guest", "startMs": ws[-1]["endMs"] + 250, "endMs": ws[-1]["endMs"] + 2000,
              "words": words("Virtual nodes.", ws[-1]["endMs"] + 250, per=600)}
        pages = qc.caption_pages([t, t2], "karaoke", 17, 700)
        peak = max(p["chars"] / (p["endMs"] - p["startMs"]) * 1000 for p in pages)
        self.assertLessEqual(peak, 21)

    def test_typescript_builder_matches_python(self):
        # N05: both builders take manifest.holds; the second fixture has a hold the early start must respect.
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        sample = json.loads((TEMPLATE / "public" / "episodes" / "sample" / "episode.json").read_text())
        q = {"id": "t01", "speaker": "host", "startMs": 0, "endMs": 1000, "words": words("Which algorithm is it?", 0, per=250)}
        a = {"id": "t02", "speaker": "guest", "startMs": 8250, "endMs": 9000, "words": words("The algorithm is consistent hashing.", 8250, per=150)}
        n = {"id": "t03", "speaker": "host", "startMs": 9200, "endMs": 10500, "words": words("Right, the ring.", 9200, per=400)}
        held = {"turns": [q, a, n], "holds": [{"startMs": 1000, "endMs": 8000}],
                "captions": {"mode": "karaoke", "maxCharsPerSecond": 17, "minPageMs": 700}}
        sample_held = copy.deepcopy(sample)
        mid = sample_held["turns"][3]
        sample_held["holds"] = [{"startMs": sample_held["turns"][2]["endMs"], "endMs": mid["words"][0]["startMs"]}]
        harness = (
            "import { readFileSync } from 'node:fs';\n"
            "import { pathToFileURL } from 'node:url';\n"
            "const [, , mod, ep] = process.argv;\n"
            "const { buildCaptionPages } = await import(pathToFileURL(mod).href);\n"
            "const m = JSON.parse(readFileSync(ep, 'utf8'));\n"
            "const pages = buildCaptionPages(m.turns, m.captions.mode, m.captions.maxCharsPerSecond, m.captions.minPageMs, m.holds ?? []);\n"
            "console.log(JSON.stringify(pages.map((p) => [p.turnId, p.startMs, p.endMs, p.words.map((w) => w.text).join(' ')])));\n"
        )
        for name, m in (("sample", sample), ("sample with hold", sample_held), ("hold fixture", held)):
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                h = Path(d) / "h.mjs"
                h.write_text(harness)
                f = Path(d) / "episode.json"
                f.write_text(json.dumps(m))
                r = subprocess.run([node, str(h), str(TEMPLATE / "src" / "components" / "captionPages.ts"), str(f)],
                                   capture_output=True, text=True, timeout=60)
                if r.returncode != 0 and "Unknown file extension" in r.stderr:
                    self.skipTest("this node cannot strip TypeScript types")
                self.assertEqual(r.returncode, 0, r.stderr)
                ts = json.loads(r.stdout)
                py = [[p["turn"], p["startMs"], p["endMs"], p["text"]] for p in
                      qc.caption_pages(m["turns"], m["captions"]["mode"], m["captions"]["maxCharsPerSecond"],
                                       m["captions"]["minPageMs"], m.get("holds", []))]
                self.assertEqual(ts, py)
        # The hold changed the answer page (control: without it the page starts early).
        with_hold = qc.caption_pages(held["turns"], "karaoke", 17, 700, held["holds"])
        without = qc.caption_pages(held["turns"], "karaoke", 17, 700)
        self.assertGreaterEqual(min(p["startMs"] for p in with_hold if p["turn"] == "t02"), 8000)
        self.assertLess(min(p["startMs"] for p in without if p["turn"] == "t02"), 8000)


# ------------------------------------------------------------------------------------- renderer

REMOTION = os.environ.get("PE_REMOTION_DIR")


@unittest.skipUnless(REMOTION and (Path(REMOTION) / "node_modules" / "remotion").is_dir(),
                     "set PE_REMOTION_DIR to a Remotion project with node_modules to run the renderer tests")
class Renderer(unittest.TestCase):
    proj: Path

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="w7-remotion-"))
        cls.proj = cls.tmp / "remotion"
        shutil.copytree(TEMPLATE, cls.proj, ignore=shutil.ignore_patterns("node_modules", "out"))
        (cls.proj / "node_modules").symlink_to(Path(REMOTION).resolve() / "node_modules")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def npx(self, *args, timeout=300):
        return subprocess.run(["npx", *args], cwd=self.proj, capture_output=True, text=True, timeout=timeout)

    def still(self, slug: str, frame: int) -> subprocess.CompletedProcess:
        out = self.tmp / f"{slug}-{frame}.png"
        r = self.npx("remotion", "still", "Episode", str(out), f"--props={json.dumps({'slug': slug})}", f"--frame={frame}")
        if r.returncode == 0:
            self.assertTrue(out.is_file() and out.stat().st_size > 10_000, r.stdout[-500:])
        return r

    def episode(self, slug: str, mutate) -> None:
        src = json.loads((self.proj / "public" / "episodes" / "sample-ring" / "episode.json").read_text())
        ep = mutate(copy.deepcopy(src))
        d = self.proj / "public" / "episodes" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "episode.json").write_text(json.dumps(ep))

    def test_typecheck(self):
        r = self.npx("tsc", "--noEmit")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_hash_map_sample_still(self):
        # The original sample (free layout world, BucketFill, check card with an answer) still renders.
        for frame in (300, 700):
            r = self.still("sample", frame)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_ring_world_still(self):
        r = self.still("sample-ring", 310)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_custom_shared_world_still(self):
        r = self.still("sample-ring", 570)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_compare_still(self):
        r = self.still("sample-ring", 900)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_check_card_self_test_still(self):
        def mutate(ep):
            ep["scenes"] = [{"id": "c1", "type": "check", "startMs": 0, "endMs": ep["audio"]["durationMs"],
                             "props": {"question": "Explain aloud why only one arc moves."}}]
            return ep
        self.episode("w7-check", mutate)
        r = self.still("w7-check", 60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def svg_episode(self, slug: str, svg: str) -> None:
        def mutate(ep):
            ep["scenes"] = [{"id": "d1", "type": "diagram", "startMs": 0, "endMs": ep["audio"]["durationMs"],
                             "props": {"title": "SVG", "svg": "diagrams/x.svg"}}]
            return ep
        self.episode(slug, mutate)
        d = self.proj / "public" / "episodes" / slug / "diagrams"
        d.mkdir(exist_ok=True)
        (d / "x.svg").write_text(svg)

    def test_safe_svg_renders(self):
        self.svg_episode("w7-svg-ok", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
                         '<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
                         '<rect id="r" x="10" y="10" width="80" height="50" fill="url(#g)"/><text x="100" y="50">ok</text></svg>')
        r = self.still("w7-svg-ok", 30)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_unsafe_svg_fails_loudly(self):
        self.svg_episode("w7-svg-bad", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
                         '<image href="https://attacker.example/x.png" width="10" height="10"/>'
                         '<rect x="1" y="1" width="5" height="5" onclick="alert(1)"/></svg>')
        r = self.still("w7-svg-bad", 30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not safe to insert", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
