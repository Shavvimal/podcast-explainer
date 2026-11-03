#!/usr/bin/env python3
"""qc.py: automated checks on a rendered explainer episode (SKILL.md workflow steps 12 and 14).

Usage:
  python3 qc.py probe    --workspace explainers --slug <slug> [--mp4 PATH]
  python3 qc.py stills   --workspace explainers --slug <slug> [--from-remotion] [--remotion-dir DIR]
  python3 qc.py captions --workspace explainers --slug <slug>
  python3 qc.py coverage --workspace explainers --slug <slug>
  python3 qc.py audio    --workspace explainers --slug <slug>
  python3 qc.py all      --workspace explainers --slug <slug> [--skip-stills] [--final]
  add --json to print the result as JSON

Stills come from the delivered mp4 (ffmpeg) by default, so the judge sees the file the learner gets.
--from-remotion renders them from the source with `npx remotion still` instead (diagnosis only).

Order (SKILL.md steps 11 to 14): render, `qc.py all` to find and fix fails; then learn.json,
learn.py and transcript.py --embed-chapters, so the mp4 is final; then `qc.py all` again, which
writes the evidence and both briefs for THAT mp4; judge and restate; the parent agent writes
qc/scores.json; finally `qc.py all --final`, a read-only verification of the same build.

Build identity: `all` records sha256 digests in qc/report.json `build`: script, scenes, timing,
episode.json, episode.wav, facts, outline, learn.json, the learn/ outputs (not gaplog.md, which
The learner edits), transcript.json, the resolved glossary, and the mp4 (chapters included). `build.id`
names that set. qc/scores.json carries it, and --final fails when the scores belong to another build.

--final is the delivery check: chapters in the mp4; transcript.json and learn/provenance.json
built from the current script.json, timing.json and learn.json (digests, not times); learn/ files
unchanged since learn.py wrote them; a held-out question in learn.json; and a qc/scores.json for
this build with finite scores in range, a reason per score, a recorded restater result, every
rubric line at 8 or more, J1, J5, J7, J11 at 4 or more and no J below 3. The learner's listen note
(qc/listen.json) is checked when present; gate 3 records it.

Inputs: <slug>/episode.json (from build_manifest.py), <slug>/script.json, <slug>/scenes.json,
<slug>/timing.json, <slug>/out/episode.mp4. Outputs go to <slug>/qc/: stills/, contact sheets,
<command>.json, fidelity.json, and for `all` report.json, report.md, judge-brief.md,
restate-brief.md and restate/ (frames list and canonical spoken text for the blind agent).
Exit codes: 0 = no check failed (warnings allowed), 1 = at least one check failed, 2 = bad command line.
Standard library only; needs ffmpeg and ffprobe (npx only with --from-remotion).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402

SKILL = Path(__file__).resolve().parent.parent
REFS = SKILL / "references"
FPS = 30
FRAME_MS = 1000 / FPS
# Targets (references/qc.md section 2): tts.py normalises the mono wav to pc.MONO_LUFS (-19) with a
# true-peak ceiling of pc.MONO_TRUE_PEAK; Remotion's stereo AAC lands near -16 LUFS and adds 1.6 to
# 2.3 dB of true peak.
LUFS_TARGET, LUFS_WARN, LUFS_FAIL = -16.0, 1.0, 2.0
MAX_PART_MS = 12 * 60 * 1000          # a series part is at most 12 minutes of measured audio
CAUSAL_ROLES = {"mechanism", "example", "misconception", "compare", "scale", "transfer"}
LEVEL_WARN_DB = 6.0                   # a turn this far from the median turn level sounds like a jump
RUBRIC_KEYS = ["hook", "concept", "pedagogy", "visual", "readability", "accuracy", "captions", "audio", "pacing", "pauses"]
J_IDS = [f"J{i}" for i in range(1, 12)]          # learning-design.md section 10: J1 to J10, plus J11 (labels)
J_BAR = {"J1": 4, "J5": 4, "J7": 4, "J11": 4}     # every other J needs 3
RUBRIC_BAR = 8
RESTATE_BAR = 4                                  # restater self-score 1 to 5 (qc.md section 5)
REF_RE = re.compile(r"\b\d{1,2}:\d{2}\b|\bt\d{2,3}\b")      # a reason cites a time or a turn id
TP_FAIL = -1.0
BLACK_MIN_S = 0.2
BLACK_PIX_TH = 0.03
DEAD_AIR_S = 1.5
# Captions (references/remotion.md section 5): 19.2 cps peak measured on fast Gemini speech is accepted.
CPS_WARN = 21.0
SHEET720_PER_PAGE = 6                # contact-sheet-720-NN.png: 2 columns x 3 rows of 1280 px frames
FLASH_GAP_MS = (1, 120)
# Geometry at 1920x1080, from templates/remotion/src/theme.ts and the components.
STAGE = (96, 124, 96 + 1728, 124 + 712)          # x0, y0, x1, y1
CAPTION_BOX = (300, 852, 1620, 1026)
BADGE_W, BADGE_H = 180, 92
BADGES = {"left": (96, 852 + (174 - 92 - 44) / 2, 96 + BADGE_W, 852 + (174 - 92 - 44) / 2 + BADGE_H),
          "right": (1824 - BADGE_W, 852 + (174 - 92 - 44) / 2, 1824, 852 + (174 - 92 - 44) / 2 + BADGE_H)}
CHIP_ROW = (1920 - 96 - 1100, 54, 1920 - 96, 54 + 30 * 1.2 + 16)  # one row: 30 px label, 8 px padding
NODE_DEFAULTS = {"box": (280, 120), "pill": (260, 88), "circle": (160, 160)}
RING_DEFAULTS = {"owner": 96, "item": 72}
LIMITS = {"karaoke": dict(minWords=3, maxWords=7, maxChars=46, hardWords=14, hardChars=88),
          "pop": dict(minWords=1, maxWords=3, maxChars=24, hardWords=5, hardChars=32)}
GAP_BREAK_MS, HOLD_AFTER_TURN_MS = 600, 300
TARGET_CPS, MAX_LEAD_MS, HOLD_GAP_MS = 19, 500, 167  # captionPages.ts: rate lead and flicker hold
SENTENCE_END = re.compile(r"[.?!;:][\"')\]]?$")
CLAUSE_END = re.compile(r"[,\u2014-][\"')\]]?$")
NUM_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?!\w)")


class QcError(RuntimeError):
    pass


def mmss(ms: float) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60:02d}:{s % 60:02d}.{int(ms % 1000):03d}"


def check(cid: str, status: str, detail: str, fix: str = "") -> dict:
    return {"id": cid, "status": status, "detail": detail, "fix": fix}


def run(cmd: list[str], cwd: Path | None = None, timeout: float = 1800) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise QcError(f"{cmd[0]} not found on PATH; install it (ffmpeg 7 gives ffmpeg and ffprobe)") from e


class Episode:
    def __init__(self, args):
        self.ws = Path(args.workspace).resolve()
        try:
            self.dir = pc.episode_dir(self.ws, args.slug)
        except pc.BadId as e:
            raise QcError(str(e)) from None
        self.slug = args.slug
        if not self.dir.is_dir():
            raise QcError(f"episode folder {self.dir} not found; check --workspace and --slug")
        self.qc = self.dir / "qc"
        self.mp4 = Path(args.mp4).resolve() if getattr(args, "mp4", None) else self.dir / "out" / "episode.mp4"
        self.remotion = Path(args.remotion_dir).resolve() if getattr(args, "remotion_dir", None) else self.ws / "remotion"
        self.manifest = self._load("episode.json")
        self.script = self._load("script.json")
        self.scenes = self._load("scenes.json")
        self.timing = self._load("timing.json")

    def _load(self, name: str):
        p = self.dir / name
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise QcError(f"{p}: invalid JSON at line {e.lineno}: {e.msg}") from e

    def need_manifest(self) -> dict:
        if self.manifest is None:
            raise QcError(f"{self.dir / 'episode.json'} not found; run build_manifest.py --workspace {self.ws} --slug {self.slug}")
        return self.manifest

    def total_ms(self) -> int:
        m = self.need_manifest()
        return int(m["audio"]["durationMs"]) + int(m["video"].get("tailMs", 1000))

    def holds(self) -> list[dict]:
        return list((self.manifest or {}).get("holds") or [])

    def raw_text(self) -> dict[str, str]:
        out = {}
        for seg in (self.script or {}).get("segments", []):
            for t in seg.get("turns", []):
                out[t.get("id")] = t.get("text", "")
        return out


# ------------------------------------------------------------------------------------------- probe

def probe(ep: Episode) -> list[dict]:
    if not ep.mp4.is_file():
        return [check("probe.file", "fail", f"{ep.mp4} not found",
                      f"render first: cd {shlex.quote(str(ep.remotion))} && npx remotion render Episode {shlex.quote(str(ep.mp4))} --props='{{\"slug\":\"{ep.slug}\"}}'")]
    out: list[dict] = []
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels:format=duration",
             "-of", "json", str(ep.mp4)])
    if r.returncode:
        return [check("probe.file", "fail", f"ffprobe cannot read {ep.mp4}: {r.stderr.strip()[:200]}", "re-render the mp4")]
    info = json.loads(r.stdout)
    vids = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    auds = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    probs = []
    v = vids[0] if vids else {}
    if len(vids) != 1:
        probs.append(f"{len(vids)} video streams")
    if v.get("codec_name") != "h264":
        probs.append(f"video codec {v.get('codec_name')}")
    if (v.get("width"), v.get("height")) != (1920, 1080):
        probs.append(f"size {v.get('width')}x{v.get('height')}")
    if v.get("r_frame_rate") not in ("30/1", "30000/1000"):
        probs.append(f"frame rate {v.get('r_frame_rate')}")
    if len(auds) != 1 or auds[0].get("codec_name") != "aac":
        probs.append(f"audio streams {[a.get('codec_name') for a in auds]} (want exactly one aac)")
    spec = f"h264 {v.get('width')}x{v.get('height')} {v.get('r_frame_rate')}, audio {[a.get('codec_name') for a in auds]}"
    out.append(check("probe.spec", "fail" if probs else "pass", spec + ("; " + "; ".join(probs) if probs else ""),
                     "render with --codec=h264 and the template remotion.config.ts (1920x1080, 30 fps)" if probs else ""))
    dur_ms = float(info.get("format", {}).get("duration", 0)) * 1000
    if ep.manifest:
        # Root.tsx renders ceil((audio + tail) * fps) whole frames, so the mp4 is up to one frame longer
        # than audio + tail; compare with that frame-rounded length (W10: +39 ms failed a correct render).
        want = round(math.ceil(ep.total_ms() / 1000 * 30 - 1e-9) * 1000 / 30)
        delta = dur_ms - want
        out.append(check("probe.duration", "pass" if abs(delta) <= FRAME_MS + 0.1 else "fail",
                         f"mp4 {dur_ms:.0f} ms vs manifest {want} ms (audio + tail), delta {delta:+.0f} ms",
                         "" if abs(delta) <= FRAME_MS + 0.1 else
                         "the mp4 is stale or from another manifest: rerun build_manifest.py, then render again"))
    else:
        out.append(check("probe.duration", "skip", "no episode.json to compare with", "run build_manifest.py"))
    # Loudness: loudnorm measure pass.
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(ep.mp4), "-vn", "-af",
             "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        out.append(check("probe.loudness", "fail", "loudnorm measurement failed", "check that the mp4 has an audio stream"))
    else:
        ln = json.loads(m.group(0))
        lufs, tp = float(ln["input_i"]), float(ln["input_tp"])
        off = abs(lufs - LUFS_TARGET)
        st = "pass" if off <= LUFS_WARN else "warn" if off <= LUFS_FAIL else "fail"
        out.append(check("probe.loudness", st, f"integrated {lufs:.1f} LUFS (target {LUFS_TARGET:.0f} +/- {LUFS_WARN:.0f} LU)",
                         "" if st == "pass" else f"rerun tts.py with the default --lufs {pc.MONO_LUFS:g} (mono wav; the stereo mp4 then lands near -16), then build_manifest.py and render"))
        out.append(check("probe.truepeak", "pass" if tp < TP_FAIL else "fail", f"true peak {tp:.1f} dBTP (must be below {TP_FAIL:.0f})",
                         "" if tp < TP_FAIL else
                         "Remotion's encode raises the true peak 1.6 to 2.3 dB over episode.wav: rerun tts.py with --true-peak "
                         f"about {math.ceil(tp - TP_FAIL + 0.5)} dB below the value it used (default {pc.MONO_TRUE_PEAK}, so try "
                         f"{pc.MONO_TRUE_PEAK - math.ceil(tp - TP_FAIL + 0.5):.1f}), no billing for cached turns, then build_manifest.py and render"))
    # A series part is capped on measured audio, not on its plan (references/depth.md section 5).
    series = (ep.script or {}).get("series")
    if isinstance(series, dict) and ep.manifest:
        aud = int(ep.manifest["audio"]["durationMs"])
        out.append(check("probe.partcap", "pass" if aud <= MAX_PART_MS else "fail",
                         f"series {series.get('id')} part {series.get('part')}: {aud / 60000:.1f} min of audio (cap {MAX_PART_MS // 60000} min)",
                         "" if aud <= MAX_PART_MS else "cut turns or move a segment to the next part, then rerun tts.py"))
    r = run(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(ep.mp4)])
    try:
        n_ch = len(json.loads(r.stdout or "{}").get("chapters", []))
    except json.JSONDecodeError:
        n_ch = 0
    n_seg = len((ep.manifest or {}).get("segments", []))
    ok_ch = n_seg and n_ch == n_seg
    out.append(check("probe.chapters", "pass" if ok_ch else ("fail" if getattr(ep, "final", False) else "warn"),
                     f"{n_ch} chapter marker(s) in the mp4 for {n_seg} segment(s)",
                     "" if ok_ch else f"run transcript.py --workspace {ep.ws} --slug {ep.slug} --embed-chapters, then qc.py all --final"))
    # Black frames. pix_th 0.03 catches true black (Y 16) but not the template background #0E1117
    # (Y about 30), which pix_th 0.10 counted as black on a near-empty card (2 Nov 2026).
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(ep.mp4), "-an", "-vf",
             f"blackdetect=d={BLACK_MIN_S}:pix_th={BLACK_PIX_TH}", "-f", "null", "-"])
    blacks = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)]
    out.append(check("probe.black", "fail" if blacks else "pass",
                     f"{len(blacks)} black run(s) of {BLACK_MIN_S} s or more" + (": " + ", ".join(f"{mmss(a * 1000)}..{mmss(b * 1000)}" for a, b in blacks[:5]) if blacks else ""),
                     "a scene leaves the stage empty: check scene anchors at those times in scenes.json" if blacks else ""))
    # Dead air, with hold windows, the tail and <long pause> turns exempt.
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(ep.mp4), "-vn", "-af",
             f"silencedetect=noise=-40dB:d={DEAD_AIR_S}", "-f", "null", "-"])
    starts = [float(x) * 1000 for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) * 1000 for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    ends += [dur_ms] * (len(starts) - len(ends))
    exempt = []
    turns = (ep.manifest or {}).get("turns", [])
    for h in ep.holds():
        exempt.append((h["startMs"] - 500, h["endMs"] + 1500, f"hold after {h.get('turn')}"))
    if turns:
        exempt.append((turns[-1]["endMs"] - 500, dur_ms + 1, "final tail"))
        raw = ep.raw_text()
        for t in turns:
            if "<long pause>" in raw.get(t["id"], ""):
                exempt.append((t["startMs"] - 300, t["endMs"] + 1500, f"<long pause> in {t['id']}"))
    dead = []
    for a, b in zip(starts, ends):
        if not any(lo <= a and b <= hi for lo, hi, _ in exempt):
            dead.append((a, b))
    out.append(check("probe.deadair", "warn" if dead else "pass",
                     f"{len(dead)} unplanned silence(s) of {DEAD_AIR_S} s or more ({len(starts) - len(dead)} exempt: holds, tail, <long pause>)"
                     + (": " + ", ".join(f"{mmss(a)}..{mmss(b)}" for a, b in dead[:5]) if dead else ""),
                     "a turn ends early or a gap is too long: listen there, retake the turn (tts.py --only <id> --retake) or mark a planned pause with holdAfterMs" if dead else ""))
    return out


# ------------------------------------------------------------------------------------------- stills

def still_plan(ep: Episode) -> list[dict]:
    """Entry, middle and exit per segment; the middle of each hold; and the middle of every turn
    in a causal segment (mechanism, example, misconception, compare, scale, transfer), so the
    judge can score J4 step by step instead of guessing between samples."""
    m = ep.need_manifest()
    total = ep.total_ms()
    last_frame = math.ceil(total / FRAME_MS) - 1
    plan = []
    roles = {s["id"]: s.get("role") for s in m.get("segments", [])}
    for s in m.get("segments", []):
        a, b = s["startMs"], s["endMs"]
        for kind, ms in (("entry", a + 300), ("middle", (a + b) / 2), ("exit", b - 300)):
            plan.append({"segment": s["id"], "kind": kind, "ms": int(ms)})
    # one still at the middle of every scene, so a visual that sits on a non-causal turn (the position
    # signal waves, a head join, a table) is always in the evidence the judge and the restater read
    for sc in m.get("scenes", []):
        if "startMs" in sc and "endMs" in sc:
            mid = int((sc["startMs"] + sc["endMs"]) / 2)
            seg = next((x["id"] for x in m.get("segments", []) if x["startMs"] <= mid <= x["endMs"]), None)
            if seg:
                plan.append({"segment": seg, "kind": f"scene-{sc.get('id')}", "ms": mid})
                # the end of a scene shows what its steps built (dots, bars, joined boxes); the middle may not
                if sc["endMs"] - sc["startMs"] > 4000:
                    plan.append({"segment": seg, "kind": f"sceneend-{sc.get('id')}", "ms": int(sc["endMs"] - 400)})
    for h in ep.holds():
        plan.append({"segment": h.get("segment"), "kind": f"hold-{h.get('turn')}", "ms": int((h["startMs"] + h["endMs"]) / 2)})
    for t in m.get("turns", []):
        if roles.get(t.get("segment")) in CAUSAL_ROLES:
            plan.append({"segment": t["segment"], "kind": f"turn-{t['id']}", "ms": int((t["startMs"] + t["endMs"]) / 2)})
    for p in plan:
        p["frame"] = max(0, min(last_frame, round(p["ms"] / FRAME_MS)))
        # W14a: the world marks the renderer draws on this frame (spotlight, arcs, tint, walk arrows,
        # change band), after the W13b expiry rules, so a reader of index.json sees what is lit.
        mk = pc.marks_at(m, p["frame"] * FRAME_MS)
        if mk is not None:
            p["marks"] = {k: v for k, v in mk.items() if v}
    return plan


def stills(ep: Episode, from_remotion: bool = False) -> list[dict]:
    plan = still_plan(ep)
    sdir = ep.qc / "stills"
    if sdir.is_dir():  # stills of an older build must not survive into this review
        for old in sdir.glob("*.png"):
            old.unlink()
    sdir.mkdir(parents=True, exist_ok=True)
    use_mp4 = not from_remotion
    if use_mp4 and not ep.mp4.is_file():
        return [check("stills.render", "fail", f"no {ep.mp4}: stills come from the delivered mp4",
                      "render the mp4 first (or pass --from-remotion for a source preview, never for the judge)")]
    if not use_mp4 and not (ep.remotion / "package.json").is_file():
        return [check("stills.render", "fail", f"no Remotion project at {ep.remotion}", "drop --from-remotion")]
    failed = []
    for p in plan:
        name = f"{p['segment']}-{p['kind']}.png"
        dst = sdir / name
        p["path"] = str(dst)
        if use_mp4:
            r = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{p['frame'] / FPS:.3f}", "-i", str(ep.mp4), "-frames:v", "1", str(dst)])
        else:
            props = json.dumps({"slug": ep.slug})
            r = run(["npx", "remotion", "still", "Episode", str(dst), f"--props={props}", f"--frame={p['frame']}"], cwd=ep.remotion)
        if r.returncode or not dst.is_file():
            failed.append(f"{name}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['no output']}")
    (sdir / "index.json").write_text(json.dumps({"source": "mp4" if use_mp4 else "remotion still",
                                                 "mp4Sha256": pc.file_sha(ep.mp4, 64) if use_mp4 else None,
                                                 "stills": plan}, indent=1) + "\n")
    out = [check("stills.render", "fail" if failed else ("pass" if use_mp4 else "warn"),
                 f"{len(plan) - len(failed)} of {len(plan)} stills from {'the delivered mp4' if use_mp4 else 'npx remotion still (source preview, not the delivered file)'} in {sdir}"
                 + ("; failed: " + "; ".join(failed[:3]) if failed else ""),
                 "run the failing still by hand in the remotion folder and read its error" if failed else "")]
    ok = [p for p in plan if Path(p["path"]).is_file()]
    viewing, _ = read_viewing(ep)
    for old in ep.qc.glob("contact-sheet-720-*.png"):
        old.unlink()

    def sheet(name: str, frames: list[dict], width: int, cols: int):
        with tempfile.TemporaryDirectory() as tmp:
            for i, p in enumerate(frames, 1):
                shutil.copy(p["path"], Path(tmp) / f"{i:04d}.png")
            rows = math.ceil(len(frames) / cols)
            r = run(["ffmpeg", "-y", "-v", "error", "-framerate", "1", "-i", str(Path(tmp) / "%04d.png"), "-vf",
                     f"scale={width}:-1,tile={cols}x{rows}:padding=4:color=black", "-frames:v", "1", str(ep.qc / name)])
        return r, rows

    for name, width, cols in (("contact-sheet.png", 480, 6), ("contact-sheet-phone.png", 360, 4)):
        if not ok:
            break
        r, rows = sheet(name, ok, width, cols)
        role = (" (the readability reference: brief.json viewing is phone)" if viewing == "phone" else " (optional evidence: viewing is desktop)") if "phone" in name else ""
        out.append(check(f"stills.{name.split('.')[0]}", "fail" if r.returncode else "pass",
                         f"{ep.qc / name} ({cols} columns x {rows} rows, {width} px tiles){role}" if not r.returncode else r.stderr.strip()[:200],
                         "" if not r.returncode else "check ffmpeg on the stills folder"))
    if ok and viewing == "desktop":
        # 720p reference: every still at 1280 px wide (a 720p player), 2 x 3 per page.
        pages, bad = [], []
        for k in range(0, len(ok), SHEET720_PER_PAGE):
            name = f"contact-sheet-720-{k // SHEET720_PER_PAGE + 1:02d}.png"
            r, _ = sheet(name, ok[k:k + SHEET720_PER_PAGE], 1280, 2)
            (bad if r.returncode else pages).append(name if not r.returncode else f"{name}: {r.stderr.strip()[:120]}")
        out.append(check("stills.contact-sheet-720", "fail" if bad else "pass",
                         f"{len(pages)} page(s) {ep.qc}/contact-sheet-720-NN.png (2 columns x up to 3 rows, 1280 px tiles: "
                         "the readability reference for viewing desktop)" + ("; failed: " + "; ".join(bad[:2]) if bad else ""),
                         "check ffmpeg on the stills folder" if bad else ""))
    return out


# ------------------------------------------------------------------------------------------- captions

def _chars(ws: list[dict]) -> int:
    return len(" ".join(w["text"] for w in ws))


def caption_pages(turns: list[dict], mode: str, max_cps: float, min_page: float, holds=()) -> list[dict]:
    """Python port of templates/remotion/src/components/captionPages.ts buildCaptionPages.

    `holds` is manifest["holds"] (the 5th argument of buildCaptionPages, N05): the early start of a
    fast page never reaches back into a hold that ends before the page's first word."""
    lim = LIMITS[mode]
    out = []
    need = lambda g: max(min_page, _chars(g) / max_cps * 1000)
    for ti, turn in enumerate(turns):
        words = [w for w in turn.get("words", []) if w["text"].strip()]
        if not words:
            continue
        groups, cur = [], []
        for i, w in enumerate(words):
            if cur and _chars(cur + [w]) > lim["maxChars"]:
                groups.append(cur)
                cur = []
            cur.append(w)
            nxt = words[i + 1] if i + 1 < len(words) else None
            pause = bool(nxt) and nxt["startMs"] - w["endMs"] > GAP_BREAK_MS
            ends_soon = any(len(words[i + 1:i + 1 + k]) == k and SENTENCE_END.search(words[i + k]["text"])
                            and len(cur) + k <= lim["maxWords"] + 2 for k in (1, 2))
            if ((len(cur) >= lim["maxWords"] and not (ends_soon and not pause))
                    or (SENTENCE_END.search(w["text"]) and len(cur) >= lim["minWords"])
                    or (CLAUSE_END.search(w["text"]) and len(cur) >= lim["minWords"] + (1 if mode == "karaoke" else 0))
                    or (pause and len(cur) >= lim["minWords"])):
                groups.append(cur)
                cur = []
        if cur:
            prev = groups[-1] if groups else None
            if prev and len(cur) < lim["minWords"] and len(prev) + len(cur) <= lim["maxWords"] + 1 and _chars(prev + cur) <= lim["maxChars"] + 8:
                prev.extend(cur)
            else:
                groups.append(cur)
        next_start = turns[ti + 1]["startMs"] if ti + 1 < len(turns) else math.inf
        turn_end = min(turn["endMs"] + HOLD_AFTER_TURN_MS, next_start)

        def shown(gs, gi):
            if gi + 1 < len(gs):
                return gs[gi + 1][0]["startMs"] - gs[gi][0]["startMs"]
            return max(turn_end, min(gs[gi][0]["startMs"] + need(gs[gi]), next_start)) - gs[gi][0]["startMs"]

        fits = lambda g: len(g) <= lim["hardWords"] and _chars(g) <= lim["hardChars"]
        stuck = set()
        for _ in range(500):
            gi = next((i for i, g in enumerate(groups) if id(g[0]) not in stuck and need(g) - shown(groups, i) > 0), -1)
            if gi < 0:
                break
            opts = []
            if gi + 1 < len(groups):
                opts.append((gi, groups[gi] + groups[gi + 1]))
            if gi > 0:
                opts.append((gi - 1, groups[gi - 1] + groups[gi]))
            best = None
            for at, merged in opts:
                if not fits(merged):
                    continue
                trial = groups[:at] + [merged] + groups[at + 2:]
                d = need(trial[at]) - shown(trial, at)
                if best is None or d < best[2]:
                    best = (at, merged, d)
            if best is None:
                stuck.add(id(groups[gi][0]))
                continue
            groups[best[0]:best[0] + 2] = [best[1]]
        # 2b. Reading rate: move a fast page's boundary with a same-turn neighbour by up to 4 words.
        cps = lambda gs, gi: _chars(gs[gi]) / max(1, shown(gs, gi)) * 1000
        for _ in range(3):
            changed = False
            gi = 0
            while gi < len(groups):
                if cps(groups, gi) <= TARGET_CPS:
                    gi += 1
                    continue
                best_score, best_gs = cps(groups, gi), None
                for at in (gi - 1, gi):
                    if at < 0 or at + 1 >= len(groups):
                        continue
                    both = groups[at] + groups[at + 1]
                    for cut in range(2, len(both) - 1):
                        if cut == len(groups[at]) or abs(cut - len(groups[at])) > 4:
                            continue
                        a, b = both[:cut], both[cut:]
                        if not fits(a) or not fits(b):
                            continue
                        trial = groups[:at] + [a, b] + groups[at + 2:]
                        score = max(cps(trial, at), cps(trial, at + 1))
                        if score < best_score - 0.05:
                            best_score, best_gs = score, trial
                if best_gs is not None:
                    groups = best_gs
                    changed = True
                gi += 1
            if not changed:
                break
        for gi, g in enumerate(groups):
            s = g[0]["startMs"]
            out.append({"turn": turn["id"], "speaker": turn["speaker"], "startMs": s, "endMs": s + shown(groups, gi),
                        "chars": _chars(g), "text": " ".join(w["text"] for w in g), "speechEndMs": g[-1]["endMs"],
                        "firstWordMs": s})
    # 3. Reading rate: a page faster than TARGET_CPS starts early, into the silence before it.
    for i, p in enumerate(out):
        want = p["chars"] / TARGET_CPS * 1000
        if p["endMs"] - p["startMs"] >= want:
            continue
        prev = out[i - 1] if i > 0 else None
        earliest = max(0, p["startMs"] - MAX_LEAD_MS)
        if prev:
            keep = prev["startMs"] + prev["chars"] / TARGET_CPS * 1000
            earliest = max(earliest, prev["speechEndMs"], min(keep, prev["endMs"]))
        # N05: never into a hold that ends before this page's first word (p["startMs"] is still it).
        for h in holds or ():
            hs, he = h.get("startMs", 0), h.get("endMs", 0)
            if he > hs and hs < p["startMs"] and he > earliest:
                earliest = max(earliest, min(he, p["startMs"]))
        start = max(earliest, p["endMs"] - want)
        if start < p["startMs"]:
            p["startMs"] = round(start)
            if prev and prev["endMs"] > p["startMs"]:
                prev["endMs"] = p["startMs"]
    # 4. Flicker: hold a page through a blank shorter than HOLD_GAP_MS (5 frames).
    for a, b in zip(out, out[1:]):
        gap = b["startMs"] - a["endMs"]
        if 0 < gap < HOLD_GAP_MS:
            a["endMs"] = b["startMs"]
    return out


def overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def world_node_boxes(m: dict) -> list[tuple[float, str, str, tuple]]:
    """Screen boxes of revealed world nodes at each world step (camera after its move)."""
    world = m.get("world")
    if not world:
        return []
    W, H = world.get("width", 1728), world.get("height", 712)
    cam = {"x": W / 2, "y": H / 2, "zoom": 1, **(world.get("camera") or {})}  # a partial camera keeps the defaults
    fit = min(1728 / W, 712 / H)
    steps = []
    for sc in m["scenes"]:
        if sc["type"] != "world":
            continue
        for i, st in enumerate(sc["props"].get("steps", []) or []):
            steps.append((st.get("atMs", sc["startMs"] + i * 1500), sc, st))
    steps.sort(key=lambda x: x[0])
    out = []
    for t, sc, st in steps:
        if st.get("camera"):
            cam.update(st["camera"])
        s = fit * cam.get("zoom", 1)
        for n in world["nodes"]:
            if n.get("revealAtMs", 0) > t + 1000:
                continue
            if n.get("role") and "shape" not in n:  # ring discs (WorldScene.tsx RING_DEFAULTS)
                w = h = n.get("w", RING_DEFAULTS[n["role"]])
            else:
                shape = n.get("shape", "box")
                w, h = NODE_DEFAULTS[shape]
                w = n.get("w", w)
                h = w if shape == "circle" else n.get("h", h + (40 if n.get("value") is not None and shape == "box" else 0))
            cx = STAGE[0] + 864 + (n["x"] - cam["x"]) * s
            cy = STAGE[1] + 356 + (n["y"] - cam["y"]) * s
            out.append((t, sc["id"], n["id"], (cx - w * s / 2, cy - h * s / 2, cx + w * s / 2, cy + h * s / 2)))
    return out


def captions(ep: Episode) -> list[dict]:
    m = ep.need_manifest()
    cap = m.get("captions", {})
    mode = cap.get("mode", "karaoke")
    out = []
    if mode == "off":
        return [check("captions.mode", "skip", "captions mode is off", "")]
    min_page = cap.get("minPageMs", 700)
    holds = m.get("holds") or []
    pages = caption_pages(m["turns"], mode, cap.get("maxCharsPerSecond", 17), min_page, holds)

    def caps_on(ms):
        sc = next((s for s in m["scenes"] if s["startMs"] <= ms < s["endMs"]), None)
        return not (sc and sc.get("captions") == "off")

    pages = [p for p in pages if caps_on(p["startMs"])]
    if not pages:
        return [check("captions.pages", "warn", "no caption pages (no words in episode.json turns?)", "run align.mjs, then build_manifest.py")]
    for p in pages:
        p["cps"] = p["chars"] / max(1, p["endMs"] - p["startMs"]) * 1000
    worst = max(pages, key=lambda p: p["cps"])
    fast = [p for p in pages if p["cps"] > CPS_WARN]
    out.append(check("captions.rate", "warn" if fast else "pass",
                     f"{len(pages)} {mode} pages, peak {worst['cps']:.1f} chars/s at {worst['turn']} {mmss(worst['startMs'])} (\"{worst['text'][:50]}\"); "
                     f"{len(fast)} page(s) above {CPS_WARN:.0f}",
                     f"split turn {fast[0]['turn']} or slow its delivery; or set scenes.json captions.maxCharsPerSecond lower so pages merge" if fast else ""))
    short = [p for p in pages if p["endMs"] - p["startMs"] < min_page]
    out.append(check("captions.minTime", "warn" if short else "pass",
                     f"{len(short)} page(s) under {min_page} ms" + (f"; shortest {min(p['endMs'] - p['startMs'] for p in short):.0f} ms at {short[0]['turn']} {mmss(short[0]['startMs'])}" if short else ""),
                     f"turn {short[0]['turn']} is too fast to read: split it or use karaoke mode" if short else ""))
    flashes = [(a, b) for a, b in zip(pages, pages[1:]) if FLASH_GAP_MS[0] <= b["startMs"] - a["endMs"] <= FLASH_GAP_MS[1]]
    out.append(check("captions.flash", "warn" if flashes else "pass",
                     f"{len(flashes)} blank flicker(s) of {FLASH_GAP_MS[0]} to {FLASH_GAP_MS[1]} ms between pages"
                     + (f"; first {flashes[0][0]['turn']} -> {flashes[0][1]['turn']} at {mmss(flashes[0][0]['endMs'])}" if flashes else ""),
                     "the page builder holds a page through any blank under 167 ms, so a flicker means qc.py and captionPages.ts disagree or words[] overlap; check those turns" if flashes else ""))
    # N05: a page whose first word comes after a hold must not show during the hold.
    in_hold = [(p, h) for p in pages for h in holds
               if h.get("startMs", 0) <= p["startMs"] < h.get("endMs", 0) and p["firstWordMs"] >= h.get("endMs", 0)]
    out.append(check("captions.hold", "fail" if in_hold else "pass",
                     (f"{len(in_hold)} page(s) start inside a hold before their first word; first {in_hold[0][0]['turn']} "
                      f"page at {mmss(in_hold[0][0]['startMs'])}, hold {mmss(in_hold[0][1]['startMs'])}..{mmss(in_hold[0][1]['endMs'])} "
                      f"(\"{in_hold[0][0]['text'][:40]}\")") if in_hold else f"no caption page shows inside any of {len(holds)} hold(s)",
                     "qc.py caption_pages and captionPages.ts disagree about holds: pass manifest.holds to both and rebuild" if in_hold else ""))
    geo = []
    if overlap(CAPTION_BOX, STAGE):
        geo.append("caption box overlaps the stage")
    for side, box in BADGES.items():
        if overlap(CAPTION_BOX, box):
            geo.append(f"caption box overlaps the {side} speaker badge")
    if overlap(CHIP_ROW, STAGE):
        geo.append("keyword chip row overlaps the stage")
    clipped = []
    for t, sid, nid, box in world_node_boxes(m):
        if overlap(box, CAPTION_BOX) and caps_on(t):
            geo.append(f"world node {nid} at {mmss(t)} reaches the caption band")
        if box[0] < STAGE[0] - 1 or box[1] < STAGE[1] - 1 or box[2] > STAGE[2] + 1 or box[3] > STAGE[3] + 1:
            clipped.append(f"{nid} in {sid} at {mmss(t)}")
    out.append(check("captions.geometry", "fail" if geo else "warn" if clipped else "pass",
                     "; ".join(geo) if geo else (f"no overlap; {len(clipped)} world node(s) cut by the stage edge: " + ", ".join(sorted(set(clipped))[:5]) if clipped
                                                 else "caption box 300..1620 x 852..1026 clear of stage, badges, chips; world nodes inside the stage"),
                     "move the node (world.nodes x/y) or the camera step so the node stays inside the stage" if (geo or clipped) else ""))
    ep._pages = pages
    return out


# ------------------------------------------------------------------------------------------- coverage

def _key(s: str) -> str:
    k = re.sub(r"[^a-z0-9]", "", s.lower())
    return k[:-1] if k.endswith("s") and len(k) > 3 else k


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    if isinstance(obj, dict):
        return [s for k, v in obj.items() if k not in ("component", "language", "svg", "viewBox") for s in _strings(v)]
    return []


