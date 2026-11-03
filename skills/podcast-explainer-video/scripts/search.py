#!/usr/bin/env python3
"""Search the explainer library and jump to the moment in the video.

Usage:
  search.py "query" [--library DIR] [--limit 10] [--json] [--slug X] [--tag T]
                    [--engine auto|rg|bm25] [--open [--hit N] [--dry-run]]
  search.py --list [--library DIR] [--tag T] [--json]

The library is the folder transcript.py writes: <slug>.md files (one per
episode) and index.json, plus learn/<slug>/selftest.md and cards.md that
learn.py writes. Default library: $EXPLAINERS_LIBRARY, else ./explainers/library.

Chunks searched: transcript turns, chapter goal lines, glossary entries,
pause prompts (Check yourself chapter), self-test questions with their
answers, and card fronts with their backs. Self-test and card hits carry the
[mm:ss] of the turn that explains them, so the deep link goes there.

Engines:
  rg    exact phrase, case-insensitive, through ripgrep (needs `rg` on PATH)
  bm25  pure-Python BM25 over turn-level chunks, with boosts for words in the
        episode title, tags and glossary terms
  auto  (default) rg phrase hits first when rg exists, then BM25 hits

Each hit prints the episode, chapter, [mm:ss], speaker, a snippet with the
match marked, a citation tag and a deep link file:///.../episode.mp4#t=SECONDS.
--open starts a player at the timestamp of hit N (default 1) on macOS.
Exit code 0 with hits, 1 on error, 2 when nothing matched.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

TURN_RE = re.compile(r"^\*\*\[(\d+):(\d{2})\] (.+?):\*\* (.*)$")
CHAPTER_RE = re.compile(r"^## \[(\d+):(\d{2})\] Chapter (\d+): (.*)$")
GLOSS_RE = re.compile(r"^- \*\*(.+?)\*\*(?: \[(\d+):(\d{2})\])?(?:: (.*))?$")
PAUSE_RE = re.compile(r"^- \[(\d+):(\d{2})\] Pause \((.*?)\): (.*)$")
SELFTEST_Q_RE = re.compile(r"^(\d+)\. \((\w+)\) (.*)$")
SELFTEST_A_RE = re.compile(r"^(\d+)\. (.*?) Explained at \[(\d+):(\d{2})\]")
CARD_Q_RE = re.compile(r"^(\d+)\. \*\*Q:\*\* (.*)$")
CARD_A_RE = re.compile(r"^\s+\*\*A:\*\* (.*?) \[[a-z0-9-]+ (\d+):(\d{2})\]")
STOP = set("a an and are as at be but by do does for from how i in is it its of on or so that the this to was what when where which who why will with you".split())
BOLD, RESET = "\033[1m", "\033[0m"


class Fail(Exception):
    pass


# ---------------------------------------------------------------- loading

def parse_front_matter(lines: list[str]) -> tuple[dict, int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return meta, i + 1
        if ":" in line:
            key, raw = line.split(":", 1)
            raw = raw.strip()
            try:
                meta[key.strip()] = json.loads(raw)
            except json.JSONDecodeError:
                meta[key.strip()] = raw
    return meta, 0


def load_library(lib: Path) -> tuple[list[dict], list[dict]]:
    """Return (episodes, chunks). One chunk per turn, chapter goal and glossary entry."""
    if not lib.is_dir():
        raise Fail(f"library folder not found: {lib} (run transcript.py first, or pass --library)")
    index = {}
    index_path = lib / "index.json"
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            index = {e["slug"]: e for e in data.get("episodes", []) if isinstance(e, dict) and e.get("slug")}
        except (json.JSONDecodeError, KeyError) as exc:
            raise Fail(f"{index_path}: cannot read ({exc}); rerun transcript.py for any episode to rebuild it") from exc

    episodes, chunks = [], []
    for md in sorted(lib.glob("*.md")):
        lines = md.read_text(encoding="utf-8").split("\n")
        meta, body_start = parse_front_matter(lines)
        slug = meta.get("slug") or md.stem
        rec = index.get(slug, {})
        ep = {
            "slug": slug,
            "title": rec.get("title") or meta.get("title") or slug,
            "tags": [t.lower() for t in (rec.get("tags") or meta.get("tags") or [])],
            "glossary": rec.get("glossary") or meta.get("glossary") or [],
            "depth": rec.get("depth") or meta.get("depth"),
            "series": rec.get("series") or meta.get("series"),
            "durationSec": rec.get("durationSec") or meta.get("durationSec") or 0,
            "date": rec.get("date") or meta.get("date"),
            "mp4": rec.get("mp4") or meta.get("mp4"),
            "chapters": rec.get("chapters") or [],
            "file": str(md.resolve()),
        }
        episodes.append(ep)
        chapter, ch_index, ch_ms, section = "", 0, 0, ""
        for n in range(body_start, len(lines)):
            line = lines[n]
            m = CHAPTER_RE.match(line)
            if m:
                ch_ms = (int(m.group(1)) * 60 + int(m.group(2))) * 1000
                ch_index, chapter, section = int(m.group(3)), m.group(4), "chapter"
                continue
            if line.startswith("## "):
                section = line[3:].strip().lower()
                continue
            base = {"slug": slug, "episode": ep, "file": ep["file"], "line": n + 1}
            m = TURN_RE.match(line)
            if m and section == "chapter":
                ms = (int(m.group(1)) * 60 + int(m.group(2))) * 1000
                chunks.append({**base, "kind": "turn", "chapter": chapter, "chapterIndex": ch_index,
                               "ms": ms, "speaker": m.group(3), "text": m.group(4)})
            elif section == "chapter" and line.startswith("Goal: "):
                chunks.append({**base, "kind": "goal", "chapter": chapter, "chapterIndex": ch_index,
                               "ms": ch_ms, "speaker": "", "text": line})
            elif section == "glossary":
                g = GLOSS_RE.match(line)
                if g:
                    ms = (int(g.group(2)) * 60 + int(g.group(3))) * 1000 if g.group(2) else 0
                    ch_title, ch_idx = chapter_at(ep, ms)
                    chunks.append({**base, "kind": "glossary", "chapter": ch_title,
                                   "chapterIndex": ch_idx, "ms": ms, "speaker": "", "mentioned": bool(g.group(2)),
                                   "term": g.group(1), "text": f"{g.group(1)}: {g.group(4) or ''}".strip()})
            elif section == "check yourself":
                p = PAUSE_RE.match(line)
                if p:
                    ms = (int(p.group(1)) * 60 + int(p.group(2))) * 1000
                    ch_title, ch_idx = chapter_at(ep, ms)
                    chunks.append({**base, "kind": "pause", "chapter": ch_title, "chapterIndex": ch_idx,
                                   "ms": ms, "speaker": "", "text": f"Pause ({p.group(3)}): {p.group(4)}"})
        if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(slug)):  # never follow a crafted slug out of the library
            chunks += learn_chunks(lib / "learn" / slug, ep)
    link_series_glossary(chunks)
    return episodes, chunks


def _series_id(ep: dict):
    s = ep.get("series")
    return s.get("id") if isinstance(s, dict) else (s if isinstance(s, str) else None)


def link_series_glossary(chunks: list[dict]) -> None:
    """W16 (W14b D18): a series shares one glossary, so a part lists terms it never speaks (no first
    mention, filed at [00:00]). Such an entry links to the part whose transcript first mentions
    the term, so a search lands on the part that teaches it."""
    taught = {}
    for c in chunks:
        if c["kind"] == "glossary" and c.get("mentioned") and _series_id(c["episode"]):
            taught.setdefault((_series_id(c["episode"]), c["term"].lower()), c)
    for c in chunks:
        if c["kind"] == "glossary" and not c.get("mentioned"):
            t = taught.get((_series_id(c["episode"]), c["term"].lower()))
            if t and t["slug"] != c["slug"]:
                c.update(slug=t["slug"], episode=t["episode"], ms=t["ms"], chapter=t["chapter"], chapterIndex=t["chapterIndex"],
                         mentioned=True, text=f"{c['text']} (taught in {t['slug']})")


def learn_chunks(folder: Path, ep: dict) -> list[dict]:
    """Self-test and card chunks from library/learn/<slug>/ (written by learn.py).
    One chunk per item: the question line, with the answer line as an alias line."""
    out = []
    for name, kind in (("selftest.md", "self-test"), ("cards.md", "card")):
        path = folder / name
        if not path.exists():
            continue
        f = str(path.resolve())
        lines = path.read_text(encoding="utf-8").split("\n")
        items: dict[int, dict] = {}
        section = ""
        for n, line in enumerate(lines, start=1):
            if line.startswith("## "):
                section = line[3:].strip().lower()
                continue
            if kind == "self-test":
                q = SELFTEST_Q_RE.match(line) if section == "questions" else None
                a = SELFTEST_A_RE.match(line) if section == "answer key" else None
                if q:
                    items[int(q.group(1))] = {"q": q.group(3), "level": q.group(2), "line": n}
                elif a and int(a.group(1)) in items:
                    it = items[int(a.group(1))]
                    it.update(a=a.group(2), ms=(int(a.group(3)) * 60 + int(a.group(4))) * 1000, alias=n)
            else:
                q = CARD_Q_RE.match(line)
                a = CARD_A_RE.match(line)
                if q:
                    items[int(q.group(1))] = {"q": q.group(2), "line": n}
                    last = int(q.group(1))
                elif a and items:
                    it = items[last]
                    it.update(a=a.group(1), ms=(int(a.group(2)) * 60 + int(a.group(3))) * 1000, alias=n)
        for num, it in sorted(items.items()):
            if "a" not in it:
                continue
            ch_title, ch_idx = chapter_at(ep, it["ms"])
            label = f"Self-test Q{num}" if kind == "self-test" else f"Card {num}"
            out.append({"slug": ep["slug"], "episode": ep, "file": f, "line": it["line"], "aliasLines": [it["alias"]],
                        "kind": kind, "chapter": ch_title, "chapterIndex": ch_idx, "ms": it["ms"], "speaker": "",
                        "text": f"{label}: {it['q']} Answer: {it['a']}"})
    return out


def chapter_at(ep: dict, ms: int) -> tuple[str, int]:
    """Chapter that holds a [mm:ss] time (whole seconds, as printed)."""
    title, idx = "", 0
    for ch in ep["chapters"]:
        if (ch.get("startMs", 0) // 1000) * 1000 <= ms:
            title, idx = ch.get("title", ""), ch.get("index", 0)
    return title, idx


# ---------------------------------------------------------------- scoring

def stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower().replace("'", "")) if w not in STOP]


def bm25(query: str, chunks: list[dict], k1: float = 1.2, b: float = 0.75) -> list[tuple[float, dict]]:
    q = tokens(query)
    if not q or not chunks:
        return []
    docs = [tokens(c["text"]) for c in chunks]
    avg = sum(len(d) for d in docs) / len(docs) or 1
    df = Counter()
    for d in docs:
        df.update(set(d))
    n = len(docs)
    results = []
    for c, d in zip(chunks, docs):
        tf = Counter(d)
        score = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(d) / avg))
        if score <= 0:
            continue
        ep = c["episode"]
        qset = set(q)
        score += 0.5 * len(qset & set(tokens(ep["title"])))
        score += 1.0 * len(qset & {stem(t) for tag in ep["tags"] for t in re.findall(r"[a-z0-9]+", tag)})
        if c["kind"] == "glossary":  # W16 (D18): a turn that teaches the term ranks above its glossary line
            score *= 0.9 if c.get("mentioned") else 0.3
        elif any(qset & set(tokens(g)) for g in ep["glossary"]):
            score += 0.3
        results.append((score, c))
    # W16 (D18): a glossary line never outranks a matching turn of the episode it links to.
    best_turn: dict[str, float] = {}
    for score, c in results:
        if c["kind"] == "turn":
            best_turn[c["slug"]] = max(best_turn.get(c["slug"], 0.0), score)
    results = [(min(score, best_turn[c["slug"]] * 0.99) if c["kind"] == "glossary" and c["slug"] in best_turn else score, c)
               for score, c in results]
    results.sort(key=lambda r: (-r[0], r[1]["slug"], r[1]["ms"]))
    return results


def rg_phrase(query: str, lib: Path, chunks: list[dict]) -> list[tuple[float, dict]]:
    rg = shutil.which("rg")
    if not rg or not query.strip():
        return []
    res = subprocess.run([rg, "-n", "-i", "-F", "--no-heading", "--with-filename", "--glob", "*.md",
                          "--", query, str(lib)], capture_output=True, text=True)
    if res.returncode not in (0, 1):
        raise Fail(f"ripgrep failed: {res.stderr.strip()}")
    by_line = {}
    for c in chunks:
        for ln in [c["line"], *c.get("aliasLines", [])]:
            by_line[(c["file"], ln)] = c
    hits = []
    for row in res.stdout.splitlines():
        m = re.match(r"^(.*?):(\d+):", row)
        if not m:
            continue
        c = by_line.get((str(Path(m.group(1)).resolve()), int(m.group(2))))
        if c:
            # W16 (D18): transcript turns first, then glossary lines with a first mention, then the rest
            score = 100.0 + {"turn": 5}.get(c["kind"], 0) - (50 if c["kind"] == "glossary" and not c.get("mentioned") else 0) \
                + c["text"].lower().count(query.lower())
            hits.append((score, c))
    hits.sort(key=lambda r: (-r[0], r[1]["slug"], r[1]["ms"]))
    return hits


def tag_hits(query: str, episodes: list[dict], chunks: list[dict]) -> list[tuple[float, dict]]:
    """An exact tag match returns the episode's first chunk, at [00:00]."""
    q = query.strip().lower()
    out = []
    for ep in episodes:
        if q and q in ep["tags"]:
            first = next((c for c in chunks if c["slug"] == ep["slug"] and c["kind"] in ("goal", "turn")), None)
            if first:
                out.append((50.0, {**first, "kind": "tag", "ms": 0, "speaker": "", "text": f"tag: {q}. {first['text']}"}))
    return out


