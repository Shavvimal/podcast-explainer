"""Tests for scripts/export_delivery.py (W13a): a complete, portable copy of one delivered episode.

    python3 -m unittest tests.test_w13a_export -v

Builds a tiny fake workspace (no render, no network).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "podcast-explainer-video"
sys.path.insert(0, str(SKILL / "scripts"))

import export_delivery as ex  # noqa: E402


def _tmpdir(prefix: str) -> Path:
    try:
        return Path(tempfile.mkdtemp(prefix=prefix))
    except (FileNotFoundError, OSError):  # no usable TMPDIR: fall back to a folder next to the tests
        base = SKILL / "tests" / ".tmp"
        base.mkdir(exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make_workspace(root: Path, slug: str = "demo", hero_exists: bool = True) -> Path:
    ws = root / "my explainers"
    ep = ws / slug
    for d in ("out", "learn", "qc/judge", "qc/restate", "qc/stills", "audio/cache"):
        (ep / d).mkdir(parents=True, exist_ok=True)
    mp4 = ep / "out" / "episode.mp4"
    mp4.write_bytes(b"\x00\x01fake-mp4")
    uri = mp4.resolve().as_uri()
    (ep / "out" / "episode.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    (ep / "transcript.md").write_text(f"---\nmp4: \"{mp4.resolve()}\"\n---\n\nVideo: {uri}\n\n[00:12]({uri}#t=12) Nia: hi\n")
    (ep / "out" / "transcript.md").write_text((ep / "transcript.md").read_text())
    (ep / "captions.vtt").write_text("WEBVTT\n")
    (ep / "script.json").write_text('{"id": "demo"}\n')
    (ep / "audio" / "episode.wav").write_bytes(b"RIFFwav")
    (ep / "audio" / "turn-t01.wav").write_bytes(b"RIFFturn")
    (ep / "audio" / "cache" / "x.wav").write_bytes(b"RIFFcache")
    (ep / "learn" / "selftest.md").write_text(f"# Self-test\n\n1. Answer. Rewatch: {uri}#t=5\n")
    hero = (ep / "qc" / "hero.png").resolve()
    if hero_exists:
        (ep / "qc" / "hero.png").write_bytes(b"\x89PNG")
    (ep / "learn" / "summary.md").write_text(f"# Summary\n\n![Mechanism]({hero.as_uri()})\n\nSee [the cards](cards.md).\n")
    (ep / "learn" / "cards.md").write_text("# Cards\n")
    (ep / "learn" / "cards.csv").write_text("Q\tA [demo 00:05]\texplainer::demo seg01\n")
    (ep / "qc" / "report.json").write_text(json.dumps({"mp4": str(mp4.resolve()), "remotion": str((ws / "remotion" / "x").resolve())}))
    (ep / "qc" / "listen.json").write_text("{}\n")
    (ep / "qc" / "judge" / "reply.md").write_text("judge says ok\n")
    lib = ws / "library"
    (lib / "learn" / slug).mkdir(parents=True)
    (lib / "learn" / slug / "selftest.md").write_text((ep / "learn" / "selftest.md").read_text())
    (lib / f"{slug}.md").write_text((ep / "transcript.md").read_text())
    (lib / "index.json").write_text(json.dumps({"version": 1, "episodes": [
        {"slug": "other", "mp4": "/elsewhere/other.mp4"},
        {"slug": slug, "mp4": str(mp4.resolve()), "learn": {"dir": str((ep / "learn").resolve())}}]}))
    files = {"transcript.md": f"{slug}/transcript.md", "captions.vtt": f"{slug}/captions.vtt",
             "library": f"library/{slug}.md", "sidecar.srt": f"{slug}/out/episode.srt"}
    (ep / "delivery.json").write_text(json.dumps({"files": {k: {"path": v, "sha256": sha(ws / v)} for k, v in files.items()}}))
    return ws


def run(argv) -> tuple[int, str, str]:
    o, e = io.StringIO(), io.StringIO()
    with redirect_stdout(o), redirect_stderr(e):
        code = ex.main(argv)
    return code, o.getvalue(), e.getvalue()


class ExportDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmpdir("w13a-export-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ws = make_workspace(self.tmp)
        self.out = self.tmp / "example out"

    def export(self, *extra):
        return run(["--workspace", str(self.ws), "--slug", "demo", "--to", str(self.out), *extra])

    def test_complete_portable_copy(self):
        code, out, err = self.export()
        self.assertEqual(code, 0, out + err)
        rec = json.loads((self.out / "export.json").read_text())
        for rel in ("out/episode.mp4", "transcript.md", "delivery.json", "learn/selftest.md", "qc/listen.json",
                    "qc/judge/reply.md", "audio/episode.wav", "library/demo.md", "library/learn/demo/selftest.md",
                    "library/index.json", "script.json"):
            self.assertIn(rel, rec["files"], rel)
            self.assertTrue((self.out / rel).is_file(), rel)
        self.assertFalse((self.out / "audio" / "turn-t01.wav").exists())
        self.assertFalse((self.out / "audio" / "cache").exists())
        self.assertIn("qc/scores.json", rec["missing"])

    def test_links_become_relative_and_resolve(self):
        code, out, err = self.export()
        self.assertEqual(code, 0, out + err)
        ws_abs = str(self.ws.resolve())
        for p in self.out.rglob("*"):
            if p.is_file() and p.suffix in (".md", ".csv") and p.name != "export.json":
                self.assertNotIn(ws_abs, p.read_text(), p)
                self.assertNotIn("file://", p.read_text(), p)
        self.assertIn("Rewatch: ../out/episode.mp4#t=5", (self.out / "learn" / "selftest.md").read_text())
        self.assertIn("![Mechanism](../qc/hero.png)", (self.out / "learn" / "summary.md").read_text())
        self.assertIn('mp4: "out/episode.mp4"', (self.out / "transcript.md").read_text())
        self.assertIn("(../out/episode.mp4#t=12)", (self.out / "library" / "demo.md").read_text())
        self.assertIn("../../../out/episode.mp4#t=5", (self.out / "library" / "learn" / "demo" / "selftest.md").read_text())

    def test_digests(self):
        self.export()
        rec = json.loads((self.out / "export.json").read_text())
        for rel, r in rec["files"].items():
            self.assertEqual(sha(self.out / rel), r["sha256"], rel)
            if not r["rewritten"]:
                self.assertEqual(r["sha256"], r["sourceSha256"], rel)
        self.assertTrue(rec["files"]["transcript.md"]["rewritten"])
        self.assertEqual(rec["files"]["out/episode.mp4"]["sha256"], sha(self.ws / "demo" / "out" / "episode.mp4"))
        self.assertEqual(rec["deliveryProblems"], [])

    def test_one_record_index(self):
        self.export()
        idx = json.loads((self.out / "library" / "index.json").read_text())
        self.assertEqual([r["slug"] for r in idx["episodes"]], ["demo"])
        self.assertEqual(idx["episodes"][0]["mp4"], "out/episode.mp4")
        self.assertEqual(idx["episodes"][0]["learn"]["dir"], "learn")

    def test_external_paths_stay_absolute_and_are_listed(self):
        self.export()
        rec = json.loads((self.out / "export.json").read_text())
        self.assertTrue(any("remotion" in e for e in rec["external"]), rec["external"])
        rep = json.loads((self.out / "qc" / "report.json").read_text())
        self.assertEqual(rep["mp4"], "out/episode.mp4")

    def test_broken_link_fails_unless_allowed(self):
        (self.ws / "demo" / "qc" / "hero.png").unlink()
        code, out, _ = self.export()
        self.assertEqual(code, 1)
        self.assertIn("BROKEN LINK: learn/summary.md: ../qc/hero.png", out)
        rec = json.loads((self.out / "export.json").read_text())
        self.assertEqual(rec["brokenLinks"], ["learn/summary.md: ../qc/hero.png"])
        code, out, _ = self.export("--force", "--allow-broken-links")
        self.assertEqual(code, 0, out)

    def test_placeholder_path_is_a_mention_not_a_broken_link(self):
        pattern = (self.ws / "demo" / "qc" / "contact-sheet-NN.png").resolve()
        (self.ws / "demo" / "qc" / "report.md").write_text(f"| stills | PASS | 3 page(s) {pattern} |\n")
        code, out, _ = self.export()
        self.assertEqual(code, 0, out)
        rec = json.loads((self.out / "export.json").read_text())
        self.assertEqual(rec["brokenLinks"], [])
        self.assertEqual(rec["unresolvedMentions"], ["qc/report.md: contact-sheet-NN.png"])

    def test_refuses_non_empty_dir_without_force(self):
        self.out.mkdir()
        (self.out / "README.md").write_text("keep me\n")
        code, _, err = self.export()
        self.assertEqual(code, 1)
        self.assertIn("not empty", err)
        code, out, err = self.export("--force")
        self.assertEqual(code, 0, out + err)
        self.assertEqual((self.out / "README.md").read_text(), "keep me\n")
        # a re-export with --force removes only the files the previous export listed
        (self.ws / "demo" / "qc" / "judge" / "reply.md").unlink()
        code, out, err = self.export("--force")
        self.assertEqual(code, 0, out + err)
        self.assertFalse((self.out / "qc" / "judge" / "reply.md").exists())
        self.assertTrue((self.out / "README.md").exists())

    def test_force_refuses_to_overwrite_unlisted_file(self):
        (self.out / "learn").mkdir(parents=True)
        (self.out / "learn" / "selftest.md").write_text("hand-made\n")
        code, _, err = self.export("--force")
        self.assertEqual(code, 1)
        self.assertIn("would overwrite", err)

    def test_missing_required_file_is_an_error(self):
        (self.ws / "demo" / "delivery.json").unlink()
        code, _, err = self.export()
        self.assertEqual(code, 1)
        self.assertIn("delivery.json", err)

    def test_stale_source_against_delivery_json_fails(self):
        (self.ws / "demo" / "captions.vtt").write_text("WEBVTT\n\nedited\n")
        code, out, _ = self.export()
        self.assertEqual(code, 1)
        self.assertIn("captions.vtt", out)

    def test_symlink_in_source_is_refused(self):
        os.symlink(self.ws / "demo" / "script.json", self.ws / "demo" / "qc" / "link.json")
        code, _, err = self.export()
        self.assertEqual(code, 1)
        self.assertIn("symbolic link", err)

    def test_bad_slug(self):
        code, _, err = run(["--workspace", str(self.ws), "--slug", "../x", "--to", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn("invalid slug", err)


if __name__ == "__main__":
    unittest.main()