def coverage(ep: Episode) -> list[dict]:
    m = ep.need_manifest()

    def visible(lo: int, hi: int) -> str:
        # Only what is on screen by `hi`: future steps, unrevealed nodes and unanswered cues do not count.
        return pc.visible_text(m, lo, hi)

    miss_terms, miss_nums, n_terms, n_nums = [], [], 0, 0
    for t in m["turns"]:
        lo, hi = t["startMs"] - 1500, t["endMs"] + 1500
        vis = visible(lo, hi)
        vkey = _key(vis)
        vnums = {x.replace(",", "") for x in NUM_RE.findall(vis)}
        for term in t.get("onScreen", []):
            n_terms += 1
            if _key(term) not in vkey:
                miss_terms.append(f"{t['id']} '{term}' @ {mmss(t['startMs'])}")
        for num in {x.replace(",", "") for x in NUM_RE.findall(t["text"])}:
            n_nums += 1
            if num not in vnums:
                miss_nums.append(f"{t['id']} '{num}' @ {mmss(t['startMs'])}")
    out = [check("coverage.onScreen", "warn" if miss_terms else "pass",
                 f"{n_terms - len(miss_terms)} of {n_terms} onScreen terms have a visible event within 1.5 s" + (": missing " + "; ".join(miss_terms[:8]) if miss_terms else ""),
                 "add a chip overlay or a node label anchored to that word, or rerun build_manifest.py --auto-chips" if miss_terms else ""),
           check("coverage.numbers", "warn" if miss_nums else "pass",
                 f"{n_nums - len(miss_nums)} of {n_nums} spoken numbers are on screen within 1.5 s" + (": missing " + "; ".join(miss_nums[:8]) if miss_nums else ""),
                 "show the number (node value via a world step `set`, or a chip) when it is spoken" if miss_nums else "")]
    # Anchors name real turns.
    turn_ids = {t.get("id") for seg in (ep.script or {}).get("segments", []) for t in seg.get("turns", [])} or {t["id"] for t in m["turns"]}
    bad, ms_anchors = [], []

    def walk(obj, where):
        if isinstance(obj, dict):
            if "turn" in obj and isinstance(obj.get("turn"), str):
                if obj["turn"] not in turn_ids:
                    bad.append(f"{where}: turn {obj['turn']}")
            elif "ms" in obj and isinstance(obj.get("ms"), (int, float)) and len(obj) <= 2:
                ms_anchors.append(where)
            for k, v in obj.items():
                walk(v, f"{where}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{where}[{i}]")

    src = ep.scenes or {}
    for sc in src.get("scenes", []):
        walk(sc.get("anchor"), f"scene {sc.get('id')} anchor")
        walk(sc.get("props"), f"scene {sc.get('id')} props")
    for ov in src.get("overlays", []):
        walk(ov.get("anchor"), f"overlay {ov.get('id')} anchor")
    if not ep.scenes:
        out.append(check("coverage.anchors", "skip", f"{ep.dir / 'scenes.json'} not found", "write scenes.json"))
    else:
        out.append(check("coverage.anchors", "fail" if bad else "warn" if ms_anchors else "pass",
                         ("unknown turns: " + "; ".join(bad[:6])) if bad else
                         (f"{len(ms_anchors)} absolute ms anchor(s) do not move with a new take: " + "; ".join(ms_anchors[:4]) if ms_anchors else "every anchor names a turn in script.json"),
                         "fix the turn id in scenes.json (turn ids come from script.json), then rerun build_manifest.py" if bad else
                         ("anchor to a turn or word instead of {\"ms\": ...}" if ms_anchors else "")))
    holds = ep.holds()
    raw_pause = {t.get("id"): t.get("pause") for seg in (ep.script or {}).get("segments", []) for t in seg.get("turns", []) if t.get("pause")}
    no_prompt = [h["turn"] for h in holds if (h.get("kind") or raw_pause.get(h.get("turn"))) and not (h.get("prompt") or (raw_pause.get(h.get("turn")) or {}).get("prompt"))]
    no_hold = [tid for tid in raw_pause if tid not in {h.get("turn") for h in holds}]
    out.append(check("coverage.pauses", "fail" if no_prompt or no_hold else "pass",
                     f"{len(holds)} hold(s), {len(raw_pause)} pause cue(s)" + (f"; pause without prompt: {no_prompt}" if no_prompt else "")
                     + (f"; pause without a hold in episode.json: {no_hold}" if no_hold else ""),
                     "give every `pause` a prompt and holdAfterMs 6000 to 8000 in script.json, then rerun tts.py and build_manifest.py"
                     if no_prompt or no_hold else ""))
    out += text_size(ep)
    out += labels_counts(ep)
    out += labels_stale(ep)
    out += labels_early(ep)
    out += marks_focus(ep)
    out += world_nodefit(ep)
    return out


# ------------------------------------------------------------------------------------------- labels.early

def labels_early(ep: Episode) -> list[dict]:
    """labels.early (W16, W15 proposal 1; W18 gate): a number on a chip, stat, banner, note or `set`
    label that shows before any word speaks it. A label the author reviewed carries `earlyOk: "reason"`
    on its step, banner or chip (the picture is meant to lead, for example a cold-open prompt or the
    same quantity in other words); it is listed, never counted. An unreviewed early label is a warning
    in the diagnostic run and a fail under --final."""
    m = ep.need_manifest()
    probs = pc.early_label_problems(m)
    open_ = [p for p in probs if not p.get("earlyOk")]
    ok = [p for p in probs if p.get("earlyOk")]

    def line(p):
        return (f"{p['where']} '{p['text']}' shows {p['number'].replace('point', '.')} at {mmss(p['shownMs'])} in {p['turn']}, "
                f"{p['leadMs'] / 1000:.1f} s before {p['spokenTurn']} speaks it ({mmss(p['spokenMs'])})")
    reviewed = (f"; {len(ok)} reviewed earlyOk: " + "; ".join(f"{p['where']} '{p['text']}' ({p['earlyOk']})" for p in ok[:6])) if ok else ""
    if not open_:
        return [check("labels.early", "pass", "no unreviewed cued label shows a number before it is spoken" + reviewed)]
    return [check("labels.early", "fail" if getattr(ep, "final", False) else "warn",
                  f"{len(open_)} unreviewed label number(s) shown before they are spoken: " + "; ".join(line(p) for p in open_[:6])
                  + (f"; and {len(open_) - 6} more" if len(open_) > 6 else "") + reviewed,
                  "anchor the step to the word that speaks the number (never to a summary turn before it), or, when the "
                  "picture is meant to lead, add earlyOk: \"<reason>\" to that step, banner or chip in scenes.json; then rerun build_manifest.py")]


# ------------------------------------------------------------------------------------------- world.nodefit

def world_nodefit(ep: Episode) -> list[dict]:
    """world.nodefit (W16, W14b D15): a node whose label, sublabel and value need more height than
    the node draws (the value overlaps the sublabel and spills out). The episode world and every
    compare panel's own world."""
    m = ep.need_manifest()
    probs = []
    if m.get("world"):
        probs += [f"world {p}" for p in pc.node_fit_problems(m["world"], pc.world_timeline(m))]
    for sc in m.get("scenes", []):
        if sc.get("type") != "compare":
            continue
        for side in ("left", "right"):
            pn = (sc.get("props") or {}).get(side) or {}
            if pn.get("kind") == "world" and isinstance(pn.get("world"), dict):
                tl = pc.local_timeline(pn.get("steps") or [], f"{sc['id']}-{side}", sc.get("startMs", 0))
                probs += [f"{sc['id']} {side} panel {p}" for p in pc.node_fit_problems(pn["world"], tl)]
    if not m.get("world") and not probs:
        return [check("world.nodefit", "skip", "no concept world in episode.json")]
    if probs:
        return [check("world.nodefit", "fail", f"{len(probs)} node(s) too short for their text: " + "; ".join(probs[:6]),
                      "drop the explicit h (pills and boxes grow for a value line), or move the value to its own node; rebuild and render")]
    return [check("world.nodefit", "pass", "every node is tall enough for its label, sublabel and value")]


# ------------------------------------------------------------------------------------------- marks.focus

def marks_focus(ep: Episode) -> list[dict]:
    """marks.focus (W13b port, judge v6 item 1): the spotlight must not dim what a walk arrow or the
    words name. Replays pe_common.focus_problems (worldState.ts focusProblems) on episode.json with
    the W13b expiry rules (marks end at the next step unless persist). Warnings: the judge decides."""
    m = ep.need_manifest()
    if not m.get("world"):
        return [check("marks.focus", "skip", "no concept world in episode.json")]
    probs = pc.focus_problems(m)
    timeline = pc.world_timeline(m)
    res = pc.resolve_steps(timeline, m["world"])
    kept = sorted({k for st in timeline for k in pc.MARK_KINDS if pc.persists(st, k)})
    walks = sum(1 for st in timeline if st.get("walk"))
    if probs:
        return [check("marks.focus", "warn", f"{len(probs)} spotlight problem(s): " + "; ".join(probs[:6]),
                      "add the named node to that step's focus or speaksOf, add a step on the word, or set \"focus\": []; "
                      "then rerun build_manifest.py (it prints the same warnings)")]
    return [check("marks.focus", "pass", f"{len(res)} world step(s), {walks} walk(s): no spotlight dims what a walk or the words name "
                  f"(marks end at the next step unless persist; persisted kinds: {', '.join(kept) or 'none'})")]


# ------------------------------------------------------------------------------------------- text size

# The judge treats text under 28 px as a bug (motionConstants.ts MIN_TEXT_PX). Built-in scenes clamp
# their text to it; custom components and SVG files are code the agent wrote, so QC reads them.
MIN_TEXT_PX = 28
DIAGRAM_HEADING_PX = 92            # DiagramScene.tsx: a title takes 92 px of the stage height
SVG_DEFAULT_FONT = 16              # browser default font-size for SVG text with no size set
_FONT_SIZE_RE = re.compile(r"fontSize\s*(?::|=)\s*")
_ARITH_RE = re.compile(r"^[\d\s.+\-*/()]+$")


def _theme_type(remotion: Path) -> dict[str, float]:
    """theme.ts `type` scale (min is MIN_TEXT_PX), from the project, else the skill template."""
    out = {"min": MIN_TEXT_PX}
    for root in (remotion, SKILL / "templates" / "remotion"):
        try:
            text = (root / "src" / "theme.ts").read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"export const type\s*=\s*\{([^}]*)\}", text)
        if m:
            out.update({k: float(v) for k, v in re.findall(r"(\w+)\s*:\s*(\d+(?:\.\d+)?)", m.group(1))})
            return out
    return out


def _expr_after(text: str, i: int) -> str:
    """The expression that starts at text[i]: a JSX {...}, a quoted string, or an object value."""
    if i < len(text) and text[i] == "{":
        depth, j = 0, i
        while j < len(text):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                return text[i + 1:j]
            j += 1
        return text[i + 1:]
    if i < len(text) and text[i] in "\"'":
        j = text.find(text[i], i + 1)
        return text[i:j + 1]
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif c in ",\n" and depth == 0:
            break
        j += 1
    return text[i:j]


def _font_px(expr: str, scale_type: dict[str, float]):
    """(px, kind): kind 'value' for a number we can compute, 'clamped' for Math.max(... type.min or
    MIN_TEXT_PX ...), 'unknown' otherwise."""
    e = expr.strip()
    if re.search(r"Math\.max\([^)]*(type\.min|MIN_TEXT_PX)", e):
        return None, "clamped"
    q = re.fullmatch(r"[\"']\s*(\d+(?:\.\d+)?)\s*(px)?\s*[\"']", e)
    if q:
        return float(q.group(1)), "value"
    sub = re.sub(r"\btype\.(\w+)", lambda m: str(scale_type.get(m.group(1), "?")), e)
    sub = re.sub(r"\bMIN_TEXT_PX\b", str(MIN_TEXT_PX), sub)
    if _ARITH_RE.match(sub) and sub.strip():
        try:
            return float(eval(compile(sub, "<fontSize>", "eval"), {"__builtins__": {}}, {})), "value"  # digits and + - * / only
        except Exception:  # noqa: BLE001
            return None, "unknown"
    return None, "unknown"


def _custom_files(remotion: Path, names: set[str]) -> dict[str, Path | None]:
    cdir = remotion / "src" / "scenes" / "custom"
    try:
        index = (cdir / "index.ts").read_text(encoding="utf-8")
    except OSError:
        index = ""
    imports = {}
    for names_s, mod in re.findall(r"import\s*\{([^}]*)\}\s*from\s*[\"']\./([^\"']+)[\"']", index):
        for n in names_s.split(","):
            n = n.strip().split(" as ")[-1].strip()
            if n:
                imports[n] = mod
    out = {}
    for n in names:
        mod = imports.get(n, n)
        f = next((cdir / f"{mod}{ext}" for ext in ("", ".tsx", ".ts") if (cdir / f"{mod}{ext}").is_file()), None)
        out[n] = f
    return out