# ---------------------------------------------------------------- output

def mmss(ms: int) -> str:
    s = int(ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def deep_link(ep: dict, ms: int) -> str | None:
    if not ep.get("mp4"):
        return None
    return f"{Path(ep['mp4']).as_uri()}#t={int(ms) // 1000}"


def snippet(text: str, query: str, color: bool, width: int = 180) -> str:
    phrase = re.escape(query.strip())
    terms = [re.escape(w) for w in re.findall(r"[A-Za-z0-9]+", query) if w.lower() not in STOP]
    pats = [phrase] + [rf"\b{t}\w*" for t in terms] + [rf"\b{re.escape(stem(t.lower()))}\w*" for t in terms]
    pats = [p for p in pats if p]
    rx = re.compile("|".join(f"(?:{p})" for p in pats), re.I) if pats else None
    m = rx.search(text) if rx else None
    start = 0
    if m and len(text) > width:
        start = max(0, min(m.start() - width // 3, len(text) - width))
    cut = text[start:start + width]
    cut = ("..." if start else "") + cut + ("..." if start + width < len(text) else "")
    if not rx:
        return cut
    on, off = (BOLD, RESET) if color else ("**", "**")
    return rx.sub(lambda mm: f"{on}{mm.group(0)}{off}", cut)


def hit_record(rank: int, score: float, c: dict, engine: str) -> dict:
    ep = c["episode"]
    return {
        "rank": rank, "score": round(score, 3), "engine": engine, "kind": c["kind"],
        "slug": c["slug"], "title": ep["title"], "chapter": c["chapter"], "chapterIndex": c["chapterIndex"],
        "ms": c["ms"], "seconds": c["ms"] // 1000, "at": mmss(c["ms"]), "speaker": c["speaker"],
        "text": c["text"], "link": deep_link(ep, c["ms"]), "transcript": f"{c['file']}:{c['line']}",
        "cite": f"[{c['slug']} {mmss(c['ms'])}]",
    }


# ---------------------------------------------------------------- open

def player_command(mp4: str, seconds: int) -> tuple[list[str], str]:
    """Pick a player that can start at a time. Returns (argv, note)."""
    if shutil.which("mpv"):
        return ["mpv", f"--start={seconds}", mp4], "mpv"
    iina = "/Applications/IINA.app/Contents/MacOS/iina-cli"
    if os.path.exists(iina):
        return [iina, mp4, f"--mpv-start={seconds}"], "IINA"
    vlc = "/Applications/VLC.app/Contents/MacOS/VLC"
    if os.path.exists(vlc):
        return [vlc, f"--start-time={seconds}", mp4], "VLC"
    url = f"{Path(mp4).as_uri()}#t={seconds}"
    for app in ("Google Chrome", "Safari"):
        if os.path.exists(f"/Applications/{app}.app"):
            return ["open", "-a", app, url], f"{app} (media fragment #t)"
    return ["open", mp4], "default app (QuickTime ignores the time: seek by hand)"


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--library", default=os.environ.get("EXPLAINERS_LIBRARY", "explainers/library"))
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json", action="store_true", help="print hits as JSON")
    ap.add_argument("--slug", help="only this episode")
    ap.add_argument("--tag", help="only episodes with this tag")
    ap.add_argument("--engine", choices=["auto", "rg", "bm25"], default="auto")
    ap.add_argument("--list", action="store_true", help="list episodes instead of searching")
    ap.add_argument("--open", action="store_true", help="open hit N in a player at its time (macOS)")
    ap.add_argument("--hit", type=int, default=1, help="which hit --open uses (default 1)")
    ap.add_argument("--dry-run", action="store_true", help="with --open: print the player command only")
    args = ap.parse_args(argv)

    try:
        if args.slug and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", args.slug):
            raise Fail(f"invalid --slug {args.slug!r}: use lowercase letters, digits and single hyphens")
        lib = Path(args.library).expanduser().resolve()
        episodes, chunks = load_library(lib)
        if args.slug:
            episodes = [e for e in episodes if e["slug"] == args.slug]
            if not episodes:
                raise Fail(f"no episode with slug '{args.slug}' in {lib}")
        if args.tag:
            episodes = [e for e in episodes if args.tag.lower() in e["tags"]]
        keep = {e["slug"] for e in episodes}
        chunks = [c for c in chunks if c["slug"] in keep]

        if args.list or not args.query.strip():
            rows = [{k: e[k] for k in ("slug", "title", "durationSec", "depth", "date", "tags", "series", "mp4", "file")}
                    | {"chapters": [{"at": c.get("at"), "title": c.get("title")} for c in e["chapters"]]}
                    for e in episodes]
            if args.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
            else:
                print(f"{len(rows)} episode(s) in {lib}")
                for r in rows:
                    series = f" series {r['series']['id']} part {r['series'].get('part')}" if r["series"] else ""
                    print(f"- {r['slug']}: {r['title']} [{mmss(r['durationSec'] * 1000)}] depth {r['depth']}{series}"
                          f" tags {', '.join(r['tags']) or '-'} video {'yes' if r['mp4'] else 'no'}")
                    for c in r["chapters"]:
                        print(f"    [{c['at']}] {c['title']}")
            return 0 if rows else 2

        engine = args.engine
        if engine == "rg" and not shutil.which("rg"):
            raise Fail("--engine rg needs ripgrep on PATH; use --engine bm25")
        ranked: list[tuple[float, dict, str]] = []
        seen = set()

        def add(results, name):
            for score, c in results:
                key = (c["file"], c["line"])
                if key not in seen:
                    seen.add(key)
                    ranked.append((score, c, name))

        add(tag_hits(args.query, episodes, chunks), "tag")
        if engine in ("auto", "rg"):
            add(rg_phrase(args.query, lib, chunks), "rg")
        if engine in ("auto", "bm25"):
            add(bm25(args.query, chunks), "bm25")
        ranked = ranked[: max(1, args.limit)]
        hits = [hit_record(i, s, c, name) for i, (s, c, name) in enumerate(ranked, start=1)]

        if args.json and not args.open:
            print(json.dumps(hits, indent=2, ensure_ascii=False))
        elif not args.open:
            used = "rg phrase + bm25" if engine == "auto" and shutil.which("rg") else ("bm25" if engine == "auto" else engine)
            print(f"{len(hits)} hit(s) for \"{args.query}\" in {lib} (engine: {used})")
            color = sys.stdout.isatty()
            for h, (_, c, _) in zip(hits, ranked):
                print()
                print(f"{h['rank']}. {h['title']} [{h['slug']}]")
                who = f"  {h['speaker']}" if h["speaker"] else f"  ({h['kind']})"
                print(f"   Chapter {h['chapterIndex'] or '-'}: {h['chapter']}  [{h['at']}]{who}")
                print(f"   {snippet(c['text'], args.query, color)}")
                print(f"   {h['link'] or 'video: not rendered yet'}")
                print(f"   cite {h['cite']}  transcript {h['transcript']}")
        if not hits:
            return 2
        if args.open:
            if not 1 <= args.hit <= len(hits):
                raise Fail(f"--hit {args.hit} is out of range (1 to {len(hits)})")
            h = hits[args.hit - 1]
            ep = ranked[args.hit - 1][1]["episode"]
            if not ep.get("mp4") or not Path(ep["mp4"]).exists():
                raise Fail(f"episode {h['slug']} has no mp4 on disk; render it, then rerun transcript.py --mp4")
            cmd, note = player_command(ep["mp4"], h["seconds"])
            print(f"open {h['cite']} {h['title']}, chapter {h['chapterIndex']}, with {note}")
            print("  " + " ".join(cmd))
            if not args.dry_run:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return 0
    except Fail as exc:
        print(f"search.py: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
