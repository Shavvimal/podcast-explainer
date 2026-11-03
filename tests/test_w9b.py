"""W9 integrator tests: the general-rule regex is case-insensitive on its words, a predict hold on
the expert's core question satisfies E35, tts.py falls back to the role's default voice, and a
compare table's `cellTint` outlines the named cells (renderer state, bundled with esbuild).

    PE_REMOTION_DIR=<remotion project with node_modules> python3 -m unittest tests.test_w9b -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
sys.path.insert(0, str(SKILL / "scripts"))

import tts  # noqa: E402
import validate_script as vs  # noqa: E402

REMOTION = os.environ.get("PE_REMOTION_DIR")
ESBUILD = Path(REMOTION).resolve() / "node_modules" / ".bin" / "esbuild" if REMOTION else None
HAVE_BUNDLER = bool(shutil.which("node") and ESBUILD and ESBUILD.is_file())


def script(turns: list[dict]) -> dict:
    return {"version": 1, "id": "x", "title": "x", "targetMinutes": 1,
            "speakers": [{"id": "host", "name": "Nia", "voice": "Sulafat", "color": "#4F8CFF", "side": "left", "role": "learner"},
                         {"id": "guest", "name": "Theo", "voice": "Iapetus", "color": "#FFB020", "side": "right", "role": "expert"}],
            "segments": [{"id": "seg01", "role": "example", "learningGoal": "g", "visualPlan": "v", "turns": turns}]}


def codes(data: dict, outline: dict) -> set[str]:
    rep = vs.Report("x")
    vs.check_script(data, None, 1, 45, "per-turn", rep, None, outline)
    return {i["code"] for i in rep.items}


class GeneralRule(unittest.TestCase):
    def test_sentence_initial_words_match(self):
        for text in ("In general, a leaving server hands its stretch to one neighbour.",
                     "On average a new server takes its share.", "a new server takes about K over N keys"):
            self.assertTrue(vs.GENERAL_RE.search(text), text)

    def test_lowercase_variables_do_not_match(self):
        self.assertIsNone(vs.GENERAL_RE.search("so 3 in a row is fine"))


class CoreHold(unittest.TestCase):
    OUTLINE = {"segments": [{"id": "seg01", "coreSegment": True}]}

    def turns(self, hold_on_expert: bool) -> list[dict]:
        q = {"id": "t02", "speaker": "guest", "text": "D lands at 9. Which keys hit D first?"}
        if hold_on_expert:
            q.update(holdAfterMs=7000, pause={"kind": "predict", "prompt": "Which keys change owner?"})
        return [{"id": "t01", "speaker": "host", "text": "Where does D go, and how does a key know?"}, q,
                {"id": "t03", "speaker": "host", "text": "Keys 7 and 8 walk to D now."},
                {"id": "t04", "speaker": "host", "text": "Is that luck, or always so?"},
                {"id": "t05", "speaker": "guest", "text": "Always: the stretch belonged to one server."}]

    def test_expert_posed_predict_hold_satisfies_e35(self):
        self.assertNotIn("E35", codes(script(self.turns(True)), self.OUTLINE))

    def test_no_hold_still_fails_e35(self):
        self.assertIn("E35", codes(script(self.turns(False)), self.OUTLINE))


class DefaultVoices(unittest.TestCase):
    def test_role_default_when_voice_missing(self):
        self.assertEqual(tts.DEFAULT_VOICES, {"learner": "Sulafat", "expert": "Iapetus"})
        data = script([{"id": "t01", "speaker": "host", "text": "Hello there."}])
        for sp in data["speakers"]:
            del sp["voice"]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "script.json").write_text(json.dumps(data))
            s = tts.load_script(Path(d))
        self.assertEqual({sp["id"]: sp["voice"] for sp in s["speakers"]}, {"host": "Sulafat", "guest": "Iapetus"})

    def test_samples_use_the_default_pair(self):
        for rel in ("evals/files/sample-script.json", "templates/remotion/sample-inputs/script.json",
                    "templates/remotion/sample-inputs/ring/script.json"):
            sp = {s["role"]: s for s in json.loads((SKILL / rel).read_text())["speakers"]}
            self.assertEqual((sp["learner"]["voice"], sp["expert"]["voice"]), ("Sulafat", "Iapetus"), rel)
            self.assertEqual((sp["learner"]["name"], sp["expert"]["name"]), ("Nia", "Theo"), rel)


@unittest.skipUnless(HAVE_BUNDLER, "set PE_REMOTION_DIR to a Remotion project with node_modules (esbuild)")
class CellTint(unittest.TestCase):
    HARNESS = (
        "import { pathToFileURL } from 'node:url';\n"
        "const [, , mod] = process.argv;\n"
        "const { panelStateAt } = await import(pathToFileURL(mod).href);\n"
        "const panel = { title: 'mod', kind: 'table', columns: ['0','1','2','3'],\n"
        "  rows: [{ id: 'm4', label: 'mod 4', cells: ['A','B','C','D'] }],\n"
        "  steps: [{ atMs: 1000, marks: { m4: [1, 3] } },\n"
        "          { atMs: 2000, cellTint: { warn: { m4: [3] }, text: { m4: [1] } } },\n"
        "          { atMs: 3000, cellTint: {} }] };\n"
        "const at = (ms) => { const r = panelStateAt(panel, 0, 30, Math.round(ms * 30 / 1000)).rows[0];\n"
        "  return { marked: [...r.marked].sort(), tinted: Object.fromEntries(r.tinted) }; };\n"
        "console.log(JSON.stringify([at(1500), at(2500), at(3500)]));\n"
    )

    def test_cell_tint_is_inherited_and_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "cs.mjs"
            r = subprocess.run([str(ESBUILD), str(SKILL / "templates/remotion/src/scenes/compareState.ts"), "--bundle",
                                "--format=esm", "--platform=node", f"--outfile={out}", "--log-level=warning"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            h = Path(d) / "h.mjs"
            h.write_text(self.HARNESS)
            r = subprocess.run(["node", str(h), str(out)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
        before, during, after = json.loads(r.stdout)
        self.assertEqual(before, {"marked": [1, 3], "tinted": {}})
        self.assertEqual(during["tinted"], {"3": "warn", "1": "text"})
        self.assertEqual(after["tinted"], {})


if __name__ == "__main__":
    unittest.main()