def custom_font_problems(path: Path, scale_type: dict[str, float], limit: float = MIN_TEXT_PX) -> tuple[list[str], list[str]]:
    """(fails, warns) for fontSize values under `limit` (MIN_TEXT_PX) in one custom component file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # An <svg viewBox> whose width and height differ from the viewBox scales its text: a literal is
    # then only a warning. width={W} height={H} viewBox="0 0 W H" is 1:1.
    scaled = False
    for tag in re.findall(r"<svg\b[^>]*>", text, re.S):
        vb = re.search(r"viewBox=[\"{]+\s*[\d.\-]+[\s,]+[\d.\-]+[\s,]+([\d.]+)[\s,]+([\d.]+)", tag)
        w = re.search(r"\bwidth=\{?[\"']?([\d.]+)", tag)
        h = re.search(r"\bheight=\{?[\"']?([\d.]+)", tag)
        if vb and not (w and h and float(w.group(1)) == float(vb.group(1)) and float(h.group(1)) == float(vb.group(2))):
            scaled = True
    fails, warns = [], []
    for m in _FONT_SIZE_RE.finditer(text):
        expr = _expr_after(text, m.end())
        line = text.count("\n", 0, m.start()) + 1
        px, kind = _font_px(expr, scale_type)
        where = f"{path.name}:{line} fontSize {expr.strip()[:40]}"
        if kind == "value" and px < limit:
            (warns if scaled else fails).append(f"{where} = {px:g} px" + (" (inside a scaled <svg viewBox>)" if scaled else ""))
        elif kind == "unknown":
            warns.append(f"{where} (computed; cannot verify)")
    return fails, warns


def _svg_box(viewbox: str | None, titled: bool) -> float:
    """Scale from SVG user units to stage px: DiagramScene fits the file's viewBox into the stage
    (1728 x 712, minus the 92 px heading) with preserveAspectRatio meet. No viewBox: 1:1."""
    if not viewbox:
        return 1.0
    try:
        _, _, w, h = [float(x) for x in re.split(r"[\s,]+", viewbox.strip())]
    except ValueError:
        return 1.0
    if w <= 0 or h <= 0:
        return 1.0
    avail_w = STAGE[2] - STAGE[0]
    avail_h = (STAGE[3] - STAGE[1]) - (DIAGRAM_HEADING_PX if titled else 0)
    return min(avail_w / w, avail_h / h)


_SVG_SIZE_RE = re.compile(r"""font-size\s*(?:=\s*["']\s*|:\s*)([\d.]+)\s*([a-z%]*)""", re.I)
_SVG_FONT_RE = re.compile(r"""\bfont\s*:\s*(?:[^;}"']*?\s)?([\d.]+)(px|pt|em|rem|%)""", re.I)


def svg_font_problems(path: Path, titled: bool, limit: float = MIN_TEXT_PX) -> tuple[list[str], list[str]]:
    """(fails, warns) for SVG text that renders under `limit` (MIN_TEXT_PX) after the stage scale."""
    text = path.read_text(encoding="utf-8", errors="replace")
    root = re.search(r"<svg\b[^>]*>", text, re.S)
    vb = re.search(r"""viewBox\s*=\s*["']([^"']+)["']""", root.group(0)) if root else None
    scale = _svg_box(vb.group(1) if vb else None, titled)
    transformed = bool(re.search(r"""transform\s*[=:]\s*["']?[^"';>]*(scale|matrix)\s*\(""", text))
    fails, warns = [], []
    sizes = 0
    for rx in (_SVG_SIZE_RE, _SVG_FONT_RE):
        for m in rx.finditer(text):
            sizes += 1
            v, unit = float(m.group(1)), m.group(2).lower()
            line = text.count("\n", 0, m.start()) + 1
            where = f"{path.name}:{line} {m.group(0).strip()[:40]}"
            if unit in ("", "px", "pt"):
                px = v * (4 / 3 if unit == "pt" else 1) * scale
                if px < limit:
                    msg = f"{where} renders at {px:.1f} px (scale {scale:.2f})"
                    (warns if transformed else fails).append(msg + (" before a transform scale" if transformed else ""))
            else:
                warns.append(f"{where} ({unit} is relative; cannot verify)")
    if sizes == 0 and re.search(r"<text\b", text) and SVG_DEFAULT_FONT * scale < limit:
        warns.append(f"{path.name}: <text> with no font-size renders at the 16-unit default, {SVG_DEFAULT_FONT * scale:.1f} px (scale {scale:.2f})")
    return fails, warns


# Built-in scenes (W10). The renderer clamps most text to type.min, but a compare table and a
# diagram's inline elements take their size and colour from episode.json, so QC computes them:
# compare tables with a port of tableLayout.ts (or the legacy single-row layout when the project's
# CompareScene predates it), diagram text with DiagramScene's stage scale and dimming.
PHONE_TEXT_PX = 36                 # phone readability: text under 36 px at 1080p is about 7 px at 360 px wide
GRID_TEXT_PX = 36                  # tableLayout.ts GRID_TEXT_PX (theme.ts type.grid)
MAX_BAND_COLS = 8                  # phone readability: at most 8 cells per row in one band
CHAR_W = 0.62                      # tableLayout.ts CHAR_W: advance of a bold mono or sans character, in font sizes
CELL_TEXT_PAD = 8                  # tableLayout.ts CELL_TEXT_PAD
TABLE_LABEL_W, TABLE_CELL_GAP, TABLE_ROW_PAD, TABLE_BAND_GAP = 180, 6, 12, 16
TABLE_LABEL_MAX = pc.TABLE_LABEL_MAX
TABLE_PAD_X, TABLE_PAD_TOP, TABLE_MAX_CELL = 24, 8, 110
COMPARE_GAP, COMPARE_HEADER_H, COMPARE_STAT_H, COMPARE_VERDICT_H, COMPARE_HEADING_H = 40, 64, 84, 72, 80
SANS_CHAR_EM = 0.55                # average sans advance per character (row labels)
DIAGRAM_DIM = 0.35                 # DiagramScene.tsx: a non-highlighted element's opacity is 1 - 0.35 (0.65)
DIAGRAM_VIEWBOX = "0 0 1728 600"
CONTRAST_MIN = 4.5                 # WCAG AA for text
THEME_COLORS = {"bg": "#0E1117", "surface": "#171C26", "surfaceRaised": "#202736", "line": "#3A4356", "text": "#F2F4F8",
                "muted": "#A9B1C2", "dim": "#8E97AA", "accent": "#7CC4FF", "good": "#5BD69A", "warn": "#FFB020", "bad": "#FF7A7A"}
CSS_COLORS = {"white": "#FFFFFF", "black": "#000000", "gray": "#808080", "grey": "#808080", "red": "#FF0000",
              "green": "#008000", "blue": "#0000FF", "yellow": "#FFFF00", "orange": "#FFA500"}
VIEWINGS = ("desktop", "phone")


# The compare-table layout lives once, in pe_common (a 1:1 port of tableLayout.ts).
table_layout = pc.table_layout
table_chars = pc.table_chars


def legacy_table_layout(n_cols: int, w: float, label_px: float = 30) -> dict:
    """CompareScene.tsx before tableLayout.ts (W9 and older projects): one row of every column,
    cell min(96, floor((w - 48 - 150) / n) - 6), text type.label (30 px)."""
    n = max(1, n_cols)
    cell = min(96, math.floor((w - 48 - 150) / n) - 6)
    return {"bands": [list(range(n))], "perBand": n, "cell": cell, "rowH": max(cell, 56) + 14, "font": label_px,
            "labelW": 150, "bandGap": 0, "header": True}


def compare_body(titled: bool) -> tuple[float, float]:
    """CompareScene.tsx Panel: the table body (innerW x bodyH) inside one panel."""
    panel_w = (1728 - COMPARE_GAP) / 2
    panel_h = 712 - (COMPARE_HEADING_H if titled else 0) - COMPARE_VERDICT_H - 16
    return panel_w - 12, panel_h - COMPARE_HEADER_H - COMPARE_STAT_H - 12


def renderer_has_bands(remotion: Path) -> bool:
    """True when the Remotion project that renders this episode wraps tables into bands. A project
    without its own CompareScene.tsx is judged by the skill template."""
    scenes = remotion / "src" / "scenes"
    if (scenes / "CompareScene.tsx").is_file():
        return (scenes / "tableLayout.ts").is_file()
    return (SKILL / "templates" / "remotion" / "src" / "scenes" / "tableLayout.ts").is_file()


def color_rgb(c) -> tuple[float, float, float] | None:
    """#RGB / #RRGGBB / theme colour name / a few CSS names -> (r, g, b) in 0..255, else None."""
    if not isinstance(c, str):
        return None
    c = THEME_COLORS.get(c.strip(), CSS_COLORS.get(c.strip().lower(), c.strip()))
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", c)
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(x * 2 for x in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    """WCAG contrast ratio of two (r, g, b) colours."""
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def blend(fg, bg, alpha: float):
    return tuple(alpha * f + (1 - alpha) * b for f, b in zip(fg, bg))


def read_viewing(ep: Episode) -> tuple[str, str]:
    """(viewing, note): brief.json `viewing` (desktop default, or phone)."""
    try:
        brief = ep._load("brief.json") or {}
    except QcError as e:
        return "desktop", f"brief.json unreadable ({e}); using desktop"
    v = brief.get("viewing", "desktop")
    if v not in VIEWINGS:
        return "desktop", f"brief.json viewing {v!r} is not desktop or phone; using desktop"
    return v, ""


def builtin_text(ep: Episode) -> dict:
    """Text in built-in scenes that episode.json sizes or colours: compare tables and diagram
    inline elements. Returns read (what was read), fails (under 28 px or contrast under 4.5:1),
    warns, phone (under 36 px at 1080p or more than 8 cells per row)."""
    m = ep.need_manifest()
    fps = (m.get("video") or {}).get("fps") or FPS
    bands = renderer_has_bands(ep.remotion)
    bg = color_rgb(THEME_COLORS["bg"])
    out = {"read": [], "fails": [], "warns": [], "phone": []}
    for sc in m.get("scenes", []):
        p = sc.get("props") or {}
        sid = sc.get("id")
        if sc.get("type") == "compare":
            w, h = compare_body(bool(p.get("title")))
            for side in ("left", "right"):
                panel = p.get(side) or {}
                if panel.get("kind") != "table":
                    continue
                rows = panel.get("rows") or []
                cols = panel.get("columns") or []
                n = len(cols) or max([len(r.get("cells") or []) for r in rows] + [1])
                L = (table_layout(n, len(rows), w, h, bool(cols), table_chars(panel), pc.table_label_chars(panel)) if bands
                     else legacy_table_layout(n, w))
                where = f"{sid} {side} table"
                out["read"].append(f"{where}: {n} columns in {len(L['bands'])} band(s) of up to {L['perBand']}, cell {L['cell']} px, "
                                   f"text {L['font']:g} px" + ("" if bands else " (legacy one-row layout)"))
                if L["font"] < MIN_TEXT_PX:
                    out["fails"].append(f"{where}: cell text {L['font']:g} px")
                elif L["font"] < PHONE_TEXT_PX:
                    out["phone"].append(f"{where}: cell, header and row-label text {L['font']:g} px (phone needs {PHONE_TEXT_PX})")
                if L["perBand"] > MAX_BAND_COLS:
                    out["phone"].append(f"{where}: {L['perBand']} cells per row (phone needs {MAX_BAND_COLS} or fewer; "
                                        f"at 360 px wide a cell is {L['cell'] * 360 / 1920:.0f} px)")
                # R03: one cell per column in every row, or the renderer drops or leaves out cells.
                lens = sorted({len(r.get("cells") or []) for r in rows})
                if rows and lens != [n]:
                    out["fails"].append(f"{where}: rows have {', '.join(map(str, lens))} cells for {n} columns; every row needs one cell per column")
                # R01: impossible geometry. Text taller than its cell, or a cell string wider than the cell
                # (mono, about MONO_CHAR_EM x font per character), overlaps or overflows in every viewing.
                longest = table_chars(panel)
                need_w = longest * CHAR_W * L["font"]
                # Stumble 5: the row label draws at labelFont (W13b: the label column grows to 320 px, then
                # the label text shrinks); a legacy layout has no labelFont and uses the sans estimate.
                lchars = max([len(str(r.get("label") or "")) for r in rows] + [0])
                label_w = lchars * (CHAR_W if "labelFont" in L else SANS_CHAR_EM) * L.get("labelFont", L["font"])
                if not L.get("fits", True) or L["cell"] < L["font"] or need_w > L.get("cellW", L["cell"]) + 0.5:
                    out["fails"].append(f"{where}: {L['font']:g} px text cannot fit a {L.get('cellW', L['cell'])} px cell (longest value {longest} "
                                        f"character(s), about {need_w:.0f} px wide); use fewer columns or rows, or shorter values")
                elif L["cell"] < L["font"] + 8:
                    out["warns"].append(f"{where}: cell {L['cell']} px is tight for {L['font']:g} px text; fewer rows or no scene title")
                if label_w > L["labelW"] + 0.5 or ("labelFont" in L and lchars and L["labelFont"] < MIN_TEXT_PX):
                    out["fails"].append(f"{where}: a row label of {lchars} characters needs {label_w:.0f} px at "
                                        f"{L.get('labelFont', L['font']):g} px in the {L['labelW']} px label column (text under "
                                        f"{MIN_TEXT_PX} px or overflow); shorten the row labels")
                for val, fill in (panel.get("valueColors") or {}).items():
                    rgb = color_rgb(fill)
                    if rgb is None:
                        out["warns"].append(f"{where}: valueColors {val!r} {fill!r} is not a hex colour; contrast not checked")
                    elif contrast(bg, rgb) < CONTRAST_MIN:
                        out["fails"].append(f"{where}: cell text on {val!r} fill {fill} has contrast {contrast(bg, rgb):.1f}:1 (under 4.5:1)")
        elif sc.get("type") == "matrix":  # W16: matrixLayout.ts, ported in pe_common
            L = pc.matrix_layout(p)
            where = f"{sid} matrix"
            out["read"].append(f"{where}: {len(p.get('columns') or [])} x {len(p.get('rows') or [])}, cell {L['cellW']} x {L['cellH']} px, text {L['font']} px")
            for msg in pc.matrix_problems(p):
                out["fails"].append(f"{where}: {msg}")
            if L["fits"] and L["font"] < PHONE_TEXT_PX:
                out["phone"].append(f"{where}: text {L['font']} px (phone needs {PHONE_TEXT_PX})")
        elif sc.get("type") == "diagram" and not p.get("svg"):
            els = [e for e in p.get("elements") or [] if isinstance(e, dict)]
            texts = [e for e in els if e.get("kind") == "text"]
            vb = p.get("viewBox") or DIAGRAM_VIEWBOX
            scale = _svg_box(vb, bool(p.get("title")))
            from_frame = pc.ms_to_frame(sc.get("startMs", 0), fps)
            end = pc.ms_to_frame(sc.get("endMs", 0), fps) - from_frame - 1
            steps = p.get("steps") or []
            cues = [pc.cue_frame(s.get("atMs"), 15 + i * 45, from_frame, fps) for i, s in enumerate(steps)]
            reveal_at: dict[str, int] = {}
            hidden_end: set[str] = set()  # a step `hide` list (when the template has it) at or before the end
            for i, s in enumerate(steps):
                for eid in s.get("reveal") or []:
                    reveal_at.setdefault(eid, cues[i])
                if cues[i] <= end:
                    hidden_end |= set(s.get("hide") or [])
                    hidden_end -= set(s.get("reveal") or [])
            active = max([i for i, c in enumerate(cues) if c <= end], default=-1)
            hi = set(steps[active].get("highlight") or []) if active >= 0 else set()
            sizes = []
            for e in texts:
                eid = e.get("id")
                units = max(MIN_TEXT_PX, MIN_TEXT_PX / scale, e.get("fontSize") if isinstance(e.get("fontSize"), (int, float)) else 30)
                px = units * scale
                sizes.append(px)
                where = f"{sid} diagram text {eid} {str(e.get('text', ''))[:32]!r}"
                if px < MIN_TEXT_PX - 0.05:
                    out["fails"].append(f"{where} renders at {px:.1f} px")
                elif px < PHONE_TEXT_PX - 0.05:
                    out["phone"].append(f"{where} renders at {px:.1f} px (phone needs {PHONE_TEXT_PX})")
                fill = e.get("fill") or THEME_COLORS["text"]
                rgb = color_rgb(fill)
                if rgb is None:
                    out["warns"].append(f"{where}: fill {fill!r} is not a hex colour; contrast not checked")
                    continue
                c = contrast(rgb, bg)
                if c < CONTRAST_MIN:
                    out["fails"].append(f"{where}: fill {fill} has contrast {c:.1f}:1 on {THEME_COLORS['bg']} (under 4.5:1)")
                shown = (reveal_at.get(eid) is None or reveal_at[eid] <= end) and eid not in hidden_end
                if shown and hi and eid not in hi:
                    eff = contrast(blend(rgb, bg, 1 - DIAGRAM_DIM), bg)
                    if eff < CONTRAST_MIN:
                        out["warns"].append(f"{where}: shown dimmed (opacity {1 - DIAGRAM_DIM:.2f}) at the end of the scene, "
                                            f"fill {fill} drops to {eff:.1f}:1 (under 4.5:1)")
            out["read"].append(f"{sid} diagram: {len(texts)} inline text element(s)" +
                               (f", {min(sizes):.0f} to {max(sizes):.0f} px (stage scale {scale:.2f})" if sizes else ""))
    return out


def builtin_component_files(ep: Episode, m: dict) -> list[tuple[str, Path]]:
    """Renderer files whose text this episode shows: SpeakerRail and ChapterLabel always, KeywordChips
    with chips, PauseCue with holds, CompareScene with a compare scene (titles, pills, banners). The
    episode's Remotion project first, else the skill template."""
    want = ["components/SpeakerRail.tsx", "components/ChapterLabel.tsx"]
    if m.get("overlays"):
        want.append("components/KeywordChips.tsx")
    if m.get("holds"):
        want.append("components/PauseCue.tsx")
    if any(sc.get("type") == "compare" for sc in m.get("scenes", [])):
        want.append("scenes/CompareScene.tsx")
    out = []
    for rel in want:
        for root in (ep.remotion, SKILL / "templates" / "remotion"):
            f = root / "src" / rel
            if f.is_file():
                out.append((rel, f))
                break
    return out


def text_size(ep: Episode) -> list[dict]:
    """text.minsize: text under 28 px or under 4.5:1 contrast in custom components (fontSize),
    diagram SVG files (font-size after the stage scale), compare tables (tableLayout.ts port) and
    diagram inline text (size after the stage scale, fill contrast, dimming at the scene end).
    text.phone: the same sources against the phone threshold (36 px, 8 cells per row): a fail
    when brief.json viewing is phone, else a warning. Neither check is ever skipped."""
    m = ep.need_manifest()
    scale_type = _theme_type(ep.remotion)
    fails, warns, phone, read = [], [], [], []
    n_custom = n_svg = 0
    comps = {(sc.get("props") or {}).get("component") for sc in m.get("scenes", []) if sc.get("type") == "custom"} - {None}
    for name, f in sorted(_custom_files(ep.remotion, comps).items()):
        if f is None:
            warns.append(f"custom component {name}: no file under {ep.remotion / 'src' / 'scenes' / 'custom'}; cannot read its sizes")
            continue
        n_custom += 1
        a, b = custom_font_problems(f, scale_type)
        fails += a
        warns += b
        phone += [x for x in custom_font_problems(f, scale_type, PHONE_TEXT_PX)[0] if x not in a]
    seen = set()
    for sc in m.get("scenes", []):
        p = sc.get("props") or {}
        if sc.get("type") != "diagram" or not p.get("svg") or (p["svg"], bool(p.get("title"))) in seen:
            continue
        seen.add((p["svg"], bool(p.get("title"))))
        try:
            f = pc.safe_path(ep.dir, ep.dir / p["svg"], f"scene {sc.get('id')} diagram")
        except pc.BadId as e:
            warns.append(f"{e}; cannot read its sizes")
            continue
        if not f.is_file():
            warns.append(f"scene {sc.get('id')}: {f} not found; cannot read its sizes")
            continue
        n_svg += 1
        a, b = svg_font_problems(f, bool(p.get("title")))
        fails += a
        warns += b
        phone += [x for x in svg_font_problems(f, bool(p.get("title")), PHONE_TEXT_PX)[0] if x not in a]
    read += ([f"{n_custom} custom component file(s)"] if n_custom else []) + ([f"{n_svg} SVG diagram file(s)"] if n_svg else [])
    bt = builtin_text(ep)
    fails += bt["fails"]
    warns += bt["warns"]
    phone += bt["phone"]
    read += bt["read"]
    # R01: every other built-in text the episode draws (speaker rail, chapter label, chips, pause card,
    # compare titles, pills and banners), read from the renderer source against the phone threshold.
    bfiles = builtin_component_files(ep, m)
    for rel, f in bfiles:
        phone += [f"built-in {x}" for x in custom_font_problems(f, scale_type, PHONE_TEXT_PX)[0]]
    bnote = (f"; phone check also read {len(bfiles)} built-in component file(s) ({', '.join(Path(r).stem for r, _ in bfiles)})"
             if bfiles else "")
    kinds = sorted({sc.get("type") for sc in m.get("scenes", [])} - {None})
    what = ("; ".join(read) if read else
            f"no custom component, SVG file, compare table or inline diagram text among {len(m.get('scenes', []))} scene(s) "
            f"({', '.join(kinds) or 'none'}); the other built-in scenes use theme.ts type.* sizes of {MIN_TEXT_PX} px or more")
    status = "fail" if fails else "warn" if warns else "pass"
    detail = (f"{len(fails)} problem(s) (under {MIN_TEXT_PX} px or contrast under 4.5:1): " + "; ".join(fails[:6]) if fails else
              f"{len(warns)} to check by eye: " + "; ".join(warns[:6]) if warns else
              f"every size is {MIN_TEXT_PX} px or more and every fill 4.5:1 or more")
    if fails and warns:
        detail += f"; also {len(warns)} to check by eye: " + "; ".join(warns[:3])
    detail += f". Read: {what}{bnote}"
    fix = ("raise each size to type.label (30) or more; in a custom component use type.* from theme.ts; in an SVG file "
           "raise font-size so size x stage scale >= 28, or narrow the viewBox; give diagram text a theme colour "
           "(text, muted, accent) so it reaches 4.5:1" if fails else
           "check these on the contact sheet; prefer type.* sizes or Math.max(type.min, ...); keep the text the hosts "
           "still talk about in the last step's highlight, or give it a brighter fill" if warns else "")
    out = [check("text.minsize", status, detail, fix)]
    viewing, note = read_viewing(ep)
    pstatus = ("fail" if viewing == "phone" else "warn") if phone else "pass"
    pdetail = (f"viewing {viewing}: {len(phone)} phone readability finding(s) (text under {PHONE_TEXT_PX} px at 1080p, or more "
               f"than {MAX_BAND_COLS} cells per row): " + "; ".join(phone[:6]) if phone else
               f"viewing {viewing}: no text under {PHONE_TEXT_PX} px and no grid over {MAX_BAND_COLS} cells per row in what text.minsize read")
    if note:
        pdetail += f" ({note})"
    pfix = ("" if not phone else
            "re-render with the current template (compare tables wrap into bands of 8 or fewer at type.grid 36 px); raise "
            "diagram and custom text to 36 px or more; built-in text under 36 px needs a template with a phone type scale"
            + ("" if viewing == "phone" else
            "; a warning only, because brief.json viewing is desktop (judge readability on contact-sheet-720-*.png)"))
    out.append(check("text.phone", pstatus, pdetail, pfix))
    return out


# ------------------------------------------------------------------------------------------- labels.counts

COUNT_MOVE_RE = re.compile(r"\b(move|moved|moves|moving|miss|misses|missed|change|changes|changed|stay|stays|stayed|keep|keeps|kept)\b", re.I)
COUNT_SAME_RE = re.compile(r"\b(stay|stays|stayed|keep|keeps|kept)\b", re.I)
X_OF_Y_RE = re.compile(r"(?<![\d.])(\d+)\s+of\s+(\d+)(?![\d.])")
P_TO_Q_RE = re.compile(r"(?<![\d.])(\d+)\s*(?:to|→|->)\s*(\d+)(?![\d.])", re.I)
MOD_P_RE = re.compile(r"\bmod\s*(\d+)\b", re.I)
SERVER_RE = re.compile(r"\b(servers?|nodes?|robots?|machines?|shards?|fleet)\b", re.I)
GENERAL_RE = re.compile(r"\bgeneral\b|\bany\s+n\b|\be\.g\b", re.I)
FIXED_RE = re.compile(r"\bfixed\s+(fleet|n|count|number|size|set)\b|\bn\s+fixed\b|\b(fleet|count|n)\s+(is\s+|stays\s+)?fixed\b", re.I)
CHANGING_RE = re.compile(r"\b(chang\w*|grow\w*|shrink\w*|elastic)\s+(fleet|n|count|number|size)\b|\b(fleet|count)\s+(chang\w*|grow\w*)", re.I)
_NAME_STOP = {"the", "a", "an", "of", "n", "k", "hash", "key", "keys", "job", "jobs"}


def _name_words(panel: dict) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", f"{panel.get('title', '')} {panel.get('tag', '')}".lower()) if w not in _NAME_STOP}


def _table_facts(panel: dict, st: dict) -> dict | None:
    """Counts from a two-row table at one frame: differing and equal columns among the columns
    filled (not '?') in both visible rows; exact when every column is filled in both. `to` maps a
    value to the number of columns that change TO it (before != after, after == value)."""
    rows = st["rows"]
    if panel.get("kind") != "table" or len(rows) != 2:
        return None
    n = len(panel.get("columns") or []) or max(len(r["cells"]) for r in rows)
    a, b = rows
    vis = a["visible"] and b["visible"]
    both = [i for i in range(min(len(a["cells"]), len(b["cells"]))) if vis and a["cells"][i] != "?" and b["cells"][i] != "?"]
    mods = [int(x.group(1)) for r in rows if (x := MOD_P_RE.search(str(r.get("label") or "")))]
    to: dict[str, int] = {}
    to_exact: dict[str, int] = {}
    for i in both:
        if a["cells"][i] != b["cells"][i]:
            k = str(b["cells"][i]).lower()
            to[k] = to.get(k, 0) + 1
            to_exact[str(b["cells"][i])] = to_exact.get(str(b["cells"][i]), 0) + 1
    return {"n": n, "diff": sum(1 for i in both if a["cells"][i] != b["cells"][i]),
            "same": sum(1 for i in both if a["cells"][i] == b["cells"][i]), "filled": len(both),
            "exact": vis and len(both) == n, "mods": mods if len(mods) == 2 and vis else [],
            "labels": [r.get("label") for r in rows], "to": to, "toExact": to_exact}


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<=[.;])\s+|\s+[|·]\s+", text) if c.strip()]


# R02: automatic hard failures only for unambiguous wording. "X of Y move(d)", "moves X of Y",
# "X of Y stay", "X of Y move to V" (columns that change TO value V) are unambiguous; "miss" and
# other verbs are checked but a mismatch only warns. A structured `claim` on a chip or banner
# ({kind: count, of, scope: columns-changed | cells-changed-to, value, to, side}) is always exact.
MOVE_TO_RE = re.compile(r"\b(?:move|moves|moved|moving|change|changes|changed|go|goes|went)\s+(?:to|into)\s+([A-Za-z0-9]+)\b", re.I)
AMBIGUOUS_VERB_RE = re.compile(r"\b(miss|misses|missed)\b", re.I)


def _claim_check(claim: dict, tf: dict) -> tuple[bool, str] | None:
    """(true?, computed) for a structured count claim against one table's facts, or None when the
    claim is not a supported count claim."""
    if not isinstance(claim, dict) or claim.get("kind") != "count":
        return None
    scope, val, of = claim.get("scope"), claim.get("value"), claim.get("of")
    if scope == "columns-changed":
        got = tf["diff"]
        what = f"{got} of {tf['n']} columns changed"
    elif scope == "cells-changed-to":
        got = tf["toExact"].get(str(claim.get("to", "")), 0)
        what = f"{got} of {tf['n']} columns change to {claim.get('to')!r}"
    else:
        return None
    return (got == val and (of is None or of == tf["n"])), what


def label_findings(m: dict, scene: dict) -> tuple[list[dict], list[str], list[str]]:
    """(findings, verified, unchecked) for one compare scene. Each finding: t (ms), side, text,
    computed, exact (a hard failure), kind. Label sources: panel stat, title and tag (static and
    per step), banner text and pill labels, chips over the scene."""
    p = scene.get("props") or {}
    fps = (m.get("video") or {}).get("fps") or FPS
    from_frame = pc.ms_to_frame(scene.get("startMs", 0), fps)
    end = pc.ms_to_frame(scene.get("endMs", 0), fps) - from_frame
    sides = {s: p.get(s) for s in ("left", "right") if isinstance(p.get(s), dict)}
    if not any(pn.get("kind") == "table" for pn in sides.values()):
        return [], [], []
    frames = {0}
    for pn in sides.values():
        for s in pn.get("steps") or []:
            if (a := pc.answer_frame(s.get("atMs"), from_frame, fps)) is not None:
                frames.add(a)
        for r in pn.get("rows") or []:
            if (a := pc.answer_frame(r.get("atMs"), from_frame, fps)) is not None:
                frames.add(a)
        frames.update(pc._fallback(i) for i in range(len(pn.get("steps") or [])))
    for b in ([p["verdict"]] if p.get("verdict") else []) + list(p.get("banners") or []):
        if (a := pc.answer_frame(b.get("atMs"), from_frame, fps)) is not None:
            frames.add(a)
    chips = [ov for ov in m.get("overlays") or [] if ov.get("startMs", 0) < scene.get("endMs", 0) and ov.get("endMs", 0) > scene.get("startMs", 0)]
    for ov in chips:
        frames.add(max(0, pc.ms_to_frame(ov["startMs"], fps) - from_frame))
    names = {s: _name_words(pn) for s, pn in sides.items()}
    vtimes = pc.visual_step_times(m)
    findings, verified, unchecked, seen = [], [], [], set()

    def add(t_ms, side, text, computed, exact, kind):
        key = (side, text, computed)
        if key not in seen:
            seen.add(key)
            findings.append({"t": t_ms, "side": side, "text": text, "computed": computed, "exact": exact, "kind": kind})

    for f in sorted(x for x in frames if 0 <= x < end):
        t_ms = (from_frame + f) / fps * 1000
        banner = pc.banner_at(p, from_frame, fps, f)
        states = {s: pc.panel_state_at(pn, from_frame, fps, f) for s, pn in sides.items()}
        facts = {s: _table_facts(pn, states[s]) for s, pn in sides.items()}
        texts = []  # (text, side or None for scene-wide, claim or None)
        for s, pn in sides.items():
            st = states[s]
            if st["stat"]:
                texts.append((st["stat"]["text"], s, st["stat"].get("claim")))
            for k in ("title", "tag"):  # R02: titles and tag pills state counts too
                if st.get(k):
                    texts.append((st[k], s, None))
            if banner and banner["labels"].get(s):
                texts.append((banner["labels"][s], s, None))
        if banner and banner.get("text"):
            cl = banner.get("claim")
            texts.append((banner["text"], cl.get("side") if isinstance(cl, dict) else None, cl))
        for ov in chips:
            pr = ov.get("props") or {}
            ca, cb, _ = pc.chip_frames(ov, vtimes, fps)  # the renderer's chip window (expiry applied)
            if ca <= from_frame + f < cb and pr.get("text"):
                cl = pr.get("claim")
                texts.append((pc.claim_fill(pr["text"], cl), cl.get("side") if isinstance(cl, dict) else None, cl))
        for text, side, claim in texts:
            targets = [side] if side else [s for s in sides if facts.get(s)]
            if claim is not None and not side and len(targets) > 1:
                unchecked.append(f"{scene.get('id')} '{text}' (claim names no side and the scene has two tables)")
                continue
            if (why := pc.claim_text_problem(text, claim)):
                # Q05: a true structured claim never certifies contradictory displayed text.
                add(t_ms, side or "-", text, why + "; write the text from the claim", True, "count")
                unchecked.append(f"{scene.get('id')} '{text}' (text contradicts its claim)")
                continue
            for s in targets:
                tf = facts.get(s)
                if not tf:
                    continue
                if claim is not None:
                    res = _claim_check(claim, tf)
                    if res is None:
                        unchecked.append(f"{scene.get('id')} {s} '{text}' (claim kind/scope not supported)")
                    elif not tf["exact"]:
                        unchecked.append(f"{scene.get('id')} {s} '{text}' (claim; table not fully filled yet)")
                    else:
                        (verified if res[0] else unchecked).append(f"{scene.get('id')} {s} '{text}' (claim {'ok' if res[0] else 'MISMATCH'})")
                        if not res[0]:
                            add(t_ms, s, text, res[1], True, "count")
                    continue
                other = set().union(*[names[o] for o in sides if o != s]) - names[s]
                for cl in _clauses(text):
                    words = set(re.findall(r"[a-z]+", cl.lower()))
                    named_other = side is None and bool(words & other) and not (words & (names[s] - other))
                    named_this = side is not None or bool(words & (names[s] - other))
                    if named_other:
                        continue
                    general = bool(GENERAL_RE.search(text))
                    for mm in X_OF_Y_RE.finditer(cl):
                        if not COUNT_MOVE_RE.search(cl):
                            continue
                        x, y = int(mm.group(1)), int(mm.group(2))
                        same = bool(COUNT_SAME_RE.search(cl))
                        to = MOVE_TO_RE.search(cl)
                        if to and not same:
                            val = tf["to"].get(to.group(1).lower(), 0)
                            what = f"changing to {to.group(1)!r}"
                        else:
                            val = tf["same"] if same else tf["diff"]
                            what = "equal" if same else "differing"
                        comp = f"{val} of {tf['n']} columns {what} ({tf['labels'][0]} vs {tf['labels'][1]}" + (
                            "" if tf["exact"] else f", only {tf['filled']} of {tf['n']} filled") + ")"
                        ok = (x, y) == (val, tf["n"])
                        unambiguous = tf["exact"] and named_this and not AMBIGUOUS_VERB_RE.search(cl)
                        line = f"{scene.get('id')} {s} '{text}' ({'ok' if ok else 'MISMATCH'})"
                        (verified if ok and tf["exact"] else unchecked).append(line if tf["exact"] else line + " [table not fully filled]")
                        if not ok:
                            add(t_ms, s, text, comp, unambiguous, "count")
                    if tf["mods"] and not general:
                        named = [(int(a), int(b)) for a, b in P_TO_Q_RE.findall(cl)] if (COUNT_MOVE_RE.search(cl) or SERVER_RE.search(cl)) else []
                        bad = [f"{a} to {b}" for a, b in named if sorted((a, b)) != sorted(tf["mods"])]
                        bad += [f"mod {q}" for q in map(int, MOD_P_RE.findall(cl)) if q not in tf["mods"]]
                        if named or MOD_P_RE.search(cl):
                            (unchecked if bad else verified).append(f"{scene.get('id')} {s} '{text}' ({'MISMATCH' if bad else 'ok'})")
                        if bad:
                            add(t_ms, s, text, f"names {', '.join(bad)} but the table rows are {tf['labels'][0]} and "
                                f"{tf['labels'][1]}; add 'in general' or 'e.g.' if it is the general case", False, "servers")
                    if tf["mods"] and len(set(tf["mods"])) == 2 and FIXED_RE.search(cl) and not CHANGING_RE.search(text):
                        unchecked.append(f"{scene.get('id')} {s} '{text}' (MISMATCH)")
                        add(t_ms, s, text, f"says the fleet is fixed but the table shows {tf['labels'][0]} to {tf['labels'][1]}", False, "fleet")
    verified = list(dict.fromkeys(verified))
    unchecked = [u for u in dict.fromkeys(unchecked) if u not in verified]
    return findings, verified, unchecked


def labels_counts(ep: Episode) -> list[dict]:
    """labels.counts (J11, automated part): a stat, title, tag, pill label, banner or chip that states
    a count must be true of the compare table on the frames where it shows. A mismatch in
    unambiguous wording (or a structured `claim`) on a fully filled table fails; other mismatches
    warn. Labels are reported as verified or unchecked, never mixed."""
    m = ep.need_manifest()
    turns = sorted(m.get("turns", []), key=lambda t: t.get("startMs", 0))

    def turn_at(ms):
        tid = None
        for t in turns:
            if t.get("startMs", 0) <= ms:
                tid = t.get("id")
        return tid

    fails, warns, verified, unchecked, tables = [], [], [], [], 0
    for sc in m.get("scenes", []):
        if sc.get("type") != "compare":
            continue
        p = sc.get("props") or {}
        tables += sum(1 for s in ("left", "right") if (p.get(s) or {}).get("kind") == "table")
        f, v, u = label_findings(m, sc)
        verified += v
        unchecked += u
        for x in f:
            line = (f"{mmss(x['t'])[:5]} {sc.get('id')} {x['side']} ({turn_at(x['t'])}): '{x['text']}' -> {x['computed']}")
            (fails if x["kind"] == "count" and x["exact"] else warns).append(line)
    ep.labels_checked = verified
    ep.labels_unchecked = unchecked
    if not tables:
        return [check("labels.counts", "pass", "no compare table panel: no count label can be computed; J11 stays with the judge")]
    status = "fail" if fails else "warn" if warns else "pass"
    detail = (f"{len(fails)} count(s) that the table contradicts: " + "; ".join(fails[:6]) if fails else "")
    if warns:
        detail += ("; " if detail else "") + f"{len(warns)} label(s) to fix or justify: " + "; ".join(warns[:6])
    if not detail:
        detail = f"{len(verified)} label(s) verified against {tables} compare table(s), all true: " + "; ".join(verified[:6])
    else:
        detail += f". Verified {len(verified)} label(s) on {tables} table(s)"
    if unchecked:
        detail += f"; {len(unchecked)} unchecked (ambiguous wording or a partly filled table; the judge checks them): " + "; ".join(unchecked[:4])
    fix = ("" if status == "pass" else
           "make each stat, title, tag, pill label, banner and chip true of the table on the frames where it shows: change the "
           "count, change the rows (for example k mod 5 and k mod 6), move the text to a scene whose table shows it, "
           "mark the general case ('in general', 'e.g.'), or state the claim exactly ('X of Y move to D')")
    return [check("labels.counts", status, detail, fix)]


# ------------------------------------------------------------------------------------------- labels.stale

# v3, v4 and v5 judges each found a chip or label that outlived the world step behind it ("keys per
# server: 4 each" still on screen after server D joined). labels.stale: a quantity label set at
# world step S and still drawn after a later step reveals or hides a node it counts is an error,
# unless the label says `persist: true` or is updated within STALE_GRACE_MS of that step.
STALE_GRACE_MS = 3000
_NUM_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
              "half", "twice", "double"}
