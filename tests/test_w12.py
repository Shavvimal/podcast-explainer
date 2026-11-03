"""Tests for the W12 fixes (consistent-hashing v6, 3 Nov 2026): whisper warm-up before paid TTS
(preflight.py --warm-whisper, align.mjs --warm) and the 15 s explain-back hold range. Run from the
skill folder:

    python3 -m unittest tests.test_w12 -v

No network, no Gemini call. The align.mjs tests need node; the warm test that builds whisper.cpp is
not run here (it needs make and a download); the error paths are.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import preflight  # noqa: E402
import validate_script as vs  # noqa: E402
from tests.test_w8 import sample_script  # noqa: E402

NODE = shutil.which("node")


class WarmWhisper(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w12-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_missing_cache_is_a_warning_with_the_warm_fix(self):
        t = preflight.Table()
        ws = self.tmp / "explainers"
        preflight.check_whisper(t, ws, warm=False, cache_dir=self.tmp / "cache")
        row = t.rows[-1]
        self.assertEqual(row["check"], "whisper ready")
        self.assertEqual(row["status"], "WARN")
        self.assertFalse(row["required"])
        self.assertIn("--warm", row["fix"])
        self.assertIn("--cache-dir", row["fix"])
        self.assertFalse(t.failed)

    def test_ready_cache_passes(self):
        wp = self.tmp / "cache" / f"whisper.cpp-{preflight.WHISPER_VERSION}"
        wp.mkdir(parents=True)
        (wp / "main").write_text("")
        (wp / f"ggml-{preflight.WHISPER_MODEL}.bin").write_text("")
        t = preflight.Table()
        preflight.check_whisper(t, self.tmp / "explainers", warm=False, cache_dir=self.tmp / "cache")
        self.assertEqual(t.rows[-1]["status"], "PASS")

    def test_warm_without_the_package_fails(self):
        t = preflight.Table()
        preflight.check_whisper(t, self.tmp / "explainers", warm=True, cache_dir=self.tmp / "cache")
        self.assertEqual(t.rows[-1]["status"], "FAIL")
        self.assertTrue(t.failed)
        self.assertIn("npm install", t.rows[-1]["fix"])

    def test_cli_flag_exists(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            preflight.main(["--help"])
        self.assertIn("--warm-whisper", buf.getvalue())

    @unittest.skipUnless(NODE, "node not installed")
    def test_align_warm_needs_no_slug_and_fails_loudly_without_the_package(self):
        (self.tmp / "explainers" / "remotion").mkdir(parents=True)
        p = subprocess.run([NODE, str(SCRIPTS / "align.mjs"), "--warm", "--workspace", str(self.tmp / "explainers"),
                            "--cache-dir", str(self.tmp / "cache")], cwd=self.tmp, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("--warm", p.stderr)
        self.assertIn("install-whisper-cpp", p.stderr)
        self.assertFalse((self.tmp / "cache").exists())

    @unittest.skipUnless(NODE, "node not installed")
    def test_align_help_lists_warm(self):
        p = subprocess.run([NODE, str(SCRIPTS / "align.mjs"), "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0)
        self.assertIn("--warm", p.stdout)

    def test_skill_md_orders_warm_before_audio(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertIn("--warm-whisper", text)
        self.assertLess(text.index("--warm-whisper"), text.index("**Step 8, real audio.**"))


class ExplainBackHold(unittest.TestCase):
    def _codes(self, kind: str, hold: int) -> list[str]:
        data = sample_script()
        for seg in data["segments"]:
            for t in seg["turns"]:
                if isinstance(t.get("pause"), dict) and t["pause"].get("kind") == "retrieve":
                    t["holdAfterMs"] = hold
                    t["pause"]["kind"] = kind
        rep = vs.Report("script.json")
        vs.check_pauses(data, data["segments"], {}, None, rep)
        return [m["code"] for m in rep.items if m["code"] == "W22" and "hold of" in m["message"]]

    def test_fifteen_second_explain_back_is_clean(self):
        self.assertEqual(self._codes("explain-back", 15000), [])

    def test_sixteen_seconds_warns(self):
        self.assertEqual(self._codes("explain-back", 16000), ["W22"])

    def test_retrieve_keeps_eight_second_cap(self):
        self.assertEqual(self._codes("retrieve", 15000), ["W22"])


if __name__ == "__main__":
    unittest.main()
