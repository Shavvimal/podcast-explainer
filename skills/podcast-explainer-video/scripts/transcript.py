#!/usr/bin/env python3
"""Write the searchable transcript, captions and chapter markers for one episode.

Reads   <workspace>/<slug>/script.json   (required)
        <workspace>/<slug>/timing.json   (required; words[] optional per turn)
        <workspace>/<slug>/facts.json    (optional: Sources section)
        <workspace>/<slug>/outline.json  (optional: chapter titles, newTerms = glossary terms)
        <workspace>/<slug>/brief.json    (optional: concept)
        <workspace>/<slug>/glossary.json (optional: {"terms": [{"term", "definition"}]})
        <workspace>/<slug>/learn.json    (optional: Check yourself chapter, front matter,
                                          glossary definitions from summary.terms)
Writes  <workspace>/<slug>/transcript.md, transcript.json, captions.vtt,
        captions.srt, chapters.ffmetadata
        <workspace>/<slug>/delivery.json (sha256 of every derivative below and above, as
        written, plus the script/timing/learn digests used; qc.py --final verifies each, N06)
        <mp4 folder>/transcript.md, <mp4 name>.srt and .vtt (sidecars beside the video)
        <workspace>/library/<slug>.md and <workspace>/library/index.json
        (one record per slug, replaced in place, sorted by slug; when learn.py has
        already written learn/, the learn fields are registered here too, so the
        two scripts can run in either order)

Glossary: explicit glossary entries, then outline newTerms, each with a definition from
glossary.json or learn.json summary.terms. On-screen labels are never glossary terms.
Backchannels (|oh|) are not in the transcript text: per-turn audio never speaks them, and in
chunk mode they belong to the other host (transcript.json turns[].backchannels).

Usage:
  transcript.py --slug hash-maps [--workspace explainers] [--mp4 PATH]
                [--embed-chapters] [--tags a,b] [--depth quick|standard|deep]
                [--series ID --part N] [--date YYYY-MM-DD]

Reruns are idempotent: the same inputs give byte-identical outputs. The
episode date, tags, depth and series of an existing index record are kept
unless a flag replaces them. Exit code 0 on success, 1 on any error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402

CAPTION_LINE = 42          # characters per caption line
CAPTION_LINES = 2          # lines per caption cue
CAPTION_MAX_MS = 7000      # longest cue
CAPTION_MIN_MS = 700       # shortest cue, when the next cue leaves room
INDEX_VERSION = 1
# Keys learn.py owns in an index record. transcript.py keeps them on every rerun, in this
# order after its own keys (same list as LEARN_KEYS in learn.py), so reruns stay byte-identical.
LEARN_KEYS = ["learningGoal", "misconceptions", "learn", "selfTest", "cards", "openGaps"]


class Fail(Exception):
    """An error with a message that names the file or turn."""


# ---------------------------------------------------------------- helpers

def load_json(path: Path, required: bool) -> dict | None:
    if not path.exists():
        if required:
            raise Fail(f"missing required file: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Fail(f"{path}: invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}") from exc


def write_if_changed(path: Path, text: str) -> bool:
    """Write through an exclusive temporary file (C02); a symbolic link at the target is refused."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and not path.is_symlink() and path.read_text(encoding="utf-8") == text:
        return False
    try:
        pc.atomic_write(path, text)
    except pc.BadId as exc:
        raise Fail(str(exc)) from None
    return True


def mmss(ms: int) -> str:
    """[mm:ss] label. Minutes are not wrapped into hours (72:05 is valid)."""
    s = max(0, int(ms)) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def clock(ms: int, sep: str) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{milli:03d}"


def clean_text(text: str) -> str:
    """Spoken text of the active host (pe_common.spoken_text, shared with tts.py, align.mjs and
    build_manifest.py): Gemini <tags> and |backchannels| are not the host's words."""
    return pc.spoken_text(text)


def yaml_value(value) -> str:
    """JSON is valid YAML flow syntax, so every value is written as JSON."""
    return json.dumps(value, ensure_ascii=False)