QUANTITY_RE = re.compile(r"\d|\b(per|each)\b|\b(" + "|".join(sorted(_NUM_WORDS)) + r")\b", re.I)


COUNT_WORD_RE = re.compile(r"\d|\b(" + "|".join(sorted(_NUM_WORDS)) + r")\b", re.I)


def is_quantity_label(text: str) -> bool:
    """A label that states a quantity: a number (or per, each) together with a word of 3+ letters
    ("keys per server: 4 each", "D's keys 3"). A bare number or a letter is an id ("7", "B")."""
    t = str(text or "")
    return bool(QUANTITY_RE.search(t)) and bool(re.search(r"[A-Za-z]{3,}", re.sub(r"\b(per|each)\b", "", t, flags=re.I)))


def _label_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _related(node: dict, words: set[str]) -> bool:
    """A revealed or hidden node changes a quantity label when it is a countable ring node (it has a
    role: owner or item) or its label is a word of the label text ("D's keys" and node D)."""
    if node.get("role"):
        return True
    lw = _label_words(node.get("label"))
    return bool(lw) and lw <= words and not lw <= {"the", "a", "of"}


def renderer_expires_labels(remotion: Path) -> bool:
    """True when the Remotion project ends labels at the next step unless persist (W11b,
    overlayState.ts). A project without its own visibleText.ts is judged by the skill template."""
    src = remotion / "src"
    if (src / "visibleText.ts").is_file():
        return (src / "overlayState.ts").is_file()
    return (SKILL / "templates" / "remotion" / "src" / "overlayState.ts").is_file()


def _stale_world(world: dict, timeline: list[dict], where: str, expiring: bool = False) -> list[dict]:
    """Stale node labels in one world timeline (the episode world or a compare panel's own world)."""
    nodes = {n.get("id"): n for n in world.get("nodes") or [] if isinstance(n, dict)}
    out = []
    # Instances: a node's label/value is (re)set by its reveal or by a `set` patch on it.
    sets: dict[str, list[tuple[float, bool]]] = {}
    for nid, n in nodes.items():
        r = n.get("revealAtMs")
        sets.setdefault(nid, []).append((r if pc._num(r) else -math.inf, bool(n.get("persist"))))
    for st in timeline:
        for nid in st.get("reveal") or []:
            if nid in nodes:
                sets.setdefault(nid, []).append((st["t"], bool(nodes[nid].get("persist"))))
        for nid, patch in (st.get("set") or {}).items():
            if nid in nodes:
                sets.setdefault(nid, []).append((st["t"], bool((patch or {}).get("persist")) or bool(nodes[nid].get("persist"))))
    hides = {nid: sorted(st["t"] for st in timeline if nid in (st.get("hide") or [])) for nid in nodes}
    for qid, inst in sets.items():
        if nodes[qid].get("role"):
            continue  # a counted ring node (owner, item) is not a label about a count
        inst = sorted(set(inst), key=lambda x: x[0])
        for k, (s0, persist) in enumerate(inst):
            if expiring and not persist:
                continue  # the renderer ends it at the next step: it cannot outlive a change
            nxt = inst[k + 1][0] if k + 1 < len(inst) else math.inf
            hid = next((h for h in hides.get(qid, []) if h > s0), math.inf)
            e0 = min(nxt, hid)
            if not pc.world_visible_ids(world, timeline, max(s0, -1e12) + 1) & {qid} and s0 != -math.inf:
                continue
            ov = pc.node_overrides(timeline, s0 + 1) .get(qid, {}) if s0 != -math.inf else {}
            label = ov.get("label") if ov.get("label") is not None else nodes[qid].get("label")
            value = ov.get("value") if "value" in ov else nodes[qid].get("value")
            text = " ".join(str(x) for x in (label, nodes[qid].get("sublabel"), value) if x not in (None, ""))
            if not is_quantity_label(text):
                continue
            words = _label_words(text)
            for st in timeline:
                t = st["t"]
                if not (s0 < t < e0) or e0 - t <= STALE_GRACE_MS:
                    continue
                if qid in (st.get("set") or {}):
                    continue
                changed = [i for i in (st.get("reveal") or []) + (st.get("hide") or []) if i in nodes and i != qid and _related(nodes[i], words)]
                if changed:
                    out.append({"t": t, "where": where, "label": text, "setMs": s0, "untilMs": e0, "changed": changed[:4], "persist": persist})
                    break
    if expiring:
        # Q03 (codex round 4): a node's own label and sublabel NEVER expire (only values and `set`
        # patches do), so check that permanent text on its own, whatever the node's persist flag.
        reported = {x["label"] for x in out}
        for qid, n in nodes.items():
            if n.get("role"):
                continue
            perm = " ".join(str(x) for x in (n.get("label"), n.get("sublabel")) if x not in (None, ""))
            # A permanent caption such as "keys per server" names a quantity but states none; only a
            # number (digits or a number word) in a base label can go stale.
            if not is_quantity_label(perm) or not COUNT_WORD_RE.search(perm) or perm in reported:
                continue
            words = _label_words(perm)
            for st in timeline:
                t = st["t"]
                changed = [i for i in (st.get("reveal") or []) + (st.get("hide") or []) if i in nodes and i != qid and _related(nodes[i], words)]
                if not changed:
                    continue
                later = t + STALE_GRACE_MS + 1
                if qid not in pc.world_visible_ids(world, timeline, t) or qid not in pc.world_visible_ids(world, timeline, later):
                    continue
                ov = pc.node_overrides(timeline, later).get(qid, {})
                if ov.get("labelSet") and ov.get("label") is not None and not n.get("sublabel"):
                    continue  # a live `set` label covers the base label there
                hid = next((h for h in hides.get(qid, []) if h > t), math.inf)
                out.append({"t": t, "where": where, "label": perm, "setMs": n.get("revealAtMs") if pc._num(n.get("revealAtMs")) else -math.inf,
                            "untilMs": hid, "changed": changed[:4], "persist": False, "permanent": True})
                break
    return out


def labels_stale(ep: Episode) -> list[dict]:
    """labels.stale: world labels, chips and compare banners that state a quantity (a number, per,
    each) must not stay on screen after a world step changes what they count."""
    m = ep.need_manifest()
    expiring = renderer_expires_labels(ep.remotion)
    timeline = pc.world_timeline(m)
    world = m.get("world") or {}
    found = _stale_world(world, timeline, "world", expiring) if world else []
    nodes = {n.get("id"): n for n in world.get("nodes") or [] if isinstance(n, dict)}
    n_chips = n_banners = 0
    for ov in m.get("overlays") or []:
        pr = ov.get("props") or {}
        text = str(pr.get("text") or "")
        if not is_quantity_label(text) or (expiring and not pr.get("persist")):
            continue
        n_chips += 1
        words = _label_words(text)
        for st in timeline:
            t = st["t"]
            if ov["startMs"] < t < ov["endMs"] - STALE_GRACE_MS:
                changed = [i for i in (st.get("reveal") or []) + (st.get("hide") or []) if i in nodes and _related(nodes[i], words)]
                if changed:
                    found.append({"t": t, "where": f"chip {ov.get('id')}", "label": text, "setMs": ov["startMs"], "untilMs": ov["endMs"],
                                  "changed": changed[:4], "persist": bool(pr.get("persist"))})
                    break
    for sc in m.get("scenes", []):
        if sc.get("type") != "compare":
            continue
        p = sc.get("props") or {}
        bl = sorted([b for b in ([p["verdict"]] if p.get("verdict") else []) + list(p.get("banners") or []) if pc._num(b.get("atMs"))],
                    key=lambda b: b["atMs"])
        for side in ("left", "right"):
            pn = p.get(side) or {}
            if pn.get("kind") != "world":
                continue
            shared = pn.get("world") == "shared"
            w = world if shared else (pn.get("world") if isinstance(pn.get("world"), dict) else {})
            tl = [x for x in timeline if x.get("sceneId") == sc.get("id")] if shared else pc.local_timeline(pn.get("steps") or [], sc.get("id"), sc.get("startMs", 0))
            wn = {n.get("id"): n for n in (w or {}).get("nodes") or [] if isinstance(n, dict)}
            if not shared and w:
                found += _stale_world(w, tl, f"{sc.get('id')} {side} panel", expiring)
            for i, b in enumerate(bl):
                text = " ".join(str(x) for x in [b.get("text")] + list((b.get("labels") or {}).values()) if x)
                if not is_quantity_label(text) or (expiring and not b.get("persist")):
                    continue
                n_banners += 1
                e0 = bl[i + 1]["atMs"] if i + 1 < len(bl) else sc.get("endMs", math.inf)
                words = _label_words(text)
                for st in tl:
                    if b["atMs"] < st["t"] < e0 - STALE_GRACE_MS:
                        changed = [x for x in (st.get("reveal") or []) + (st.get("hide") or []) if x in wn and _related(wn[x], words)]
                        if changed:
                            found.append({"t": st["t"], "where": f"{sc.get('id')} banner", "label": text, "setMs": b["atMs"], "untilMs": e0,
                                          "changed": changed[:4], "persist": bool(b.get("persist"))})
                            break
    lines = [f"{mmss(x['t'])[:5]} {x['where']}: '{x['label'][:40]}' (set {mmss(x['setMs'])[:5] if x['setMs'] != -math.inf else 'at start'}) "
             f"still shows after {', '.join(x['changed'])} {'appear or disappear' if len(x['changed']) > 1 else 'appears or disappears'}"
             + (f", until {mmss(x['untilMs'])[:5]}" if x["untilMs"] != math.inf else ", to the end") for x in found]
    hard = [ln for ln, x in zip(lines, found) if not x["persist"]]
    soft = [ln for ln, x in zip(lines, found) if x["persist"]]
    if hard:
        return [check("labels.stale", "fail", f"{len(hard)} quantity label(s) outlive the world step they describe: " + "; ".join(hard[:6])
                      + (f"; also {len(soft)} persist label(s) to confirm" if soft else ""),
                      "update the label in the same world step (a `set` on that node, or end the chip there), hide it, or "
                      "re-render with the current template (labels end at the next step unless persist). A node's own label "
                      "and sublabel never expire: move a count out of them into `value` or a `set` patch")]
    if soft:
        return [check("labels.stale", "warn", f"{len(soft)} label(s) marked persist: true stay on screen while the world changes what "
                      "they count; confirm each is still true: " + "; ".join(soft[:6]),
                      "drop persist (the label then ends at the next step) or `set` the new value in the changing step")]
    return [check("labels.stale", "pass", f"no quantity label outlives its world step ({'labels end at the next step unless persist; ' if expiring else ''}world labels, {n_chips} quantity chip(s), "
                  f"{n_banners} quantity banner(s) over world panels checked; grace {STALE_GRACE_MS / 1000:g} s)")]


