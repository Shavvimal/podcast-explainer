#!/usr/bin/env python3
"""Turn <slug>/learn.json into the learner's after-video work and register it in the library.

Reads   <workspace>/<slug>/learn.json    (required; schemas/learn.schema.json)
        <workspace>/<slug>/script.json   (required: turn and segment ids)
        <workspace>/<slug>/timing.json   (required: [mm:ss] of each cited turn)
Writes  <workspace>/<slug>/learn/selftest.md   5 questions, then the answer key with [mm:ss]
        <workspace>/<slug>/learn/teachback.md  task, required ideas, self-score, chat prompt
        <workspace>/<slug>/learn/cards.csv     Anki import: no header, TAB separated,
                                               columns front, back, tags
        <workspace>/<slug>/learn/cards.md      the same cards, readable, with [mm:ss]
        <workspace>/<slug>/learn/summary.md    one page
        <workspace>/<slug>/learn/gaplog.md     seeded once; rows the learner adds are never removed;
                                               the Rewatch cell holds "[mm:ss] (tNN)" and the time
                                               is refreshed from timing.json on every run
        <workspace>/<slug>/learn/provenance.json  digests of script.json, timing.json and learn.json
                                               used, and of the five generated files (qc.py --final)
        <workspace>/library/learn/<slug>/      copies of the six files (grep, qmd, cairn)
        <workspace>/library/index.json         the slug's record gains learn, selfTest,
                                               cards, openGaps, learningGoal, misconceptions

Usage:
  learn.py --slug hash-maps [--workspace explainers] [--json]

Run it after timing.json exists (after tts.py), before or after transcript.py: both
scripts register the learn fields with compute_fields(), so the order does not matter.
If the library has no record for the slug yet, learn/ is still written and transcript.py
registers it when it runs.
Reruns are idempotent: the same inputs give byte-identical files and print
`unchanged`. Exit code 0 on success, 1 on any error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA = SKILL_DIR / "schemas" / "learn.schema.json"
LEARN_FILES = ["selftest.md", "teachback.md", "cards.csv", "cards.md", "summary.md", "gaplog.md"]
# Keys learn.py owns in a library/index.json record, in this order after transcript.py's keys.
# transcript.py uses the same list (LEARN_KEYS) so that both scripts write identical records.
LEARN_KEYS = ["learningGoal", "misconceptions", "learn", "selfTest", "cards", "openGaps"]
SUMMARY_MAX_WORDS = 400
DEFAULT_SELFTEST_COUNT = 5   # brief.json selfTestCount overrides (3 to 8)
ANALOGY_CARD_RE = re.compile(r"\bwhere\b.*\bbreaks?\b|\bbreaks?\s+down\b|\blimits?\s+of\s+the\b.*\banalogy\b", re.I)
GAP_HEADER = "| Date | Question I could not answer | Where I got stuck | Rewatch | Status | Closed by |"
GAP_RULE = "| --- | --- | --- | --- | --- | --- |"


class Fail(Exception):
    """An error with a message that names the file, the item or the turn."""


# ---------------------------------------------------------------- helpers

def load_json(path: Path, required: bool = True):
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
    s = max(0, int(ms)) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def one_line(text: str) -> str:
    """One paragraph per line; tabs would break the Anki TSV."""
    return re.sub(r"\s+", " ", str(text)).strip()


def learning_goal(script: dict, outline: dict) -> str | None:
    """Same rule as transcript.py, so both scripts write the same record."""
    return script.get("learningObjective") or outline.get("learningObjective") or None


# ---------------------------------------------------------------- schema

def _resolve(ref: str, root: dict) -> dict:
    node = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def mini_validate(value, schema: dict, root: dict, where: str = "(root)") -> list[str]:
    """Checks the keyword subset learn.schema.json uses, for machines without jsonschema."""
    if "$ref" in schema:
        return mini_validate(value, _resolve(schema["$ref"], root), root, where)
    errs: list[str] = []
    types = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}
    t = schema.get("type")
    if t and not (isinstance(value, types[t]) and not (t in ("integer", "number") and isinstance(value, bool))):
        return [f"{where}: expected {t}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errs.append(f"{where}: must be {json.dumps(schema['const'])}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {json.dumps(value)} is not one of {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{where}: missing required field '{key}'")
        for key, sub in value.items():
            if key in props:
                errs += mini_validate(sub, props[key], root, f"{where}.{key}" if where != "(root)" else key)
            elif schema.get("additionalProperties") is False:
                errs.append(f"{where}: unknown field '{key}' (allowed: {', '.join(props)})")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{where}: needs at least {schema['minItems']} items, has {len(value)}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{where}: allows at most {schema['maxItems']} items, has {len(value)}")
        if "items" in schema:
            for i, item in enumerate(value):
                errs += mini_validate(item, schema["items"], root, f"{where}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{where}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{where}: longer than {schema['maxLength']} characters ({len(value)})")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{where}: {json.dumps(value)} does not match {schema['pattern']}")
    return errs


def schema_errors(data) -> list[str]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return mini_validate(data, schema, schema)
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))]


# ---------------------------------------------------------------- model

def load_episode(ws: Path, slug: str) -> tuple[dict, dict, dict, dict, dict, list[str]]:
    try:
        ep_dir = pc.episode_dir(ws, slug)
    except pc.BadId as e:
        raise Fail(str(e)) from None
    if not ep_dir.is_dir():
        raise Fail(f"episode folder not found: {ep_dir}")
    learn = load_json(ep_dir / "learn.json")
    errs = schema_errors(learn)
    if errs:
        raise Fail(f"{ep_dir / 'learn.json'} fails schemas/learn.schema.json:\n  " + "\n  ".join(errs))
    script = load_json(ep_dir / "script.json")
    timing = load_json(ep_dir / "timing.json")
    outline = load_json(ep_dir / "outline.json", False) or {}
    if learn["slug"] != slug:
        raise Fail(f"learn.json slug '{learn['slug']}' differs from --slug '{slug}'")
    # R05: exactly one designated held-out item at transfer or apply level (qc.py brief.heldout).
    held = pc.held_out_items(learn)
    if len(held) > 1:
        raise Fail(f"learn.json: {len(held)} selfTest items have heldOut: true; designate exactly one")
    if held and held[0].get("level") not in pc.HELD_OUT_LEVELS:
        raise Fail(f"learn.json: the heldOut selfTest item has level '{held[0].get('level')}'; use transfer or apply")

    seg_of: dict[str, str] = {}
    for seg in script.get("segments", []):
        for t in seg.get("turns", []):
            seg_of[t.get("id")] = seg.get("id")
    start_of = {t.get("id"): t.get("startMs") for t in timing.get("turns", [])}

    problems: list[str] = []

    def turn_ms(tid: str, where: str, segment: str | None = None) -> int | None:
        if tid not in seg_of:
            problems.append(f"{where}: turn {tid} is not in script.json")
            return None
        if not isinstance(start_of.get(tid), int):
            problems.append(f"{where}: turn {tid} has no timing in timing.json; rerun tts.py, then learn.py")
            return None
        if segment and seg_of[tid] != segment:
            problems.append(f"{where}: turn {tid} is in {seg_of[tid]}, not in segment {segment}")
        return start_of[tid]

    times = {}
    for i, q in enumerate(learn["selfTest"], 1):
        if q["segment"] not in set(seg_of.values()):
            problems.append(f"selfTest[{i}]: segment {q['segment']} is not in script.json")
        times[("q", i)] = turn_ms(q["turn"], f"selfTest[{i}]", q["segment"])
    for i, c in enumerate(learn["cards"], 1):
        times[("c", i)] = turn_ms(c["turnId"], f"cards[{i}]")
    for i, g in enumerate(learn["gapLog"], 1):
        times[("g", i)] = turn_ms(g["turn"], f"gapLog[{i}]")
    if problems:
        raise Fail(f"{ep_dir / 'learn.json'}: {len(problems)} reference problem(s):\n  " + "\n  ".join(problems))

    warnings = []
    # Judge v6 lessons (3 Nov 2026): the self-test spec is enforced, not advised. Exactly
    # brief.selfTestCount items (default 5), at least one at apply or transfer level, at most one
    # at remember level (rule L12), so at least one item asks for more than recall.
    brief = load_json(ep_dir / "brief.json", False) or {}
    want = brief.get("selfTestCount", DEFAULT_SELFTEST_COUNT)
    if not (isinstance(want, int) and not isinstance(want, bool) and 3 <= want <= 8):
        raise Fail(f"brief.json selfTestCount must be an integer 3 to 8, got {want!r}")
    levels = [q["level"] for q in learn["selfTest"]]
    spec = []
    if len(levels) != want:
        spec.append(f"selfTest has {len(levels)} questions; the spec is exactly {want} (learning-design.md 8.1; "
                    "brief.json selfTestCount overrides the default 5)")
    if not any(lv in ("apply", "transfer") for lv in levels):
        spec.append("selfTest has no apply or transfer question; at least one must make the learner use the mechanism on a new case")
    remember = levels.count("remember")
    if remember > 1:
        spec.append(f"selfTest has {remember} remember-level questions; at most 1 (rule L12)")
    # Judge v6 lesson (b): an analogy segment needs its analogy-limit card.
    roles = {s.get("role") for s in script.get("segments", []) if isinstance(s, dict)}
    roles |= {s.get("role") for s in outline.get("segments", []) if isinstance(s, dict)}
    if "analogy" in roles and not any(ANALOGY_CARD_RE.search(c["front"]) for c in learn["cards"]):
        name = one_line((learn["summary"].get("analogy") or {}).get("mapping", "") or "<analogy>")[:40]
        spec.append(f"the episode has an analogy segment but no analogy-limit card; add a card 'Where does the {name} "
                    "analogy break?' (learning-design.md 8.4)")
    if spec:
        raise Fail(f"{ep_dir / 'learn.json'}: {len(spec)} self-test or card spec problem(s):\n  " + "\n  ".join(spec))
    for i, c in enumerate(learn["cards"], 1):
        if not c["front"].rstrip().endswith("?") and not c["front"].lower().startswith("true or false"):
            warnings.append(f"cards[{i}] front is not a question; fronts ask for the mechanism")
    if not pc.held_out_items(learn):
        warnings.append("no selfTest item has heldOut: true; mark the ONE transfer or apply question the video never "
                        "demonstrates (qc.py --final fails without it)")
    return learn, script, timing, outline, {"times": times, "seg_of": seg_of, "start_of": start_of}, warnings


def mp4_path(ws: Path, slug: str, record: dict | None) -> str | None:
    local = ws / slug / "out" / "episode.mp4"
    if local.exists():
        return str(local.resolve())
    if record and record.get("mp4") and Path(record["mp4"]).exists():
        return record["mp4"]
    return None


def link(mp4: str | None, ms: int) -> str:
    return f"{Path(mp4).as_uri()}#t={int(ms) // 1000}" if mp4 else ""


# ---------------------------------------------------------------- renderers

def render_selftest(learn: dict, ctx: dict, mp4: str | None) -> str:
    slug = learn["slug"]
    out = [f"# Self-test: {one_line(learn['title'])}", "",
           "Answer aloud or on paper before you open the key. Then log every miss in gaplog.md.", "",
           "## Questions", ""]
    for i, q in enumerate(learn["selfTest"], 1):
        out.append(f"{i}. ({q['level']}) {one_line(q['question'])}")
    out += ["", "## Answer key", ""]
    for i, q in enumerate(learn["selfTest"], 1):
        ms = ctx["times"][("q", i)]
        rewatch = f" Rewatch: {link(mp4, ms)}" if mp4 else ""
        out.append(f"{i}. {one_line(q['answer'])} Explained at [{mmss(ms)}] ({q['segment']}, {q['turn']}). "
                   f"Cite [{slug} {mmss(ms)}].{rewatch}")
    out.append("")
    return "\n".join(out)


def render_teachback(learn: dict) -> str:
    tb = learn["teachBack"]
    out = [f"# Teach-back: {one_line(learn['title'])}", "", "## Task", "", one_line(tb["task"]), "",
           "## Required ideas", ""]
    out += [f"- [ ] {one_line(i)}" for i in tb["requiredIdeas"]]
    out += ["", f"Must not claim: {one_line(tb['mustNotClaim'])}", "",
            "## Score yourself", "",
            "Tick the ideas you covered. Put each missed idea in gaplog.md with the timestamp to rewatch (see selftest.md answer key).", "",
            "## Interactive version", "",
            "Paste this into a chat model:", "", "```text", one_line(tb["interactivePrompt"]), "```", ""]
    return "\n".join(out)


def render_cards_csv(learn: dict, ctx: dict) -> str:
    slug = learn["slug"]
    rows = []
    for i, c in enumerate(learn["cards"], 1):
        ms = ctx["times"][("c", i)]
        seg = ctx["seg_of"][c["turnId"]]
        back = f"{one_line(c['back'])} [{slug} {mmss(ms)}]"
        tags = f"explainer::{slug} {seg}"
        rows.append("\t".join([one_line(c["front"]), back, tags]))
    return "\n".join(rows) + "\n"


def render_cards_md(learn: dict, ctx: dict, mp4: str | None) -> str:
    slug = learn["slug"]
    out = [f"# Cards: {one_line(learn['title'])}", "",
           "Import cards.csv into Anki: File, Import, Type Basic, separator Tab, fields Front, Back, Tags. Suggested reviews: day 1, 3, 7 and 21.", ""]
    for i, c in enumerate(learn["cards"], 1):
        ms = ctx["times"][("c", i)]
        seg = ctx["seg_of"][c["turnId"]]
        out.append(f"{i}. **Q:** {one_line(c['front'])}")
        tail = f" {link(mp4, ms)}" if mp4 else ""
        out.append(f"   **A:** {one_line(c['back'])} [{slug} {mmss(ms)}] ({seg}, {c['turnId']}){tail}")
        out.append("")
    return "\n".join(out)


def hero_still(learn: dict, ws: Path) -> Path | None:
    """Q10 (codex round 4): summary.heroStill, only when the file exists inside the episode folder
    (a still from the delivered mp4, e.g. qc/stills/<name>.png from qc.py all). Otherwise None: the
    summary omits the image and main() warns, so the page never links to a missing file."""
    rel = (learn.get("summary") or {}).get("heroStill")
    if not rel:
        return None
    ep = (ws / learn["slug"]).resolve()
    try:
        p = pc.inside(ep, ep / rel, "summary.heroStill")
    except pc.BadId:
        return None
    return p if p.is_file() else None


def render_summary(learn: dict, ws: Path) -> tuple[str, int]:
    s = learn["summary"]
    out = [f"# Summary: {one_line(learn['title'])}", "", "## Puzzle and answer", "",
           f"Puzzle: {one_line(s['puzzle'])}", "", f"Answer: {one_line(s['answer'])}", "",
           "## Plain explanation", "", one_line(s["plain"]), "", "## Mechanism", ""]
    out += [f"{i}. {one_line(step)}" for i, step in enumerate(s["mechanism"], 1)]
    still = hero_still(learn, ws)
    if still is not None:
        out += ["", f"![Mechanism]({still.as_uri()})"]
    out += ["", "## Terms", ""]
    out += [f"- **{one_line(t['term'])}**: {one_line(t['meaning'])}" for t in s["terms"]] or ["No new terms."]
    out += ["", "## Misconception", "", f"Claim: {one_line(s['misconception']['claim'])}", "",
            f"Why it fails: {one_line(s['misconception']['whyFails'])}", ""]
    if s.get("analogy"):
        out += ["## Analogy", "", f"Mapping: {one_line(s['analogy']['mapping'])}", "",
                f"Where it breaks: {one_line(s['analogy']['breaksWhere'])}", ""]
    out += ["## Still open", ""]
    out += [f"- {one_line(x)}" for x in s.get("stillOpen", [])] or ["Nothing simplified on purpose."]
    out.append("")
    text = "\n".join(out)
    body = text.split("\n", 1)[1]
    return text, len(re.findall(r"[A-Za-z0-9]+", re.sub(r"!\[.*?\]\(.*?\)", "", body)))


REWATCH_RE = re.compile(r"\[(\d{2,}:\d{2})\](?:\s*\((t\d{2,3})\))?")


def rewatch_cell(ms: int, tid: str) -> str:
    return f"[{mmss(ms)}] ({tid})"


def gap_row(date: str, g: dict, ms: int) -> str:
    cells = [date, one_line(g["question"]), one_line(g.get("where") or "n/a"), rewatch_cell(ms, g["turn"]),
             g.get("status", "open"), ""]
    return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |"


def refresh_row(row: str, seed_turn: dict[str, str], start_of: dict) -> str:
    """Move a row's Rewatch time to the cited turn's current start. Every other cell (the
    learner's status, notes and closed-by) is kept byte for byte."""
    cells = row.split("|")
    if len(cells) < 8 or cells[1].strip().lower() == "date" or set(cells[1].strip()) <= {"-", " "}:
        return row
    question = one_line(cells[2]).lower()
    m = REWATCH_RE.search(cells[4])
    tid = (m.group(2) if m and m.group(2) else None) or seed_turn.get(question)
    if not tid or not isinstance(start_of.get(tid), int):
        return row
    new = rewatch_cell(start_of[tid], tid)
    cells[4] = f" {REWATCH_RE.sub(new, cells[4], count=1)} " if m else f" {new} "
    cells[4] = " " + cells[4].strip() + " "
    return "|".join(cells)


def render_gaplog(learn: dict, ctx: dict, existing: str | None) -> str:
    """Seed once. On reruns keep every existing row, refresh each row's Rewatch time from its
    turn id (seed rows and learner rows that cite a turn), and append seed rows whose question is new."""
    today = dt.date.today().isoformat()
    if existing is None:
        out = [f"# Gap log: {one_line(learn['title'])}", "",
               "One row per question you could not answer. Seed rows are points the episode simplified on purpose. Add your own rows; learn.py never removes them. Write a turn id in the Rewatch cell, like [04:10] (t31), and learn.py keeps the time current after a redo. The next episode in a series reads the open rows.", "",
               GAP_HEADER, GAP_RULE]
        out += [gap_row(today, g, ctx["times"][("g", i)]) for i, g in enumerate(learn["gapLog"], 1)]
        return "\n".join(out) + "\n"
    seed_turn = {one_line(g["question"]).lower(): g["turn"] for g in learn["gapLog"]}
    lines = existing.rstrip("\n").split("\n")
    lines = [refresh_row(r, seed_turn, ctx.get("start_of", {})) if r.startswith("|") else r for r in lines]
    have = {one_line(r.split("|")[2]).lower() for r in lines if r.startswith("|") and r.count("|") >= 7}
    new = [gap_row(today, g, ctx["times"][("g", i)]) for i, g in enumerate(learn["gapLog"], 1)
           if one_line(g["question"]).lower() not in have]
    if new:
        # Insert after the last table row so the table stays one block.
        last = max((i for i, r in enumerate(lines) if r.startswith("|")), default=len(lines) - 1)
        lines[last + 1:last + 1] = new
    out = "\n".join(lines) + "\n"
    return existing if out == existing else out


def open_gaps(gaplog: str) -> int:
    n = 0
    for r in gaplog.split("\n"):
        cells = [c.strip().lower() for c in r.strip().strip("|").split("|")]
        if r.startswith("|") and len(cells) >= 6 and cells[4] == "open":
            n += 1
    return n


# ---------------------------------------------------------------- library

def learn_fields(learn: dict, ctx: dict, script: dict, outline: dict, ws: Path, gaplog: str) -> dict:
    slug = learn["slug"]
    d = (ws / slug / "learn").resolve()
    fields = {}
    goal = learning_goal(script, outline)
    if goal:
        fields["learningGoal"] = goal
    fields["misconceptions"] = [one_line(learn["summary"]["misconception"]["claim"])]
    fields["learn"] = {"dir": str(d), "selfTest": str(d / "selftest.md"), "teachBack": str(d / "teachback.md"),
                       "cards": str(d / "cards.csv"), "summary": str(d / "summary.md"), "gapLog": str(d / "gaplog.md"),
                       "libraryDir": f"learn/{slug}"}
    fields["selfTest"] = [{"question": one_line(q["question"]), "level": q["level"], "answer": one_line(q["answer"]),
                           "segment": q["segment"], "turn": q["turn"], "t": ctx["times"][("q", i)] // 1000}
                          for i, q in enumerate(learn["selfTest"], 1)]
    fields["cards"] = [{"front": one_line(c["front"]), "back": one_line(c["back"]), "turn": c["turnId"],
                        "t": ctx["times"][("c", i)] // 1000} for i, c in enumerate(learn["cards"], 1)]
    fields["openGaps"] = open_gaps(gaplog)
    return fields


def compute_fields(ws: Path, slug: str) -> dict:
    """The learn fields of the library record, from learn.json, timing.json and the gap log on
    disk (or its seed). transcript.py calls this too, so registration does not depend on order."""
    learn, script, timing, outline, ctx, _ = load_episode(ws, slug)
    gap_path = ws / slug / "learn" / "gaplog.md"
    gaplog = render_gaplog(learn, ctx, gap_path.read_text(encoding="utf-8") if gap_path.exists() else None)
    return learn_fields(learn, ctx, script, outline, ws, gaplog)


def merge_record(record: dict, fields: dict) -> dict:
    """transcript.py's keys first, then LEARN_KEYS in a fixed order."""
    base = {k: v for k, v in record.items() if k not in LEARN_KEYS}
    for k in LEARN_KEYS:
        if k in fields:
            base[k] = fields[k]
    return base


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="explainers", help="workspace folder (default ./explainers)")
    ap.add_argument("--slug", required=True, help="episode folder name inside the workspace")
    ap.add_argument("--json", action="store_true", help="print a JSON report instead of text")
    args = ap.parse_args(argv)

    try:
        ws = Path(args.workspace).expanduser().resolve()
        learn, script, timing, outline, ctx, warnings = load_episode(ws, args.slug)
        out_dir = pc.inside(ws, ws / args.slug / "learn", "learn folder")
        lib = ws / "library"
        index_path = lib / "index.json"
        index = load_json(index_path, False)
        if index is not None and not isinstance(index.get("episodes"), list):
            raise Fail(f"{index_path}: no 'episodes' list; fix or delete it, then rerun transcript.py")
        record = next((e for e in (index or {}).get("episodes", []) if e.get("slug") == args.slug), None)
        mp4 = mp4_path(ws, args.slug, record)

        gap_path = out_dir / "gaplog.md"
        gaplog = render_gaplog(learn, ctx, gap_path.read_text(encoding="utf-8") if gap_path.exists() else None)
        summary, summary_words = render_summary(learn, ws)
        if learn["summary"].get("heroStill") and hero_still(learn, ws) is None:
            warnings.append(f"summary.heroStill {learn['summary']['heroStill']!r} does not exist inside {ws / args.slug}; the "
                            "image is omitted. Point it at a still from the delivered mp4 (qc/stills/*.png after qc.py all)")
        if summary_words > SUMMARY_MAX_WORDS:
            warnings.append(f"summary.md has about {summary_words} words; the spec is one page, at most about {SUMMARY_MAX_WORDS}")
        files = {
            "selftest.md": render_selftest(learn, ctx, mp4),
            "teachback.md": render_teachback(learn),
            "cards.csv": render_cards_csv(learn, ctx),
            "cards.md": render_cards_md(learn, ctx, mp4),
            "summary.md": summary,
            "gaplog.md": gaplog,
        }
        changed = []
        for name in LEARN_FILES:
            if write_if_changed(out_dir / name, files[name]):
                changed.append(str(out_dir / name))
        # Provenance (N06): what these files were built from and their digests as written, so
        # qc.py --final can tell a stale or hand-edited learn/ file. gaplog.md is the learner's, not tracked.
        prov = {"sources": pc.source_digests(ws / args.slug),
                "files": {n: pc.json_digest(out_dir / n) for n in LEARN_FILES if n != "gaplog.md"}}
        if write_if_changed(out_dir / "provenance.json", json.dumps(prov, indent=2) + "\n"):
            changed.append(str(out_dir / "provenance.json"))
        lib_dir = pc.inside(lib, lib / "learn" / args.slug, "library learn folder")
        for name in LEARN_FILES:
            if write_if_changed(lib_dir / name, files[name]):
                changed.append(str(lib_dir / name))

        registered = False
        if record is not None:
            fields = learn_fields(learn, ctx, script, outline, ws, gaplog)
            new_rec = merge_record(record, fields)
            episodes = [new_rec if e.get("slug") == args.slug else e for e in index["episodes"]]
            text = json.dumps({**index, "episodes": episodes}, indent=2, ensure_ascii=False) + "\n"
            if write_if_changed(index_path, text):
                changed.append(str(index_path))
            registered = True
        else:
            warnings.append(f"no record for '{args.slug}' in {index_path} yet: transcript.py --slug {args.slug} "
                            f"registers the learn files when it runs (no second learn.py run needed)")

        report = {"slug": args.slug, "learnDir": str(out_dir), "libraryDir": str(lib_dir),
                  "selfTest": len(learn["selfTest"]), "cards": len(learn["cards"]), "openGaps": open_gaps(gaplog),
                  "summaryWords": summary_words, "registered": registered, "changed": changed, "warnings": warnings}
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"learn: {args.slug}: {report['selfTest']} self-test questions, {report['cards']} cards, "
                  f"{report['openGaps']} open gaps, summary {summary_words} words, "
                  f"{'registered in' if registered else 'NOT registered in'} {index_path}")
            print("changed:" if changed else "unchanged: all outputs already current")
            for c in changed:
                print(f"  {c}")
            for w in warnings:
                print(f"warning: {w}", file=sys.stderr)
        return 0
    except Fail as exc:
        print(f"learn.py: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