def shorten(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "..."


def split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def dedupe(items) -> list:
    seen, out = set(), []
    for item in items:
        key = item.lower() if isinstance(item, str) else json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# ---------------------------------------------------------------- model

def build_episode(ws: Path, slug: str, args, prior: dict | None) -> dict:
    ep_dir = ws / slug
    script = load_json(ep_dir / "script.json", True)
    timing = load_json(ep_dir / "timing.json", True)
    facts = load_json(ep_dir / "facts.json", False) or {}
    outline = load_json(ep_dir / "outline.json", False) or {}
    brief = load_json(ep_dir / "brief.json", False) or {}
    learn = load_json(ep_dir / "learn.json", False)
    gloss_file = load_json(ep_dir / "glossary.json", False) or []
    if isinstance(gloss_file, dict):
        gloss_file = gloss_file.get("terms", [])

    if not isinstance(script.get("segments"), list) or not script["segments"]:
        raise Fail(f"{ep_dir / 'script.json'}: no segments")
    if not isinstance(timing.get("turns"), list) or not timing["turns"]:
        raise Fail(f"{ep_dir / 'timing.json'}: no turns")

    speakers = {s["id"]: s for s in script.get("speakers", [])}
    t_by_id: dict[str, dict] = {}
    for t in timing["turns"]:
        tid = t.get("id")
        if tid in t_by_id:
            raise Fail(f"{ep_dir / 'timing.json'}: turn {tid} appears twice")
        for key in ("startMs", "endMs"):
            if not isinstance(t.get(key), int):
                raise Fail(f"{ep_dir / 'timing.json'}: turn {tid} has no integer {key}")
        if t["endMs"] < t["startMs"]:
            raise Fail(f"{ep_dir / 'timing.json'}: turn {tid} ends before it starts")
        t_by_id[tid] = t

    outline_segs = {s.get("id"): s for s in outline.get("segments", []) if isinstance(s, dict)}
    script_turn_ids = set()
    chapters = []
    for idx, seg in enumerate(script["segments"], start=1):
        oseg = outline_segs.get(seg.get("id"), {})
        turns = []
        for turn in seg.get("turns", []):
            tid = turn.get("id")
            script_turn_ids.add(tid)
            tm = t_by_id.get(tid)
            if tm is None:
                raise Fail(f"turn {tid} (segment {seg.get('id')}) is in script.json but has no timing in timing.json; rerun tts.py")
            spk_id = turn.get("speaker")
            if spk_id not in speakers:
                raise Fail(f"turn {tid}: speaker '{spk_id}' is not in script.json speakers")
            rec = {
                "id": tid,
                "speaker": spk_id,
                "speakerName": speakers[spk_id].get("name", spk_id),
                "startMs": tm["startMs"],
                "endMs": tm["endMs"],
                "text": clean_text(turn.get("text", "")),
                "onScreen": list(turn.get("onScreen", [])),
                "factIds": list(turn.get("factIds", [])),
            }
            bcs = pc.backchannels(turn.get("text", ""))
            if bcs and timing.get("mode") == "chunk":
                other = next((s for s in speakers if s != spk_id), spk_id)
                rec["backchannels"] = [{"speaker": other, "speakerName": speakers[other].get("name", other), "text": b}
                                       for b in bcs]
            hold = turn.get("holdAfterMs", tm.get("holdAfterMs", 0)) or 0
            if hold:
                rec["holdAfterMs"] = int(hold)
                rec["holdStartMs"] = int(tm.get("holdStartMs", tm["endMs"]))
            if isinstance(turn.get("pause"), dict):
                rec["pause"] = {"kind": turn["pause"].get("kind", ""), "prompt": turn["pause"].get("prompt", "")}
            words = tm.get("words")
            if isinstance(words, list) and words:
                rec["words"] = [
                    {"text": w.get("text", ""), "startMs": int(w["startMs"]), "endMs": int(w["endMs"]),
                     "source": w.get("source", "estimated")}
                    for w in words
                ]
            turns.append(rec)
        if not turns:
            raise Fail(f"segment {seg.get('id')} has no turns")
        title = seg.get("title") or oseg.get("title")
        if not title:
            role = (seg.get("role") or "segment").capitalize()
            title = f"{role}: {shorten(seg.get('learningGoal', ''), 50)}" if seg.get("learningGoal") else role
        chapters.append({
            "id": seg.get("id", f"seg{idx:02d}"),
            "index": idx,
            "title": title,
            "role": seg.get("role", ""),
            "learningGoal": seg.get("learningGoal", ""),
            "keyQuestion": oseg.get("keyQuestion", ""),
            "turns": turns,
        })

    extra = sorted(set(t_by_id) - script_turn_ids)
    if extra:
        raise Fail(f"timing.json has turns that script.json does not: {', '.join(extra)}; rerun tts.py after the script edit")

    duration_ms = int(timing.get("durationMs") or max(t["endMs"] for t in timing["turns"]))
    # Chapter times: the first chapter starts at 0 so ffmpeg chapters cover the file.
    for i, ch in enumerate(chapters):
        ch["startMs"] = 0 if i == 0 else ch["turns"][0]["startMs"]
    for i, ch in enumerate(chapters):
        ch["endMs"] = chapters[i + 1]["startMs"] if i + 1 < len(chapters) else duration_ms

    all_turns = [t for ch in chapters for t in ch["turns"]]
    with_words = sum(1 for t in all_turns if "words" in t)
    word_level = "word" if with_words == len(all_turns) else ("mixed" if with_words else "turn")

    # Glossary: explicit entries first, then outline newTerms. Definitions come from the entry,
    # else from learn.json summary.terms (term -> meaning). onScreen labels ("9 of 12", "mod 3")
    # are visual labels, not terms, and are never glossary entries.
    meanings: dict[str, str] = {}
    if isinstance(learn, dict):
        for g in (learn.get("summary") or {}).get("terms", []) or []:
            if isinstance(g, dict) and g.get("term") and g.get("meaning"):
                meanings.setdefault(g["term"].strip().lower(), g["meaning"].strip())
    gloss_raw: list[dict] = []
    for src in (gloss_file, script.get("glossary"), outline.get("glossary"), brief.get("glossary")):
        for g in src or []:
            if isinstance(g, str):
                gloss_raw.append({"term": g, "definition": ""})
            elif isinstance(g, dict) and g.get("term"):
                gloss_raw.append({"term": g["term"], "definition": g.get("definition", "")})
    for oseg in outline.get("segments", []):
        for term in oseg.get("newTerms", []) or []:
            gloss_raw.append({"term": term, "definition": ""})
    if isinstance(learn, dict):
        for g in (learn.get("summary") or {}).get("terms", []) or []:
            if isinstance(g, dict) and g.get("term"):
                gloss_raw.append({"term": g["term"], "definition": g.get("meaning", "")})
    for g in gloss_raw:
        if not g["definition"]:
            g["definition"] = meanings.get(g["term"].strip().lower(), "")
    glossary, seen = [], {}
    for g in gloss_raw:
        key = g["term"].strip().lower()
        if key in seen:
            if g["definition"] and not glossary[seen[key]]["definition"]:
                glossary[seen[key]]["definition"] = g["definition"]
            continue
        seen[key] = len(glossary)
        glossary.append({"term": g["term"].strip(), "definition": g["definition"].strip()})
    for g in glossary:
        first = find_first_mention(g["term"], all_turns)
        g["firstMs"] = first["startMs"] if first else None
        g["turnId"] = first["id"] if first else None
    glossary.sort(key=lambda g: g["term"].lower())

    # Sources: only those that facts.json lists; mark which facts the script uses.
    used_facts = sorted({f for t in all_turns for f in t["factIds"]}, key=fact_key)
    fact_src = {f.get("id"): f.get("sourceId") for f in facts.get("facts", []) if isinstance(f, dict)}
    sources = []
    for s in facts.get("sources", []):
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        sources.append({
            "id": sid, "title": s.get("title", ""), "url": s.get("url", ""),
            "path": s.get("path", ""), "retrieved": s.get("retrieved", ""),
            "factIds": [f for f in used_facts if fact_src.get(f) == sid],
        })

    prior = prior or {}
    tags = split_tags(args.tags) or list(prior.get("tags", []))
    for src in (script.get("tags"), outline.get("tags"), brief.get("tags")):
        tags += list(src or [])
    tags = dedupe([t.strip().lower() for t in tags if isinstance(t, str) and t.strip()])

    depth = args.depth or script.get("depth") or outline.get("depth") or brief.get("depth") or prior.get("depth")
    if not depth:
        minutes = duration_ms / 60000
        depth = "quick" if minutes < 9 else ("standard" if minutes <= 16 else "deep")

    # Input files say `parts` (script/outline schemas); the index says `of`. Map it explicitly.
    series = prior.get("series")
    for src in (script.get("series"), outline.get("series"), brief.get("series")):
        if isinstance(src, dict) and src.get("id"):
            series = {"id": src["id"], "part": src.get("part"), "of": src.get("parts", src.get("of"))}
    if args.series:
        series = {"id": args.series, "part": args.part, "of": (series or {}).get("of")}

    date = args.date or prior.get("date") or brief.get("created") or dt.date.today().isoformat()
    concept = brief.get("concept") or script.get("learningObjective") or outline.get("learningObjective") or script.get("title")

    mp4 = None
    if args.mp4:
        mp4 = Path(args.mp4).expanduser().resolve()
        if not mp4.exists():
            raise Fail(f"--mp4 file not found: {mp4}")
    elif (ep_dir / "out" / "episode.mp4").exists():
        mp4 = (ep_dir / "out" / "episode.mp4").resolve()
    elif prior.get("mp4") and Path(prior["mp4"]).exists():
        mp4 = Path(prior["mp4"])

    t_start = {t["id"]: t["startMs"] for t in all_turns}
    holds = [{"turnId": t["id"], "atMs": t.get("holdStartMs", t["endMs"]), "holdMs": t.get("holdAfterMs", 0),
              "kind": t.get("pause", {}).get("kind", ""),
              "prompt": t.get("pause", {}).get("prompt", "") or t["text"]}
             for t in all_turns if t.get("holdAfterMs") or t.get("pause")]
    self_test = []
    if isinstance(learn, dict):
        for q in learn.get("selfTest", []) or []:
            if isinstance(q, dict) and q.get("question"):
                self_test.append({"question": q["question"], "level": q.get("level", ""),
                                  "turnId": q.get("turn"), "answerMs": t_start.get(q.get("turn"))})
    misconceptions = []
    if isinstance(learn, dict) and isinstance(learn.get("summary", {}).get("misconception"), dict):
        misconceptions.append(learn["summary"]["misconception"].get("claim", ""))
    for m in facts.get("misconceptions", []) or []:
        if isinstance(m, dict) and (m.get("statement") or m.get("wrong") or m.get("claim")):
            misconceptions.append(m.get("statement") or m.get("wrong") or m.get("claim"))
    misconceptions = dedupe([m for m in misconceptions if m])
    analogies = []
    if isinstance(learn, dict) and isinstance(learn.get("summary", {}).get("analogy"), dict):
        a = learn["summary"]["analogy"]
        analogies.append({"analogy": a.get("mapping", ""), "breaksWhere": a.get("breaksWhere", "")})

    return {
        "version": 1,
        "slug": slug,
        "title": script.get("title", slug),
        "concept": concept,
        "tags": tags,
        "date": date,
        "depth": depth,
        "series": series,
        "durationMs": duration_ms,
        "durationSec": round(duration_ms / 1000),
        "wordLevel": word_level,
        "model": timing.get("model", ""),
        "scratchAudio": bool(timing.get("scratch", False)),
        "mp4": str(mp4) if mp4 else None,
        "speakers": [{"id": s["id"], "name": s.get("name", s["id"]), "role": s.get("role", "")}
                     for s in script.get("speakers", [])],
        "learningGoal": script.get("learningObjective") or outline.get("learningObjective") or None,
        "misconceptions": misconceptions,
        "analogies": analogies,
        "learnDir": "learn/" if isinstance(learn, dict) else None,
        "holds": holds,
        "selfTest": self_test,
        "chapters": chapters,
        "glossary": glossary,
        "sources": sources,
    }


def fact_key(fid: str):
    m = re.match(r"f(\d+)$", fid)
    return (0, int(m.group(1))) if m else (1, fid)


def find_first_mention(term: str, turns: list[dict]) -> dict | None:
    low = term.lower()
    for t in turns:
        if any(o.lower() == low for o in t["onScreen"]):
            return t
    pat = re.compile(r"(?<!\w)" + re.escape(low) + r"(?!\w)")
    for t in turns:
        if pat.search(t["text"].lower()):
            return t
    return None


# ---------------------------------------------------------------- markdown

def speaker_labels(speakers: list[dict]) -> list[str]:
    """'Nia (learner)' per speaker. A helper, because nested same-quote f-strings need Python 3.12."""
    return [f"{s['name']} ({s['role']})" if s["role"] else s["name"] for s in speakers]


def render_markdown(ep: dict) -> str:
    fm = [
        "---",
        f"title: {yaml_value(ep['title'])}",
        f"slug: {yaml_value(ep['slug'])}",
        f"concept: {yaml_value(ep['concept'])}",
        f"tags: {yaml_value(ep['tags'])}",
        f"date: {yaml_value(ep['date'])}",
        f"durationSec: {ep['durationSec']}",
        f"depth: {yaml_value(ep['depth'])}",
        f"speakers: {yaml_value(speaker_labels(ep['speakers']))}",
        f"sources: {yaml_value([s['url'] or s['path'] or s['title'] for s in ep['sources']])}",
        f"glossary: {yaml_value([g['term'] for g in ep['glossary']])}",
        f"chapters: {len(ep['chapters'])}",
        f"timing: {yaml_value(ep['wordLevel'])}",
        f"mp4: {yaml_value(ep['mp4'])}",
    ]
    if ep["series"]:
        fm.append(f"series: {yaml_value(ep['series'])}")
    if ep["learningGoal"]:
        fm.append(f"learningGoal: {yaml_value(ep['learningGoal'])}")
    if ep["misconceptions"]:
        fm.append(f"misconceptions: {yaml_value(ep['misconceptions'])}")
    if ep["analogies"]:
        fm.append(f"analogies: {yaml_value(ep['analogies'])}")
    if ep["learnDir"]:
        fm.append(f"learn: {yaml_value(ep['learnDir'])}")
    fm.append("---")

    out = fm + ["", f"# {ep['title']}", ""]
    out.append(f"Concept: {ep['concept']}")
    out.append("")
    hosts = ", ".join(f"{s['name']} ({s['role']})" if s["role"] else s["name"] for s in ep["speakers"])
    out.append(f"Episode: {ep['slug']}. Length {mmss(ep['durationMs'])}. Depth {ep['depth']}. Hosts: {hosts}.")
    out.append("")
    if ep["mp4"]:
        out.append(f"Video: {file_url(ep['mp4'])}")
        out.append("")
    if ep["scratchAudio"]:
        out.append("Note: scratch audio (macOS say voice). Timestamps change after the Gemini pass.")
        out.append("")
    out += ["## Contents", ""]
    for ch in ep["chapters"]:
        out.append(f"- [{mmss(ch['startMs'])}] Chapter {ch['index']}: {ch['title']}")
    if ep["holds"] or ep["selfTest"]:
        out.append("- Check yourself")
    out.append("")
    for ch in ep["chapters"]:
        out.append(f"## [{mmss(ch['startMs'])}] Chapter {ch['index']}: {ch['title']}")
        out.append("")
        if ch["learningGoal"]:
            out.append(f"Goal: {ch['learningGoal']}")
            out.append("")
        for t in ch["turns"]:
            hold = f" [hold {round(t['holdAfterMs'] / 1000)} s]" if t.get("holdAfterMs") else ""
            bc = "".join(f" _({b['speakerName']}: {b['text']})_" for b in t.get("backchannels", []))
            out.append(f"**[{mmss(t['startMs'])}] {t['speakerName']}:** {t['text']}{bc}{hold}")
            out.append("")
    if ep["holds"] or ep["selfTest"]:
        # learning-design.md section 9: hold questions at their time, self-test questions
        # without answers (the answer key lives in learn/selftest.md).
        out += ["## Check yourself", ""]
        for h in ep["holds"]:
            kind = f"{h['kind']}, " if h["kind"] else ""
            secs = f"{round(h['holdMs'] / 1000)} s" if h["holdMs"] else "no hold"
            out.append(f"- [{mmss(h['atMs'])}] Pause ({kind}{secs}): {h['prompt']}")
        if ep["holds"]:
            out.append("")
        if ep["selfTest"]:
            out.append("Self-test (answers in learn/selftest.md):")
            out.append("")
            for i, q in enumerate(ep["selfTest"], 1):
                where = f" Answer explained at [{mmss(q['answerMs'])}]." if q["answerMs"] is not None else ""
                out.append(f"{i}. {q['question']}{where}")
            out.append("")
    out += ["## Glossary", ""]
    if ep["glossary"]:
        for g in ep["glossary"]:
            when = f" [{mmss(g['firstMs'])}]" if g["firstMs"] is not None else ""
            definition = f": {g['definition']}" if g["definition"] else ""
            out.append(f"- **{g['term']}**{when}{definition}")
    else:
        out.append("No glossary terms.")
    out += ["", "## Sources", ""]
    if ep["sources"]:
        for s in ep["sources"]:
            parts = [f"- {s['id']}: {s['title'] or 'Untitled'}."]
            if s["url"] or s["path"]:
                parts.append(f"{s['url'] or s['path']}.")
            if s["retrieved"]:
                parts.append(f"Retrieved {s['retrieved']}.")
            if s["factIds"]:
                parts.append(f"Facts used: {', '.join(s['factIds'])}.")
            out.append(" ".join(parts))
    else:
        out.append("No facts.json for this episode.")
    out.append("")
    return "\n".join(out)


def file_url(path: str, seconds: int | None = None) -> str:
    url = Path(path).resolve().as_uri()
    return f"{url}#t={seconds}" if seconds is not None else url


# ---------------------------------------------------------------- captions

def wrap(text: str, width: int = CAPTION_LINE) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fits(prefix: str, words: list[str]) -> bool:
    lines = wrap(prefix + " ".join(words))
    return len(lines) <= CAPTION_LINES and all(len(l) <= CAPTION_LINE for l in lines)


def turn_tokens(turn: dict) -> list[tuple[str, int, int]]:
    """(text, startMs, endMs) per token. Word times if present, else spread by length."""
    script_words = turn["text"].split()
    words = turn.get("words")
    if words:
        if len(words) == len(script_words):
            return [(sw, w["startMs"], w["endMs"]) for sw, w in zip(script_words, words)]
        return [(w["text"], w["startMs"], w["endMs"]) for w in words if w["text"].strip()]
    start, end = turn["startMs"], turn["endMs"]
    total = sum(len(w) + 1 for w in script_words) or 1
    toks, acc = [], 0
    for w in script_words:
        s = start + (end - start) * acc // total
        acc += len(w) + 1
        e = start + (end - start) * acc // total
        toks.append((w, s, e))
    return toks


def build_cues(ep: dict) -> list[dict]:
    cues = []
    for ch in ep["chapters"]:
        for t in ch["turns"]:
            prefix = f"{t['speakerName']}: "
            toks = turn_tokens(t)
            i = 0
            while i < len(toks):
                group = [toks[i]]
                j = i + 1
                while j < len(toks):
                    cand = group + [toks[j]]
                    if not fits(prefix, [g[0] for g in cand]):
                        break
                    if cand[-1][2] - cand[0][1] > CAPTION_MAX_MS:
                        break
                    group = cand
                    j += 1
                    # Prefer to break after a sentence once the cue is half full.
                    if re.search(r"[.?!]$", group[-1][0]) and len(prefix + " ".join(g[0] for g in group)) >= CAPTION_LINE:
                        break
                cues.append({"turnId": t["id"], "startMs": group[0][1], "endMs": group[-1][2],
                             "lines": wrap(prefix + " ".join(g[0] for g in group))})
                i = j
    # No overlaps; stretch short cues into the gap that follows when possible.
    for k, c in enumerate(cues):
        nxt = cues[k + 1]["startMs"] if k + 1 < len(cues) else ep["durationMs"]
        if c["endMs"] - c["startMs"] < CAPTION_MIN_MS:
            c["endMs"] = min(c["startMs"] + CAPTION_MIN_MS, max(c["endMs"], nxt))
        c["endMs"] = min(c["endMs"], nxt) if nxt > c["startMs"] else c["endMs"]
        if c["endMs"] <= c["startMs"]:
            c["endMs"] = c["startMs"] + 1
    return cues


def render_vtt(cues: list[dict]) -> str:
    out = ["WEBVTT", ""]
    for n, c in enumerate(cues, start=1):
        out += [f"{n}", f"{clock(c['startMs'], '.')} --> {clock(c['endMs'], '.')}", *c["lines"], ""]
    return "\n".join(out)


def render_srt(cues: list[dict]) -> str:
    out = []
    for n, c in enumerate(cues, start=1):
        out += [f"{n}", f"{clock(c['startMs'], ',')} --> {clock(c['endMs'], ',')}", *c["lines"], ""]
    return "\n".join(out)


# ---------------------------------------------------------------- chapters

def ffmeta_escape(text: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", text)


def render_ffmetadata(ep: dict) -> str:
    out = [";FFMETADATA1", f"title={ffmeta_escape(ep['title'])}", ""]
    for ch in ep["chapters"]:
        label = f"{ch['index']}. {ch['title']}"
        out += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={ch['startMs']}", f"END={ch['endMs']}",
                f"title={ffmeta_escape(label)}", ""]
    return "\n".join(out)


def embed_chapters(mp4: Path, meta: Path) -> None:
    if not shutil.which("ffmpeg"):
        raise Fail("--embed-chapters needs ffmpeg on PATH")
    try:  # C02: a new exclusive temp file, never a guessable name that could be a planted link
        tmp = pc.exclusive_temp(mp4.parent, mp4.stem + ".chapters", mp4.suffix)
    except pc.BadId as exc:
        raise Fail(str(exc)) from None
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-f", "ffmetadata", "-i", str(meta),
           # Map only audio and video: the old chapter text track (a data stream)
           # must not be copied, or every rerun adds one more.
           "-map", "0:v", "-map", "0:a?", "-map_metadata", "1", "-map_chapters", "1", "-c", "copy",
           "-movflags", "+faststart", str(tmp)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise Fail(f"ffmpeg could not write chapters into {mp4}: {res.stderr.strip()[-500:]}")
    os.replace(tmp, mp4)


# ---------------------------------------------------------------- library

def index_record(ep: dict, ep_dir: Path, prior: dict | None = None) -> dict:
    rec = {
        "slug": ep["slug"],
        "title": ep["title"],
        "concept": ep["concept"],
        "tags": ep["tags"],
        "date": ep["date"],
        "depth": ep["depth"],
        "series": ep["series"],
        "durationSec": ep["durationSec"],
        "speakers": [s["name"] for s in ep["speakers"]],
        "chapters": [{"id": c["id"], "index": c["index"], "title": c["title"], "startMs": c["startMs"],
                      "startSec": c["startMs"] // 1000, "at": mmss(c["startMs"])} for c in ep["chapters"]],
        "glossary": [g["term"] for g in ep["glossary"]],
        "mp4": ep["mp4"],
        "transcript": str((ep_dir / "transcript.md").resolve()),
        "libraryFile": f"{ep['slug']}.md",
    }
    # Keep the fields learn.py wrote; learningGoal is recomputed with learn.py's rule.
    prior = prior or {}
    for k in LEARN_KEYS:
        if k == "learningGoal":
            if ep["learningGoal"]:
                rec[k] = ep["learningGoal"]
        elif k in prior:
            rec[k] = prior[k]
    return rec


def register_learn(ws: Path, slug: str, record: dict) -> tuple[dict, str | None]:
    """Order-independent learn registration: when learn.py has already written <slug>/learn/,
    compute the learn fields with learn.py's own function and merge them into the record.
    Returns (record, note for the user or None)."""
    ep_dir = ws / slug
    if not (ep_dir / "learn.json").exists():
        return record, None
    if not (ep_dir / "learn" / "selftest.md").exists():
        return record, f"learn.json exists but learn/ does not: run learn.py --slug {slug} (it registers itself)"
    try:
        import learn as learnmod  # same folder
        fields = learnmod.compute_fields(ws, slug)
        return learnmod.merge_record(record, fields), None
    except Exception as exc:  # learn.json invalid: keep what the index had, say so
        return record, f"learn fields not refreshed ({exc}); fix learn.json and run learn.py"


def load_index(path: Path) -> dict:
    data = load_json(path, False)
    if data is None:
        return {"version": INDEX_VERSION, "episodes": []}
    if not isinstance(data.get("episodes"), list):
        raise Fail(f"{path}: no 'episodes' list; fix or delete the file, then rerun")
    return data


def transcript_json(ep: dict, cues: list[dict]) -> dict:
    data = {k: v for k, v in ep.items()}
    data["captions"] = {"cues": len(cues), "maxLines": CAPTION_LINES, "maxCharsPerLine": CAPTION_LINE}
    return data


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="explainers", help="workspace folder (default ./explainers)")
    ap.add_argument("--slug", required=True, help="episode folder name inside the workspace")
    ap.add_argument("--mp4", help="rendered video; default <slug>/out/episode.mp4 when it exists")
    ap.add_argument("--embed-chapters", action="store_true", help="write chapter markers into the mp4 (stream copy, no re-encode)")
    ap.add_argument("--tags", help="comma-separated tags; replaces tags kept from the index")
    ap.add_argument("--depth", choices=["quick", "standard", "deep"])
    ap.add_argument("--series", help="series id, for a deep episode split into parts")
    ap.add_argument("--part", type=int, help="part number inside --series")
    ap.add_argument("--date", help="episode date YYYY-MM-DD (default: kept from the index, else today)")
    args = ap.parse_args(argv)

    try:
        if args.part is not None and not args.series:
            raise Fail("--part needs --series")
        if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
            raise Fail(f"--date must be YYYY-MM-DD, got '{args.date}'")
        ws = Path(args.workspace).expanduser().resolve()
        ep_dir = pc.episode_dir(ws, args.slug)
        if not ep_dir.is_dir():
            raise Fail(f"episode folder not found: {ep_dir}")
        lib = ws / "library"
        index_path = lib / "index.json"
        index = load_index(index_path)
        prior = next((e for e in index["episodes"] if e.get("slug") == args.slug), None)

        ep = build_episode(ws, args.slug, args, prior)
        cues = build_cues(ep)
        md = render_markdown(ep)
        changed = []
        for name, text in [
            ("transcript.md", md),
            # provenance: the digests of the script, timing and learn.json this was built from (qc.py --final, N06)
            ("transcript.json", json.dumps({**transcript_json(ep, cues), "provenance": pc.source_digests(ep_dir)},
                                           indent=2, ensure_ascii=False) + "\n"),
            ("captions.vtt", render_vtt(cues)),
            ("captions.srt", render_srt(cues)),
            ("chapters.ffmetadata", render_ffmetadata(ep)),
        ]:
            if write_if_changed(ep_dir / name, text):
                changed.append(str(ep_dir / name))
        if ep["mp4"]:
            # Sidecar captions next to the mp4 so VLC, IINA and mpv load them by name, and the
            # searchable transcript beside the video so sharing the folder shares both.
            mp4 = Path(ep["mp4"])
            for path, text in ((mp4.with_suffix(".srt"), render_srt(cues)), (mp4.with_suffix(".vtt"), render_vtt(cues)),
                               (mp4.parent / "transcript.md", md)):
                if path.resolve() != (ep_dir / "transcript.md").resolve() and write_if_changed(path, text):
                    changed.append(str(path))
        if write_if_changed(lib / f"{args.slug}.md", md):
            changed.append(str(lib / f"{args.slug}.md"))
        # N06: the sha256 of every delivered derivative as written, so qc.py --final can tell a
        # missing, stale or hand-edited transcript, caption file, library copy or mp4 sidecar.
        record = index_record(ep, ep_dir, prior)
        record, learn_note = register_learn(ws, args.slug, record)
        # Q04 (codex round 4): THIS episode's index record is bound into delivery.json (not the whole
        # multi-episode index), so a corrupted mp4 path, self-test or card list fails qc.py --final.
        delivery = {"sources": pc.source_digests(ep_dir), "files": {},
                    "record": {"slug": args.slug, "sha256": pc.record_digest(record)}}
        for name, path in pc.delivery_paths(ws, args.slug, Path(ep["mp4"]) if ep["mp4"] else None).items():
            delivery["files"][name] = {"path": os.path.relpath(path, ws), "sha256": pc.json_digest(path)}
        if write_if_changed(ep_dir / pc.DELIVERY_FILE, json.dumps(delivery, indent=2, sort_keys=True) + "\n"):
            changed.append(str(ep_dir / pc.DELIVERY_FILE))
        episodes = [e for e in index["episodes"] if e.get("slug") != args.slug] + [record]
        episodes.sort(key=lambda e: e["slug"])
        new_index = {"version": INDEX_VERSION, "episodes": episodes}
        if write_if_changed(index_path, json.dumps(new_index, indent=2, ensure_ascii=False) + "\n"):
            changed.append(str(index_path))

        if args.embed_chapters:
            if not ep["mp4"]:
                raise Fail("--embed-chapters needs an mp4: pass --mp4 or render <slug>/out/episode.mp4 first")
            embed_chapters(Path(ep["mp4"]), ep_dir / "chapters.ffmetadata")
            changed.append(f"{ep['mp4']} (chapters)")

        print(f"transcript: {args.slug}: {len(ep['chapters'])} chapters, "
              f"{sum(len(c['turns']) for c in ep['chapters'])} turns, {len(cues)} caption cues, "
              f"timing {ep['wordLevel']}, {mmss(ep['durationMs'])}")
        print("changed:" if changed else "unchanged: all outputs already current")
        for c in changed:
            print(f"  {c}")
        if learn_note:
            print(f"note: {learn_note}", file=sys.stderr)
        return 0
    except pc.BadId as exc:
        print(f"transcript.py: error: {exc}", file=sys.stderr)
        return 1
    except Fail as exc:
        print(f"transcript.py: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