# ------------------------------------------------------------------------------------------- all, reports

LEARN_OUTPUTS = ["selftest.md", "teachback.md", "cards.csv", "cards.md", "summary.md"]  # gaplog.md is the learner's


def glossary_digest(ep: Episode) -> str | None:
    """Digest of the resolved glossary (transcript.json `glossary`, which merges glossary.json,
    outline newTerms and learn.json summary.terms)."""
    tj = ep._load("transcript.json") if (ep.dir / "transcript.json").is_file() else None
    if not tj:
        return None
    return pc.bytes_sha(json.dumps(tj.get("glossary") or [], sort_keys=True, ensure_ascii=False).encode(), 64)


def build_identity(ep: Episode) -> dict:
    """sha256 digests of everything the judge reviews, and of the mp4 under review (N01, N06).
    `id` names this build: a change to the script, audio, scenes, facts, learn material, transcript,
    glossary or the mp4 (chapters included) makes a new build that needs new scores."""
    files = {"script": ep.dir / "script.json", "scenes": ep.dir / "scenes.json", "timing": ep.dir / "timing.json",
             "episode": ep.dir / "episode.json", "audio": ep.dir / "audio" / "episode.wav",
             "facts": ep.dir / "facts.json", "outline": ep.dir / "outline.json", "learn": ep.dir / "learn.json",
             "transcript": ep.dir / "transcript.json", "glossaryFile": ep.dir / "glossary.json"}
    inputs = {k: pc.json_digest(p) for k, p in files.items()}
    inputs["learnFiles"] = {n: pc.json_digest(ep.dir / "learn" / n) for n in LEARN_OUTPUTS}
    inputs["glossary"] = glossary_digest(ep)
    # R04: the review-relevant brief fields (viewing, depth, minutes, learnerLevel, lexicon, outcome) and
    # the designated held-out item change what the reviewers judge against, so they are part of the build.
    try:
        brief = ep._load("brief.json")
        learn = ep._load("learn.json")
    except QcError:
        brief, learn = None, None
    inputs["review"] = pc.review_brief_digest(brief, learn)
    # N06: the recorded digests of every delivered transcript, caption, library and sidecar file.
    inputs["delivery"] = pc.json_digest(ep.dir / pc.DELIVERY_FILE)
    mp4 = pc.file_sha(ep.mp4, 64) if ep.mp4.is_file() else None
    bid = pc.bytes_sha(json.dumps({"in": inputs, "mp4": mp4}, sort_keys=True).encode(), 12)
    return {"id": bid, "inputs": inputs, "mp4Sha256": mp4}


def freshness(ep: Episode) -> list[dict]:
    """The mp4 must be newer than the manifest it claims to show, and Remotion's copy of the
    manifest must be the same file (else the render used another build)."""
    out = []
    man = ep.dir / "episode.json"
    if not (ep.mp4.is_file() and man.is_file()):
        return [check("build.fresh", "skip", "no mp4 or no episode.json", "")]
    stale = ep.mp4.stat().st_mtime + 1 < man.stat().st_mtime
    pub = ep.remotion / "public" / "episodes" / ep.slug / "episode.json"
    differs = pub.is_file() and pc.file_sha(pub, 64) != pc.file_sha(man, 64)
    probs = (["mp4 is older than episode.json"] if stale else []) + (
        [f"{pub} differs from {man}"] if differs else [])
    out.append(check("build.fresh", "fail" if probs else "pass",
                     "; ".join(probs) if probs else "mp4 rendered after the current episode.json; Remotion copy matches",
                     "rerun build_manifest.py, render again, then qc.py all" if probs else ""))
    return out


def audio_checks(ep: Episode) -> list[dict]:
    """Audio evidence the judge cannot get by looking: fidelity (raw ASR vs script, both
    directions) and per-turn level jumps between takes."""
    out = []
    if not ep.timing or not ep.script:
        return [check("audio.fidelity", "fail", "no timing.json or script.json", "run tts.py and align.mjs")]
    try:
        fid = pc.episode_fidelity(ep.script, ep.timing, pc.load_accept(ep.dir), pc.load_lexicon(ep.dir))
    except ValueError as e:
        return [check("audio.fidelity", "fail", str(e), "fix fidelity-accept.json")]
    ep.qc.mkdir(parents=True, exist_ok=True)
    (ep.qc / "fidelity.json").write_text(json.dumps(fid, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    c = fid["counts"]
    bad = [t for t in fid["turns"] if t["status"] in ("fail", "stale")]
    detail = (f"{c['ok']} ok, {c['warn']} warn, {c['fail']} fail, {c['accepted']} accepted, {c['stale']} stale, "
              f"{c['missing']} without raw ASR (engine {fid['engine']})")
    if bad:
        detail += "; " + "; ".join(f"{t['turn']} {', '.join(t.get('critical') or []) or t.get('detail') or ('WER ' + str(t.get('wer')))}" for t in bad[:5])
    if fid["draft"]:
        why = "; ".join(fid.get("rejected") or []) or "estimated or missing word alignment, so the audio was never checked against the script"
        detail = f"DRAFT, not deliverable ({why}). " + detail
    status = "fail" if bad or fid["draft"] else ("warn" if c["warn"] else "pass")
    out.append(check("audio.fidelity", status, detail,
                     "" if status == "pass" else
                     f"see {ep.qc / 'fidelity.json'}; retake a failing turn (tts.py --only <id> --retake, align.mjs --only <id>), "
                     "or listen and record it in fidelity-accept.json with its audioSha, expected text and reason (fidelity.py prints the entry); "
                     "a draft needs per-turn Gemini takes (no --scratch, no --mode chunk) and align.mjs with whisper.cpp"))
    levels = []
    for t in ep.timing.get("turns", []):
        f = ep.dir / t.get("file", "")
        if not f.is_file():
            continue
        r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-af", "volumedetect", "-f", "null", "-"], timeout=60)
        m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
        if m:
            levels.append((t["id"], float(m.group(1))))
    if levels:
        med = sorted(v for _, v in levels)[len(levels) // 2]
        jumps = [(tid, v - med) for tid, v in levels if abs(v - med) > LEVEL_WARN_DB]
        out.append(check("audio.levels", "warn" if jumps else "pass",
                         f"{len(levels)} turn clips, median {med:.1f} dB mean volume" +
                         ("; off by more than %.0f dB: " % LEVEL_WARN_DB + ", ".join(f"{tid} {d:+.1f} dB" for tid, d in jumps[:6]) if jumps else ""),
                         "listen to those turns (a whisper, a shout or voice drift); retake with tts.py --only <id> --retake" if jumps else ""))
    return out


def _finite(v, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.S)
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
TURN_REF_RE = re.compile(r"\bt\d{2,3}\b")
JUDGE_FIELDS = ("build", "round", "scores", "j", "reasons", "worst", "heldOut")
RESTATE_FIELDS = ("score", "summary", "gaps", "retrieval", "transfer")


def last_json_block(text: str):
    """The last ```json block of a reviewer's reply, parsed, or None."""
    blocks = JSON_BLOCK_RE.findall(text or "")
    for raw in reversed(blocks):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    return None


def review_context(ep: Episode) -> dict:
    """What evidence references in qc/scores.json may point at (N09): the script's turn ids, the
    episode length in seconds, and the still and contact-sheet file names the reviewers were given."""
    turns = {t.get("id") for seg in (ep.script or {}).get("segments", []) for t in seg.get("turns", [])}
    try:
        total = ep.total_ms() / 1000
    except (QcError, KeyError, TypeError, ValueError):
        total = None
    files = {p.name for p in (ep.qc / "stills").glob("*.png")} | {p.name for p in ep.qc.glob("contact-sheet*.png")}
    try:
        video = " | ".join(_norm_words(x) for x in _video_texts(ep))
    except Exception:  # noqa: BLE001 - quotes are then not checked against the text
        video = None
    return {"turns": turns, "maxSec": total, "files": files, "videoText": video}


FILE_REF_RE = re.compile(r"[\w.\-]+\.(?:png|jpe?g|webp)\b", re.I)


def _refs(text: str) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Q07 (codex round 4): every reference in a citation, extracted independently: frame file
    names, turn ids and mm:ss times. File names are removed before turn ids and times are read."""
    text = text or ""
    files = FILE_REF_RE.findall(text)
    rest = FILE_REF_RE.sub(" ", text)
    return files, TURN_REF_RE.findall(rest), TIME_RE.findall(rest)


def _ref_problems(text: str, ctx: dict | None) -> list[str]:
    """Every invalid reference: a frame file the reviewers were not given, a turn id that does not
    exist, an mm:ss outside the episode (or with seconds over 59)."""
    if not ctx:
        return []
    out = []
    files, turns, times = _refs(text)
    for f in files:
        if f not in (ctx.get("files") or ()):
            out.append(f"frame {f} does not exist in qc/")
    for tid in turns:
        if ctx.get("turns") and tid not in ctx["turns"]:
            out.append(f"turn {tid} does not exist")
    for mm, ss in times:
        sec = int(mm) * 60 + int(ss)
        if int(ss) >= 60 or (ctx.get("maxSec") is not None and sec > ctx["maxSec"] + 1):
            out.append(f"time {mm}:{ss} is outside the episode")
    return out


def _cites_real(text: str, ctx: dict | None) -> bool:
    """A citation holds at least one reference (frame file, turn id, mm:ss) and EVERY reference in
    it is valid (Q07: one good reference no longer excuses a bad one)."""
    if not isinstance(text, str) or not text.strip():
        return False
    files, turns, times = _refs(text)
    return bool(files or turns or times) and not _ref_problems(text, ctx)


_QUOTE_RE = re.compile(r"[\"\u201c]([^\"\u201c\u201d]{3,})[\"\u201d]")


def _norm_words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", pc.spoken_text(str(text or "")).lower()))


def quote_problems(field: str, text, ctx: dict | None) -> list[str]:
    """Q02: heldOut.case and heldOut.solution quote the video verbatim ("..." with a turn id or
    mm:ss). Each quoted piece (split at '...') of 3 or more words must occur in the spoken or shown
    text, and the citation must be valid."""
    if not (isinstance(text, str) and text.strip()):
        return [f"heldOut.{field} is missing: quote the closest {field} the video works, in double quotes, with its turn id"]
    out = []
    quotes = _QUOTE_RE.findall(text)
    if not quotes:
        out.append(f"heldOut.{field} quotes nothing: put the video's own words in double quotes")
    if not _cites_real(text, ctx):
        out.append(f"heldOut.{field} cites no existing turn id or mm:ss ({'; '.join(_ref_problems(text, ctx)) or 'no reference'})")
    hay = (ctx or {}).get("videoText")
    if hay:
        for q in quotes:
            for piece in re.split(r"\.\.\.|\u2026", q):
                w = _norm_words(piece)
                if len(w.split()) >= 3 and w not in hay:
                    out.append(f"heldOut.{field} quote \"{piece.strip()[:50]}\" is not in the spoken or shown text")
    return out


def score_problems(sc, build_id: str, ctx: dict | None = None) -> list[str]:
    """Why qc/scores.json does not pass for this build (N09). The judge and the restater each return
    their JSON in their reply; the parent agent writes the file with both replies as received (the
    text of each agent's final message) and their sha256, so the record can be compared with what
    the reviewers said. The sha256 binds the stored text; byte-for-byte fidelity with the model's own
    output cannot be proven, because the parent relays the reply. `ctx` (review_context)
    checks that every cited turn, time and still exists in this episode. The record still cannot
    prove that an independent agent wrote it when the building agent persists it."""
    if not isinstance(sc, dict):
        return ["qc/scores.json is not a JSON object"]
    probs = []
    if sc.get("build") != build_id:
        probs.append(f"scores are for build {sc.get('build')!r}, this build is {build_id!r}")
    if not (isinstance(sc.get("round"), int) and not isinstance(sc.get("round"), bool) and 1 <= sc["round"] <= 3):
        probs.append(f"round must be an integer 1 to 3, got {sc.get('round')!r}")
    scores, j, reasons = sc.get("scores") or {}, sc.get("j") or {}, sc.get("reasons") or {}
    bad = [k for k in RUBRIC_KEYS if not _finite(scores.get(k), 1, 10)]
    if bad:
        probs.append("rubric scores missing or not a finite number 1 to 10: " + ", ".join(f"{k}={scores.get(k)!r}" for k in bad))
    low = [f"{k} {scores[k]}" for k in RUBRIC_KEYS if k not in bad and scores[k] < RUBRIC_BAR]
    if low:
        probs.append(f"rubric below {RUBRIC_BAR}: " + ", ".join(low))
    badj = [k for k in J_IDS if not _finite(j.get(k), 1, 5)]
    if badj:
        probs.append("J scores missing or not a finite number 1 to 5: " + ", ".join(f"{k}={j.get(k)!r}" for k in badj))
    lowj = [f"{k} {j[k]}" for k in J_IDS if k not in badj and j[k] < J_BAR.get(k, 3)]
    if lowj:
        probs.append("J criteria under their bar: " + ", ".join(lowj))
    noreason = [k for k in RUBRIC_KEYS + J_IDS if not (isinstance(reasons.get(k), str) and REF_RE.search(reasons[k]))]
    if noreason:
        probs.append("reasons missing or citing no mm:ss or turn id for: " + ", ".join(noreason[:8]) + (" ..." if len(noreason) > 8 else ""))
    badref = [f"{k} ({'; '.join(_ref_problems(reasons[k], ctx))})" for k in RUBRIC_KEYS + J_IDS
              if isinstance(reasons.get(k), str) and _ref_problems(reasons[k], ctx)]
    if badref:
        probs.append("reasons cite evidence that is not in this episode: " + ", ".join(badref[:6]))
    worst = sc.get("worst")
    if not isinstance(worst, list):
        probs.append("worst must list the 3 worst problems (segment, turn, mm:ss)")
    else:
        if (low or lowj) and not worst:
            probs.append("worst is empty although a score is under its bar: list the worst problems with segment, turn and mm:ss")
        badw = [str(w)[:40] for w in worst if not _cites_real(str(w), ctx)]
        if badw:
            probs.append("worst items must cite an existing turn id or an mm:ss inside the episode: " + "; ".join(badw[:3]))
    ho = sc.get("heldOut")
    if not (isinstance(ho, dict) and isinstance(ho.get("demonstrated"), bool) and isinstance(ho.get("evidence"), str) and ho["evidence"].strip()):
        probs.append("heldOut must be the judge's {demonstrated: true|false, case, solution, evidence}: did the video already "
                     "work the held-out case and its solution?")
    else:
        # Q02 (codex round 4): the judge decides whether the case was demonstrated, and quotes the
        # closest case and solution the video works, so the decision can be checked.
        for field in ("case", "solution"):
            probs += quote_problems(field, ho.get(field), ctx)
        if ho["demonstrated"]:
            probs.append(f"the judge found the held-out case demonstrated in the video ({ho['evidence'][:80]}): write a new held-out case")
    # Verbatim judge reply (N09): the record must be what the judge said.
    reply = sc.get("judgeReply")
    if not (isinstance(reply, str) and reply.strip()):
        probs.append("judgeReply missing: store the judge agent's reply as received (the whole text of its final message; "
                     "qc.py save-reply --kind judge records it) and judgeReplySha256")
    else:
        if sc.get("judgeReplySha256") != pc.bytes_sha(reply.encode("utf-8"), 64):
            probs.append("judgeReplySha256 is not the sha256 of judgeReply (UTF-8): store the reply as received, unedited")
        blk = last_json_block(reply)
        if not isinstance(blk, dict):
            probs.append("judgeReply has no ```json block")
        else:
            diff = [k for k in JUDGE_FIELDS if blk.get(k) != sc.get(k)]
            if diff:
                probs.append(f"scores.json differs from the judge's own JSON block in: {', '.join(diff)}")
    rs = sc.get("restate")
    if not isinstance(rs, dict):
        probs.append("no restate result: add the blind restate agent's reply as restate {score, summary, gaps, retrieval, transfer, reply, replySha256}")
    else:
        if not _finite(rs.get("score"), 1, 5):
            probs.append(f"restate.score must be a finite number 1 to 5, got {rs.get('score')!r}")
        elif rs["score"] < RESTATE_BAR:
            probs.append(f"restate.score {rs['score']} is below {RESTATE_BAR}: the blind restater could not rebuild the mechanism")
        if not (isinstance(rs.get("summary"), str) and rs["summary"].strip()):
            probs.append("restate.summary is empty: copy the restater's 5-sentence restatement")
        if not isinstance(rs.get("gaps"), list):
            probs.append("restate.gaps must be a list (the restater's 'not shown' items, may be empty)")
        for part in ("retrieval", "transfer"):
            x = rs.get(part)
            if not (isinstance(x, dict) and isinstance(x.get("answer"), str) and x["answer"].strip()):
                probs.append(f"restate.{part} must hold the restater's actual {part} answer {{answer, citations}}")
                continue
            cites = x.get("citations")
            if not (isinstance(cites, list) and cites):
                probs.append(f"restate.{part}.citations is empty: each answer cites the frame file or [mm:ss] line it came from")
            else:
                badc = [str(c)[:30] for c in cites if not _cites_real(str(c), ctx)]
                if badc:
                    probs.append(f"restate.{part}.citations name no existing frame file or in-range mm:ss: " + "; ".join(badc[:3]))
        rreply = rs.get("reply")
        if not (isinstance(rreply, str) and rreply.strip()):
            probs.append("restate.reply missing: store the restate agent's reply as received (qc.py save-reply --kind restate) and restate.replySha256")
        else:
            if rs.get("replySha256") != pc.bytes_sha(rreply.encode("utf-8"), 64):
                probs.append("restate.replySha256 is not the sha256 of restate.reply (UTF-8): store the reply as received, unedited")
            blk = last_json_block(rreply)
            if not isinstance(blk, dict):
                probs.append("restate.reply has no ```json block")
            else:
                diff = [k for k in RESTATE_FIELDS if blk.get(k) != rs.get(k)]
                if diff:
                    probs.append(f"restate differs from the restater's own JSON block in: {', '.join(diff)}")
    return probs


def provenance_problems(ep: Episode) -> list[str]:
    """Derived files must come from the current script, timing and learn.json (N06): compare
    digests, not start times or mtimes."""
    out = []
    now = pc.source_digests(ep.dir)
    tj = ep._load("transcript.json") if (ep.dir / "transcript.json").is_file() else None
    if tj is not None:
        prov = tj.get("provenance") or {}
        diff = [k for k in ("script", "timing", "learn") if prov.get(k) != now[k]]
        if diff:
            out.append(f"transcript.json was built from another {', '.join(diff)} (provenance digests differ): rerun transcript.py")
    lp = ep.dir / "learn" / "provenance.json"
    if (ep.dir / "learn.json").is_file():
        if not lp.is_file():
            out.append("learn/provenance.json missing: rerun learn.py")
        else:
            try:
                prov = json.loads(lp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                prov = {}
            diff = [k for k in ("script", "timing", "learn") if (prov.get("sources") or {}).get(k) != now[k]]
            if diff:
                out.append(f"learn/ files were built from another {', '.join(diff)}: rerun learn.py")
            edited = [n for n, d in (prov.get("files") or {}).items() if pc.json_digest(ep.dir / "learn" / n) != d]
            if edited:
                out.append(f"learn/ files changed after learn.py wrote them ({', '.join(edited)}): rerun learn.py")
    return out


def delivery_problems(ep: Episode, rec: dict | None) -> list[str]:
    """N06: every delivered or searchable derivative (transcript.md, transcript.json, captions.vtt,
    captions.srt, chapters.ffmetadata, the library copy, the sidecars beside the mp4) must be the
    file transcript.py wrote from the CURRENT script, timing and learn.json. Two tests: the sha256
    recorded in <slug>/delivery.json, and a byte comparison with what transcript.py renders now
    from the same inputs (so an edit of a file and of delivery.json together is caught too)."""
    out = []
    dp = ep.dir / pc.DELIVERY_FILE
    if not dp.is_file():
        return [f"no {pc.DELIVERY_FILE}: rerun transcript.py (it records the digest of every transcript, caption and library file)"]
    try:
        dl = json.loads(dp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"{pc.DELIVERY_FILE} invalid ({e.msg}): rerun transcript.py"]
    now = pc.source_digests(ep.dir)
    diff = [k for k in ("script", "timing", "learn") if (dl.get("sources") or {}).get(k) != now[k]]
    if diff:
        out.append(f"transcript, captions and library copy were built from another {', '.join(diff)}: rerun transcript.py")
    files = dl.get("files") or {}
    expected = pc.delivery_paths(ep.ws, ep.slug, ep.mp4 if ep.mp4.is_file() else None)
    for name, path in expected.items():
        entry = files.get(name)
        if not path.is_file():
            out.append(f"{name} missing ({path})")
        elif not isinstance(entry, dict) or os.path.normpath(ep.ws / str(entry.get("path", ""))) != os.path.normpath(path):
            out.append(f"{name} ({path}) is not recorded in {pc.DELIVERY_FILE}: rerun transcript.py")
        elif pc.json_digest(path) != entry.get("sha256"):
            out.append(f"{name} ({path}) changed after transcript.py wrote it (stale or hand-edited): rerun transcript.py")
    # Regenerate in memory and compare bytes (catches a file edited together with delivery.json).
    try:
        import transcript as tr  # same folder
        ns = argparse.Namespace(tags=None, depth=None, series=None, part=None, date=None, mp4=None)
        epx = tr.build_episode(ep.ws, ep.slug, ns, rec)
        cues = tr.build_cues(epx)
        md = tr.render_markdown(epx)
        want = {"transcript.md": md, "captions.vtt": tr.render_vtt(cues), "captions.srt": tr.render_srt(cues),
                "chapters.ffmetadata": tr.render_ffmetadata(epx), "library": md, "sidecar.transcript.md": md,
                "sidecar.srt": tr.render_srt(cues), "sidecar.vtt": tr.render_vtt(cues),
                "transcript.json": json.dumps({**tr.transcript_json(epx, cues), "provenance": now}, indent=2, ensure_ascii=False) + "\n"}
        for name, path in expected.items():
            if name in want and path.is_file() and path.read_text(encoding="utf-8") != want[name]:
                out.append(f"{name} ({path}) differs from what transcript.py renders from the current inputs: rerun transcript.py")
        # Q04: recompute THIS episode's library record from the current inputs and compare it with the
        # stored record and with the digest delivery.json binds.
        want_rec, _ = tr.register_learn(ep.ws, ep.slug, tr.index_record(epx, ep.dir, rec))
        bound = (dl.get("record") or {}).get("sha256")
        if rec is not None:
            diff = sorted(k for k in set(want_rec) | set(rec)
                          if k not in pc.RECORD_UNBOUND_KEYS and want_rec.get(k) != rec.get(k))
            if diff:
                out.append(f"library/index.json record for {ep.slug} differs from what transcript.py and learn.py compute now "
                           f"in: {', '.join(diff[:6])}: rerun learn.py, then transcript.py")
        if not bound:
            out.append(f"{pc.DELIVERY_FILE} does not bind this episode's library record: rerun transcript.py")
        elif bound != pc.record_digest(rec):
            out.append(f"library/index.json record for {ep.slug} changed after transcript.py bound it in {pc.DELIVERY_FILE}: rerun transcript.py")
    except Exception as e:  # noqa: BLE001 - a broken input is itself a delivery problem
        out.append(f"cannot re-render the transcript to compare ({str(e)[:120]}): fix the inputs and rerun transcript.py")
    return list(dict.fromkeys(out))


def library_learn_problems(ep: Episode) -> list[str]:
    """Q04: every searchable copy in library/learn/<slug>/ is byte-identical to the canonical
    <slug>/learn/ file learn.py wrote (gaplog.md included: learn.py copies it; after the learner edits their
    gap log, rerun learn.py so the searchable copy follows)."""
    out = []
    lib = ep.ws / "library" / "learn" / ep.slug
    for name in LEARN_OUTPUTS + ["gaplog.md"]:
        src, cp = ep.dir / "learn" / name, lib / name
        if not src.is_file():
            continue
        if not cp.is_file():
            out.append(f"library/learn/{ep.slug}/{name} missing: rerun learn.py")
        elif pc.json_digest(cp) != pc.json_digest(src):
            out.append(f"library/learn/{ep.slug}/{name} differs from {ep.slug}/learn/{name}: rerun learn.py")
    return out


MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def summary_link_problems(ep: Episode) -> list[str]:
    """Q10: every link and image in learn/summary.md (and the other learn/*.md files) resolves: a
    relative path from the file's folder, a file:// URL or an absolute path must exist; http(s) and
    #anchors are not checked."""
    out = []
    for name in ("summary.md", "selftest.md", "cards.md", "teachback.md"):
        p = ep.dir / "learn" / name
        if not p.is_file():
            continue
        for target in MD_LINK_RE.findall(p.read_text(encoding="utf-8")):
            t = target.split("#", 1)[0]
            if not t or re.match(r"^(https?|mailto):", t):
                continue
            if t.startswith("file://"):
                from urllib.parse import unquote, urlparse
                path = Path(unquote(urlparse(t).path))
            else:
                path = Path(t) if t.startswith("/") else p.parent / t
            if not path.exists():
                out.append(f"learn/{name} links to {target}, which does not exist: rerun learn.py (it omits a missing heroStill)")
    return out


def final_checks(ep: Episode, build: dict) -> list[dict]:
    """Delivery gate: a read-only verification of the build the judge scored (SKILL.md step 14)."""
    out = []
    # Non-negotiable 5: every finished episode has its transcript, captions and learn/ files.
    need = [ep.dir / "transcript.md", ep.dir / "transcript.json", ep.dir / "captions.vtt", ep.dir / "captions.srt", ep.dir / "learn.json"]
    need += [ep.dir / "learn" / n for n in ("selftest.md", "cards.csv", "teachback.md", "summary.md", "gaplog.md", "provenance.json")]
    missing = [str(p.relative_to(ep.dir)) for p in need if not p.is_file()]
    stale = provenance_problems(ep)
    start = {t["id"]: t["startMs"] for t in (ep.timing or {}).get("turns", [])}
    idx_path = ep.ws / "library" / "index.json"
    rec = None
    if idx_path.is_file():
        try:
            rec = next((e for e in json.loads(idx_path.read_text(encoding="utf-8")).get("episodes", []) if e.get("slug") == ep.slug), None)
        except json.JSONDecodeError:
            rec = None
    stale += delivery_problems(ep, rec)
    stale += library_learn_problems(ep)
    stale += summary_link_problems(ep)
    if rec is None:
        stale.append("no library/index.json record")
    else:
        if not rec.get("learn"):
            stale.append("learn files not registered in library/index.json")
        bad = [x.get("turn") for x in (rec.get("selfTest") or []) + (rec.get("cards") or [])
               if x.get("turn") in start and x.get("t") != start[x["turn"]] // 1000]
        if bad:
            stale.append(f"self-test/card times differ from timing.json (first {bad[0]}): rerun learn.py")
    out.append(check("final.artefacts", "fail" if missing or stale else "pass",
                     "; ".join(([("missing: " + ", ".join(missing))] if missing else []) + stale)
                     or "transcript, captions, library copy, mp4 sidecars and learn/ files exist, are registered, match their recorded "
                        "digests and what transcript.py renders now from the current script, timing and learn.json",
                     "write learn.json, run learn.py, then transcript.py --embed-chapters, then qc.py all and re-judge" if missing or stale else ""))
    sp = ep.qc / "scores.json"
    if not sp.is_file():
        out.append(check("judge.scores", "fail", "no qc/scores.json",
                         "run the judge and restate agents (qc/judge-brief.md, qc/restate-brief.md); the parent writes qc/scores.json"))
    else:
        try:
            sc = json.loads(sp.read_text(encoding="utf-8"))
            probs = score_problems(sc, build["id"], review_context(ep))
            probs += stored_reply_problems(ep, sc)
        except json.JSONDecodeError as e:
            sc, probs = {}, [f"qc/scores.json invalid: {e.msg}"]
        out.append(check("judge.scores", "fail" if probs else "pass",
                         "; ".join(probs) or f"round {sc.get('round')}: all scores pass for build {build['id']}, restater {sc['restate']['score']}/5",
                         "fix the worst 3 problems and re-judge; gate 3 then shows a FAILED DRAFT for diagnosis, not for approval" if probs else ""))
    # D04: the judge cannot listen. Audio is scored from numbers; the learner's listen at gate 3 is the ear.
    lp = ep.qc / "listen.json"
    if not lp.is_file():
        out.append(check("audio.listen", "warn", "no qc/listen.json yet: the learner's listen note is recorded at gate 3, before 'Ship it'",
                         "at gate 3 ask the learner about clicks, voice drift and mispronounced words; write qc/listen.json "
                         f"{{\"build\": \"{build['id']}\", \"listener\": \"the learner\", \"problems\": [], \"note\": \"...\"}}"))
    else:
        try:
            ln = json.loads(lp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            ln = {"_err": e.msg}
        lprob = []
        if "_err" in ln:
            lprob.append(f"qc/listen.json invalid: {ln['_err']}")
        else:
            if ln.get("build") != build["id"]:
                lprob.append(f"listen note is for build {ln.get('build')!r}, this build is {build['id']!r}")
            if not isinstance(ln.get("problems"), list):
                lprob.append("problems must be a list")
            elif ln["problems"]:
                lprob.append("heard: " + "; ".join(map(str, ln["problems"][:4])))
        out.append(check("audio.listen", "fail" if lprob else "pass", "; ".join(lprob) or f"listened by {ln.get('listener')}: no problems",
                         "retake the named turns (tts.py --only <id> --retake), then rerun from align.mjs" if lprob else ""))
    return out


HELDOUT_Q_MAX = 0.5      # share of the question's content-word pairs found in ONE spoken turn or on-screen text
HELDOUT_A_MAX = 0.5      # share of the answer's content-word triples found anywhere in the spoken or shown text
_HO_STOP = set("""a an the and or but if then so of to in on at by for with from into onto as is are was were be been
being it its this that these those there here what which who whom whose why how when where do does did done can could
would should will shall may might must you your we our they their he she his her i me my not no yes than too very just
also about over under more most less least each every any some all one two three""".split())


def _content_seq(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", pc.spoken_text(str(text or "")).lower()):
        if w in _HO_STOP or (len(w) < 3 and not w.isdigit()):
            continue
        out.append(w[:-1] if w.endswith("s") and len(w) > 3 else w)
    return out


def _grams(seq: list[str], n: int) -> set[tuple]:
    if len(seq) < n:
        return {tuple(seq)} if seq else set()
    return {tuple(seq[i:i + n]) for i in range(len(seq) - n + 1)}


def _video_texts(ep: Episode) -> list[str]:
    """Every text the video speaks or shows: turns, pause prompts, scene and chip text, world labels."""
    out = []
    for seg in (ep.script or {}).get("segments", []):
        for t in seg.get("turns", []):
            out.append(t.get("text", ""))
            if isinstance(t.get("pause"), dict):
                out.append(t["pause"].get("prompt", ""))
    m = ep.manifest or {}
    for sc in m.get("scenes", []):
        out += _strings(sc.get("props"))
    for ov in m.get("overlays", []) or []:
        out += _strings(ov.get("props"))
    out += _strings(m.get("world"))
    out += [h.get("prompt", "") for h in m.get("holds", []) or []]
    return [x for x in out if isinstance(x, str) and x.strip()]


def held_out_overlap(ep: Episode, item: dict) -> dict:
    """How much of the held-out question and answer the video already says or shows (R05)."""
    texts = _video_texts(ep)
    q = _content_seq(item.get("question", ""))
    qg = _grams(q, 2)
    best_q, where = 0.0, ""
    for x in texts:
        g = _grams(_content_seq(x), 2)
        share = len(qg & g) / len(qg) if qg else 0.0
        if share > best_q:
            best_q, where = share, x[:60]
    a = _content_seq(item.get("answer", ""))
    ag = _grams(a, 3)
    union = set().union(*[_grams(_content_seq(x), 3) for x in texts]) if texts else set()
    best_a = len(ag & union) / len(ag) if ag else 0.0
    return {"question": round(best_q, 2), "answer": round(best_a, 2), "where": where}


def held_out_check(ep: Episode, final: bool) -> list[dict]:
    """R05: the restate brief's new case is the ONE learn.json selfTest item marked heldOut: true, at
    transfer or apply level, and neither its question nor its answer may already be in the video."""
    try:
        learn = ep._load("learn.json") or {}
    except QcError as e:
        return [check("brief.heldout", "fail", str(e), "fix learn.json")]
    items = pc.held_out_items(learn)
    fix = ("mark ONE learn.json selfTest question at transfer or apply level with \"heldOut\": true, about a case the video "
           "never shows, then run learn.py and transcript.py --embed-chapters, then qc.py all")
    if not items:
        return [check("brief.heldout", "fail" if final else "warn",
                      "no learn.json selfTest item has heldOut: true, so the restate brief has no held-out case", fix)]
    if len(items) > 1:
        return [check("brief.heldout", "fail", f"{len(items)} selfTest items have heldOut: true; designate exactly one", fix)]
    it = items[0]
    if it.get("level") not in pc.HELD_OUT_LEVELS or not str(it.get("question", "")).strip():
        return [check("brief.heldout", "fail", f"the heldOut item has level {it.get('level')!r}; it must be transfer, apply, "
                      "analyse or create and have a question", fix)]
    ov = held_out_overlap(ep, it)
    ep.heldout_overlap = ov
    # Q02 (codex round 4): only a duplicated QUESTION is a hard failure. A held-out answer that uses
    # the taught rule shares its words by design (valid transfer), and a paraphrased demonstrated case
    # shares none, so answer overlap is evidence for the judge (heldOut.demonstrated), not a verdict.
    if ov["question"] >= HELDOUT_Q_MAX:
        return [check("brief.heldout", "fail", f"the held-out question is in the video: {ov['question']:.0%} of its word pairs "
                      f"are already spoken or shown (\"{ov['where']}\"; limit {HELDOUT_Q_MAX:.0%})",
                      "write a new case the video does not ask (another input, another domain)")]
    if ov["answer"] >= HELDOUT_A_MAX:
        return [check("brief.heldout", "warn", f"held-out question from learn.json; {ov['answer']:.0%} of its answer's word "
                      "triples are spoken or shown. That is expected when the answer applies the taught rule, and a sign of a "
                      "recycled case when the video works the same situation: the judge decides (heldOut.demonstrated, with "
                      f"the case and solution quoted): {it['question'][:80]}",
                      "if the video works this same case, write a new one; if it only states the rule, leave it")]
    return [check("brief.heldout", "pass", f"held-out question from learn.json (overlap with the video: question "
                  f"{ov['question']:.0%}, answer {ov['answer']:.0%}): {it['question'][:80]}")]


def write_reports(ep: Episode, checks: list[dict], build: dict | None = None, final: bool = False) -> dict:
    ep.qc.mkdir(parents=True, exist_ok=True)
    summary = {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "warn", "fail", "skip")}
    result = "FAIL" if summary["fail"] else "PASS"
    verdict = ("READY FOR APPROVAL" if final and result == "PASS" else
               "FAILED DRAFT (show only for diagnosis)" if final else
               "checks " + result + " (not a delivery verdict: judge only a final mp4, after learn.py and "
               "transcript.py --embed-chapters; then qc.py all --final)")
    report = {"slug": ep.slug, "createdAt": dt.datetime.now().isoformat(timespec="seconds"), "mp4": str(ep.mp4),
              "build": build, "final": final, "verdict": verdict,
              "checks": checks, "summary": summary, "result": result}
    (ep.qc / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [f"# QC report: {ep.slug}", "", f"Result: **{report['result']}** ({summary['pass']} pass, {summary['warn']} warn, {summary['fail']} fail, {summary['skip']} skip). Created {report['createdAt']}.", "",
             f"Verdict: **{verdict}**", "",
             f"Video: {ep.mp4}", "", f"Build: `{(build or {}).get('id')}` (mp4 sha256 {(build or {}).get('mp4Sha256')})", "",
             "| Check | Status | Detail | Fix |", "| --- | --- | --- | --- |"]
    for c in checks:
        cell = lambda s: s.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {c['id']} | {c['status'].upper()} | {cell(c['detail'])} | {cell(c['fix'])} |")
    lines += ["", "Any FAIL blocks gate 3. Warnings are judge inputs.", ""]
    (ep.qc / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def restate_question(ep: Episode) -> str:
    """The question the video answers: the last `retrieve` pause prompt (never the closing
    next-time question, which the episode deliberately leaves open), else brief.learnerOutcome,
    else the learning objective as a question."""
    prompt = ""
    for seg in (ep.script or {}).get("segments", []):
        for t in seg.get("turns", []):
            pz = t.get("pause") if isinstance(t.get("pause"), dict) else None
            if pz and pz.get("kind") == "retrieve" and pz.get("prompt"):
                prompt = pz["prompt"]
    if prompt:
        return prompt
    brief = ep._load("brief.json") or {}
    if brief.get("learnerOutcome"):
        return f"Can you now do this: {brief['learnerOutcome']}"
    goal = (ep.script or {}).get("learningObjective", "")
    return f"Explain how and why: {goal}" if goal else "What is the mechanism, step by step?"


def transfer_question(ep: Episode) -> str:
    """The held-out question: the ONE learn.json selfTest item marked heldOut: true (R05).
    brief.heldout checks that the video neither asks nor answers it."""
    try:
        item = pc.held_out_item(ep._load("learn.json") or {})
    except QcError:
        return ""
    return item["question"] if item and item.get("level") in pc.HELD_OUT_LEVELS and item.get("question") else ""


def write_spoken(ep: Episode) -> Path:
    """Canonical spoken text (pe_common.spoken_text) with [mm:ss] from the current timing, so a
    stale transcript.md can never reach the restater."""
    m = ep.need_manifest()
    names = {s["id"]: s.get("name", s["id"]) for s in m.get("speakers", [])}
    raw = ep.raw_text()
    lines = ["# Spoken text, in order", ""]
    for t in m.get("turns", []):
        s = int(t["startMs"]) // 1000
        lines.append(f"[{s // 60:02d}:{s % 60:02d}] {names.get(t['speaker'], t['speaker'])}: {pc.spoken_text(raw.get(t['id'], t.get('text', '')))}")
    d = ep.qc / "restate"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "spoken.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def write_judge_brief(ep: Episode, build: dict | None = None) -> Path:
    sdir = ep.qc / "stills"
    idx = json.loads((sdir / "index.json").read_text()) if (sdir / "index.json").is_file() else {"stills": []}
    stills_list = [p["path"] for p in idx["stills"] if Path(p.get("path", "")).is_file()]
    spoken = write_spoken(ep) if ep.manifest else ep.dir / "script.json"
    P = lambda p: f"- `{p}`" + ("" if Path(p).exists() else " (missing)")
    viewing, _ = read_viewing(ep)
    sheets720 = sorted(ep.qc.glob("contact-sheet-720-*.png"))
    ref_sheets = [ep.qc / "contact-sheet-phone.png"] if viewing == "phone" else (sheets720 or [ep.qc / "contact-sheet-720-01.png"])
    checked = getattr(ep, "labels_checked", None)
    files = list(dict.fromkeys(str(p) for p in (ep.mp4, ep.qc / "contact-sheet.png", *ref_sheets, ep.qc / "contact-sheet-phone.png", ep.qc / "report.md",
                                                ep.qc / "fidelity.json", spoken, ep.dir / "script.json", ep.dir / "facts.json",
                                                ep.dir / "scenes.json", ep.dir / "timing.json", ep.dir / "learn")))
    bid = (build or {}).get("id")
    held = transfer_question(ep)
    score_keys = ", ".join('"%s": 8' % k for k in RUBRIC_KEYS)
    lines = [f"# Judge brief: {ep.slug}", "",
             f"Build `{bid}`. Hand this file to ONE read-only judge agent with fresh context; it is not the agent that built the video. "
             "The blind restate agent gets `qc/restate-brief.md` instead, never this file.", "",
             "## Files", ""] + [P(f) for f in files] + ["", f"Stills (from {idx.get('source', 'the mp4')}; turn-* stills are the midpoints of causal turns):", ""] + [f"- `{s}`" for s in stills_list] + [
             "", "Rubric files:", "", f"- `{REFS / 'qc.md'}` section 4 (scored rubric, 1 to 10, pass at 8 or more on every line)",
             f"- `{REFS / 'learning-design.md'}` section 10 (judge rubric J1 to J11)", "",
             "## Judge agent (read-only)", "",
             "Read only. Do not edit, render or run anything except ffprobe and ffmpeg frame extraction into "
             f"`{ep.qc / 'judge'}/`. Score each rubric line in qc.md section 4 from 1 to 10 and each criterion J1 to J11 in "
             "learning-design.md section 10 from 1 to 5, each with a timestamped reason that quotes turn ids. List the 3 worst problems "
             "with segment id, turn id and mm:ss. Check every number and negation against the facts.json quotes. Do not reward "
             "'clear', 'smooth' or 'engaging', and do not use your own feeling of understanding as evidence.", "",
             "Cite evidence, not impressions: quote the turn that gives the plain explanation, the turn where the misconception "
             "visibly fails, the turn that repairs the model, and the transfer reasoning. A criterion with no quotable turn scores 2 or less.", "",
             "J11, labels: no on-screen label contradicts the scene or the words. Check every comparison and wrong-versus-right "
             "panel, verdict, banner and chip against what the hosts say at that moment (a WRONG chip on a scheme the episode "
             "calls fine for a fixed fleet fails J11). `qc.py` labels.counts machine-checked these labels against the compare "
             "table state on their frames (see its line in report.md for mismatches). Verified: "
             + ("; ".join(checked) if checked else "none (no count label on a two-row compare table)")
             + ". Unchecked (ambiguous wording or a partly filled table; yours to check): "
             + ("; ".join(getattr(ep, "labels_unchecked", None) or []) or "none")
             + ". labels.stale lists quantity labels that outlive the world step they describe. Every other label "
             "(world panels, verdict words, chips outside compare tables) is yours to check.", "",
             f"Readability (rubric line 5): brief.json viewing is **{viewing}**. "
             + ("Score it on `qc/contact-sheet-phone.png` (360 px tiles): text under 36 px at 1080p or a grid with more than 8 "
                "cells per row is a blocker (text.phone fails), and readability scores 7 or less while one shows."
                if viewing == "phone" else
                "Score it on `qc/contact-sheet-720-NN.png` (frames at 1280 px, a 720p player): every label must be readable "
                "there. `qc/contact-sheet-phone.png` is optional evidence; text under 36 px or a grid over 8 cells per row is a "
                "warning (text.phone), not a fail.")
             + " Text under 28 px at 1080p fails in both modes (text.minsize).", "",
             "Concept lands (rubric line 2): the blind restater ran BEFORE you. Its reply is "
             f"`{ep.qc / 'replies' / 'restate.md'}` (the parent stored it with `qc.py save-reply --kind restate`, or pasted it "
             "below this brief). Score line 2 from that reply: does it state the core mechanism and answer the retrieval question "
             "correctly, with citations? Quote its words in the reason. If no restater reply reached you, say so in `notes` and "
             "score line 2 at most 5; do not guess it.", "",
             "Audio (rubric line 8): you cannot listen, so do not judge clicks, voice drift or timbre. Score it only from numbers: "
             "`qc/fidelity.json` (raw ASR vs script per turn), the audio.levels, probe.loudness, probe.truepeak and probe.deadair "
             "checks in `report.md`. A warn that is only an ASR spelling of a name (Priya heard as 'prayer') does not lower line 8; "
             "fidelity.py prints a lexicon suggestion for those. Name every turn with a fidelity warn so the learner listens to it at "
             "gate 3; their listen note (qc/listen.json) is the ear.", "",
             "Pauses (rubric line 10): a predict or retrieve hold lasts 6 to 8 s; an explain-back hold may run to 15 s "
             "(learning-design.md L11, validator W22).", "",
             "Held-out case: the restater gets this NEW case, which the video must not demonstrate: "
             + (f"\"{held}\". " if held else "(none designated yet; brief.heldout fails). ")
             + "Search the spoken text and the frames for it, including paraphrases (another name for the same object, the "
             "same numbers in other words). Applying the taught general rule to a NEW situation is not a demonstration; "
             "working the SAME situation (same kind of input, same solution) is, however it is worded. Quote the closest "
             "case the video works and its solution VERBATIM in double quotes with the turn id (heldOut.case, "
             "heldOut.solution), then decide heldOut.demonstrated; true fails the delivery check. Machine evidence: "
             + (lambda o: f"question overlap {o['question']:.0%}, answer overlap {o['answer']:.0%} (word pairs and triples "
                f"already spoken or shown)." if o else "not computed.")(getattr(ep, "heldout_overlap", None)), "",
             "Output: you are read-only, so do NOT write any file. End your reply with ONE ```json block shaped like "
             f"{{\"build\": \"{bid}\", \"round\": 1, \"scores\": {{{score_keys}}}, "
             "\"j\": {\"J1\": 4, ..., \"J11\": 4}, \"reasons\": {\"hook\": \"00:11 t02: ...\", ..., \"J11\": \"09:42 t66: ...\"}, "
             "\"worst\": [\"seg03 t16 @ 02:23: ...\"], \"heldOut\": {\"demonstrated\": false, \"case\": \"t41: \\\"<the video's closest worked case, verbatim>\\\"\", "
             "\"solution\": \"t43: \\\"<how the video solves it, verbatim>\\\"\", \"evidence\": \"<why the held-out case is or is not the same situation>\"}, "
             "\"notes\": []}. Every score is a number in range (rubric 1 to 10, J 1 to 5); every key of `scores` and `j` has a "
             "reason that cites an mm:ss or a turn id that exists in THIS episode; `worst` is never empty while a score is under "
             "its bar, and each item cites a real turn or time. The parent agent writes `qc/scores.json`: your JSON fields plus "
             "your whole reply as received (judgeReply, judgeReplySha256); scores for another build do not count.", "",
             "Use a read-only agent type (Explore) when available.", ""]
    path = ep.qc / "judge-brief.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_restate_brief(ep: Episode) -> Path:
    """The blind restater sees only delivered frames and canonical spoken text."""
    sdir = ep.qc / "stills"
    idx = json.loads((sdir / "index.json").read_text()) if (sdir / "index.json").is_file() else {"stills": []}
    frames = [p["path"] for p in idx["stills"] if Path(p.get("path", "")).is_file()]
    spoken = ep.qc / "restate" / "spoken.md"
    q = restate_question(ep)
    tq = transfer_question(ep)
    lines = [f"# Restate brief: {ep.slug}", "",
             "For ONE fresh agent that did not build the video and has not read this episode's script, facts, outline, scenes or "
             "learning goals. Give it this file only. It may read the files listed here and nothing else in the episode folder.", "",
             f"Frames (from {idx.get('source', 'the delivered mp4')}):", "", f"- `{ep.qc / 'contact-sheet.png'}`"] + [f"- `{f}`" for f in frames] + [
             "", "Spoken text, in order (canonical text the hosts say, nothing else):", "", f"- `{spoken}`", "",
             "## Task", "",
             "1. From these frames and this spoken text only, explain the concept in 5 sentences as if to a colleague.",
             f"2. Answer: {q}",
             f"3. New case (not in the video): {tq or 'invent one new input the video did not show and predict the outcome with the mechanism.'}",
             "4. For every claim in 1 to 3, cite the frame file or the [mm:ss] line it came from. An answer without a citation counts as not supported.",
             "5. Score 1 to 5 how completely you could rebuild the mechanism from these inputs alone (5: all of it, with the general rule; "
             "3: the idea but not the steps; 1: only the topic).", "",
             "Do not use outside knowledge to fill a gap: write 'not shown' instead. A gap you name is more useful than a guess.", "",
             "Do not write any file. End your reply with ONE ```json block: "
             "{\"score\": 4, \"summary\": \"<your 5 sentences>\", \"gaps\": [\"<each 'not shown' item>\"], "
             "\"retrieval\": {\"answer\": \"<your answer to 2>\", \"citations\": [\"[mm:ss]\" or \"<frame file name>\"]}, "
             "\"transfer\": {\"answer\": \"<your answer to 3>\", \"citations\": [...]}}. Every citation names a frame file "
             "listed above or an [mm:ss] line of the spoken text. The parent agent stores your whole reply as received as "
             "`restate.reply` (with its sha256) and your JSON fields as `restate` in qc/scores.json.", ""]
    path = ep.qc / "restate-brief.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def stored_reply_problems(ep: "Episode", sc: dict) -> list[str]:
    """When qc.py save-reply stored a reply (qc/replies/<kind>.json), the reply in scores.json must
    be that stored text: same sha256 as recorded at storage time (W16)."""
    out = []
    for kind, got in (("judge", sc.get("judgeReplySha256")), ("restate", (sc.get("restate") or {}).get("replySha256"))):
        mp = ep.qc / "replies" / f"{kind}.json"
        try:
            meta = json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else None
        except (OSError, json.JSONDecodeError):
            meta = {"sha256": None}
        if meta is not None and meta.get("sha256") != got:
            out.append(f"the {kind} reply in qc/scores.json is not the one stored with save-reply (qc/replies/{kind}.md, "
                       f"sha256 {str(meta.get('sha256'))[:12]}...): copy the stored text, or save the new reply again")
    return out


def save_reply(args) -> int:
    """qc.py save-reply (W16, W14b D20): the parent stores a reviewer's reply as received and records
    its sha256 at storage time. The digest proves the stored text has not changed since; it cannot
    prove that the text is byte for byte what the model produced (the parent relays it)."""
    try:
        ep_dir = pc.episode_dir(args.workspace, args.slug)
        text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    except (pc.BadId, OSError, UnicodeDecodeError) as e:
        print(f"qc.py save-reply: error: {e}", file=sys.stderr)
        return 2
    if not text.strip():
        print("qc.py save-reply: error: the reply is empty", file=sys.stderr)
        return 2
    d = ep_dir / "qc" / "replies"
    d.mkdir(parents=True, exist_ok=True)
    sha = pc.bytes_sha(text.encode("utf-8"), 64)
    pc.atomic_write(d / f"{args.kind}.md", text, base=ep_dir)
    meta = {"kind": args.kind, "sha256": sha, "bytes": len(text.encode("utf-8")), "savedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "jsonBlock": isinstance(last_json_block(text), dict),
            "note": "stored as received from the agent's final message; the sha256 binds the stored text, not the model's raw output"}
    pc.atomic_write(d / f"{args.kind}.json", json.dumps(meta, indent=1) + "\n", base=ep_dir)
    print(f"saved {d / (args.kind + '.md')} ({meta['bytes']} bytes, sha256 {sha}); JSON block {'found' if meta['jsonBlock'] else 'MISSING'}")
    return 0 if meta["jsonBlock"] else 1


def safe(fn, name, *a) -> list[dict]:
    try:
        return fn(*a)
    except QcError as e:
        return [check(name, "fail", str(e), str(e).split("; ", 1)[-1] if "; " in str(e) else "")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="QC on a rendered explainer: probe, stills, captions, coverage, all.")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{probe,stills,captions,coverage,audio,all,save-reply}")
    helps = {"probe": "ffprobe spec, duration vs manifest, loudness, true peak, chapters, series part cap, black frames, dead air",
             "stills": "stills from the delivered mp4: entry/middle/exit per segment, each hold, each causal turn; contact sheets",
             "captions": "caption pages: chars per second, min time, flicker, holds, safe-area geometry",
             "coverage": "onScreen terms and numbers visible at their time, anchors name real turns, pause prompts, text size and contrast (text.minsize, text.phone), count labels true of their compare table (labels.counts)",
             "audio": "fidelity (raw ASR vs script, both directions) and per-turn level jumps",
             "all": "every check, build identity, then qc/report.json, report.md, judge-brief.md and restate-brief.md"}
    for name, h in helps.items():
        p = sub.add_parser(name, help=h, description=h)
        p.add_argument("--workspace", default="explainers", help="workspace folder (default ./explainers)")
        p.add_argument("--slug", required=True, help="episode folder name")
        p.add_argument("--mp4", help="video to check (default <slug>/out/episode.mp4)")
        p.add_argument("--remotion-dir", help="Remotion project (default <workspace>/remotion)")
        p.add_argument("--json", action="store_true", help="print the result as JSON")
        if name in ("stills", "all"):
            p.add_argument("--from-remotion", action="store_true",
                           help="render stills from the source with npx remotion still (preview only; the default is the delivered mp4)")
            p.add_argument("--from-mp4", action="store_true", help=argparse.SUPPRESS)  # old flag; the mp4 is now the default
        if name == "all":
            p.add_argument("--skip-stills", action="store_true", help="skip stills and contact sheets")
            p.add_argument("--final", action="store_true",
                           help="read-only delivery check of the judged build: chapters, transcript and learn files built "
                                "from the current script and timing, and a valid qc/scores.json for this build")
    p = sub.add_parser("save-reply", help="store a reviewer's reply as received, with its sha256 (qc/replies/<kind>.md)",
                       description="Store the judge's or restater's reply as received (the text of the agent's final message, "
                                   "from --file or stdin) in qc/replies/<kind>.md and record its sha256 at storage time in "
                                   "qc/replies/<kind>.json. It cannot prove the text is byte for byte what the model produced.")
    p.add_argument("--workspace", default="explainers")
    p.add_argument("--slug", required=True)
    p.add_argument("--kind", required=True, choices=("judge", "restate"))
    p.add_argument("--file", help="reply text file (default: stdin)")
    args = ap.parse_args(argv)
    if args.cmd == "save-reply":
        return save_reply(args)
    try:
        ep = Episode(args)
    except QcError as e:
        print(f"qc.py: error: {e}", file=sys.stderr)
        return 1
    ep.final = bool(getattr(args, "final", False))
    funcs = {"probe": lambda: safe(probe, "probe", ep), "captions": lambda: safe(captions, "captions", ep),
             "coverage": lambda: safe(coverage, "coverage", ep), "audio": lambda: safe(audio_checks, "audio", ep),
             "stills": lambda: safe(stills, "stills", ep, getattr(args, "from_remotion", False))}
    if args.cmd == "all":
        checks = funcs["probe"]() + safe(freshness, "build", ep) + funcs["audio"]() + funcs["captions"]() + funcs["coverage"]()
        checks += held_out_check(ep, ep.final)
        checks += [check("stills", "skip", "--skip-stills", "")] if args.skip_stills else funcs["stills"]()
        build = build_identity(ep)
        if ep.final:
            checks += final_checks(ep, build)
        result = write_reports(ep, checks, build, ep.final)
        brief = write_judge_brief(ep, build)
        restate = write_restate_brief(ep)
        result["judgeBrief"] = str(brief)
        result["restateBrief"] = str(restate)
    else:
        checks = funcs[args.cmd]()
        ep.qc.mkdir(parents=True, exist_ok=True)
        result = {"slug": ep.slug, "command": args.cmd, "checks": checks,
                  "result": "FAIL" if any(c["status"] == "fail" for c in checks) else "PASS"}
        (ep.qc / f"{args.cmd}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    else:
        for c in checks:
            print(f"{c['status'].upper():<4} {c['id']}: {c['detail']}" + (f"\n     fix: {c['fix']}" if c["fix"] and c["status"] != "pass" else ""))
        if args.cmd == "all":
            print(f"wrote {ep.qc / 'report.md'}, {ep.qc / 'report.json'}, {result['judgeBrief']}, {result['restateBrief']}")
            print(f"build {result['build']['id']}; verdict: {result['verdict']}")
        print("RESULT: " + result["result"])
    return 1 if result["result"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
