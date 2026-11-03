#!/usr/bin/env python3
"""Copy the COMPLETE delivery of one episode into a portable folder (examples, archives, sharing).

Reads   <workspace>/<slug>/            mp4, sidecars, transcript, captions, chapters, delivery.json,
                                       learn/, learn.json, brief/facts/outline/script/scenes/timing/
                                       episode json, audio/episode.wav, qc/ (whole tree)
        <workspace>/library/<slug>.md, library/learn/<slug>/, library/index.json (this slug's record)
Writes  <DIR>/                         the same files, laid out as the episode folder:
          out/episode.mp4 out/episode.srt out/episode.vtt out/transcript.md
          transcript.md transcript.json captions.vtt captions.srt chapters.ffmetadata delivery.json
          learn.json brief.json facts.json outline.json script.json scenes.json timing.json episode.json
          audio/episode.wav  learn/  qc/
          library/<slug>.md  library/learn/<slug>/  library/index.json (ONE record: this slug)
        <DIR>/export.json              slug, source workspace, exportedAt, per file sha256 and the
                                       source sha256, rewritten flag, missing, brokenLinks, external

Links: every absolute path or file:// URL that points into the workspace is rewritten to a path
relative to the file that holds it (.md files) or to DIR (json, csv, srt, vtt and other text).
Paths into the workspace that are not part of this episode (remotion/, other slugs) stay absolute
and are listed in export.json `external`. Turn clips and audio/cache are never copied.

Checks after the copy: every unchanged copy matches its source sha256; every rewritten file's
sha256 is recorded; the source files named in delivery.json still match its digests; every relative
markdown link or image in an exported .md file, and every rewritten path whose source exists, resolves
inside DIR (a rewritten plain-text path that never existed, such as contact-sheet-NN.png, is listed in
`unresolvedMentions`, not as a broken link).
A broken link exits 1 unless --allow-broken-links (they are still recorded in export.json).

Usage:
  export_delivery.py --slug consistent-hashing --to ../examples/consistent-hashing-v6 [--workspace explainers]
                     [--force] [--allow-broken-links] [--json]
  export_delivery.py --series explainers/<series-id>/series.json --to ../examples/<series-id> [...]

Series mode (W16, W14b D19): every part listed in series.json is exported as above into
<DIR>/<part-slug>/, the series folder (series.json, glossary.json, facts.json, research/, gate notes)
is copied to <DIR>/series/ and checked against its source sha256, and <DIR>/index.md lists the parts
with relative links to each video, transcript and self-test (every link is checked).
<DIR>/export.json records the series, each part's result and the series files' digests.

DIR must be empty or absent. With --force, the files a previous export listed in DIR/export.json
are removed first; any other file in DIR (a README.md) is kept, and a kept file that the export
would overwrite is an error. Exit code 0 on success, 1 on any error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402

EXPORT_FILE = "export.json"
EPISODE_FILES = ["transcript.md", "transcript.json", "captions.vtt", "captions.srt", "chapters.ffmetadata",
                 "delivery.json", "learn.json", "brief.json", "facts.json", "outline.json", "script.json",
                 "scenes.json", "timing.json", "episode.json", "fidelity-accept.json", "glossary.json",
                 "audio/episode.wav", "out/episode.mp4", "out/episode.srt", "out/episode.vtt", "out/transcript.md"]
REQUIRED = ["out/episode.mp4", "transcript.md", "delivery.json", "learn/"]
OPTIONAL_REPORTED = ["qc/scores.json", "qc/listen.json"]
TREES = ["learn", "qc"]
TEXT_SUFFIXES = {".md", ".json", ".csv", ".txt", ".srt", ".vtt", ".ffmetadata", ".html", ".tsv"}
MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "data:", "#")


class Fail(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- plan


def walk_tree(base: Path, root: Path) -> list[Path]:
    """Regular files under root (no symbolic links followed or copied), sorted."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        d = Path(dirpath)
        for name in list(dirnames):
            if (d / name).is_symlink():
                raise Fail(f"{d / name} is a symbolic link; refusing to export through it")
        for name in filenames:
            p = d / name
            if p.is_symlink():
                raise Fail(f"{p} is a symbolic link; refusing to export it")
            if name.startswith(".") and name.endswith(".tmp"):
                continue  # a half-written atomic_write temp
            pc.safe_path(base, p, "source file")
            out.append(p)
    return sorted(out)


def build_plan(ws: Path, slug: str) -> tuple[dict[str, Path], list[str], list[str]]:
    """dest relpath -> source path; missing required; missing optional."""
    ep = pc.episode_dir(ws, slug)
    plan: dict[str, Path] = {}
    missing_req, missing_opt = [], []
    for rel in EPISODE_FILES:
        src = pc.safe_path(ep, ep / rel, "source file")
        if src.is_file():
            plan[rel] = src
        elif rel in REQUIRED:
            missing_req.append(rel)
    for tree in TREES:
        root = ep / tree
        if root.is_dir() and not root.is_symlink():
            for p in walk_tree(ep, root):
                plan[p.relative_to(ep).as_posix()] = p
        elif tree + "/" in REQUIRED:
            missing_req.append(tree + "/")
    if "learn/" not in missing_req and not any(k.startswith("learn/") for k in plan):
        missing_req.append("learn/")
    lib = ws / "library"
    lib_md = lib / f"{slug}.md"
    if lib_md.is_file():
        plan[f"library/{slug}.md"] = pc.safe_path(ws, lib_md, "library file")
    else:
        missing_opt.append(f"library/{slug}.md")
    lib_learn = lib / "learn" / slug
    if lib_learn.is_dir() and not lib_learn.is_symlink():
        for p in walk_tree(ws, lib_learn):
            plan[f"library/learn/{slug}/{p.relative_to(lib_learn).as_posix()}"] = p
    else:
        missing_opt.append(f"library/learn/{slug}/")
    for rel in OPTIONAL_REPORTED:
        if rel not in plan:
            missing_opt.append(rel)
    return plan, missing_req, missing_opt


def index_record(ws: Path, slug: str) -> dict | None:
    p = ws / "library" / "index.json"
    if not p.is_file():
        return None
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise Fail(f"{p}: invalid JSON at line {e.lineno}: {e.msg}")
    recs = [r for r in idx.get("episodes", []) if isinstance(r, dict) and r.get("slug") == slug]
    if not recs:
        return None
    return {"version": idx.get("version", 1), "episodes": [recs[0]]}


# ---------------------------------------------------------------- link rewriting


class Rewriter:
    """Rewrites absolute workspace paths and file:// URLs in text to relative paths."""

    def __init__(self, ws: Path, slug: str, out: Path, planned: set[str]):
        self.slug = slug
        self.out = out
        self.planned = planned
        roots = {str(ws.resolve()), os.path.abspath(ws)}
        alts = set()
        for r in roots:
            alts.add(re.escape("file://" + quote(r)))
            alts.add(re.escape("file://" + r))
            alts.add(re.escape(r))
        alt = "|".join(sorted(alts, key=len, reverse=True))
        self.re = re.compile(rf"(?:{alt})(?:(/[^\s\"'<>()\[\]#?,;`|]*))?(?=[\s\"'<>()\[\]#?,;`|]|$)")
        self.external: list[str] = []
        self.targets: list[tuple[str, str]] = []  # (holder relpath, rewritten target) whose source exists
        self.mentions: list[tuple[str, str]] = []  # rewritten paths whose source never existed (e.g. a NN pattern)
        self.ws = ws

    def dest_of(self, rel_ws: str) -> str | None:
        """Export relpath for a path relative to the workspace, or None (not part of this export)."""
        parts = [p for p in rel_ws.split("/") if p]
        if not parts:
            return None
        if parts[0] == self.slug:
            return "/".join(parts[1:]) or "."
        if parts[0] == "library":
            rest = "/".join(parts)
            if rest == f"library/{self.slug}.md" or rest == "library/index.json" or rest.startswith(f"library/learn/{self.slug}"):
                return rest
        return None

    def rewrite(self, text: str, holder: str) -> str:
        base = (self.out / holder).parent if holder.endswith(".md") else self.out

        def sub(m: re.Match) -> str:
            raw = m.group(0)
            tail = unquote(m.group(1) or "")
            dest = self.dest_of(tail)
            if dest is None:
                self.external.append(f"{holder}: {raw}")
                return raw
            target = self.out if dest == "." else self.out / dest
            rel = os.path.relpath(target, base).replace(os.sep, "/")
            if " " in rel and holder.endswith(".md"):
                rel = quote(rel)
            src = self.ws.resolve() / tail.lstrip("/")
            (self.targets if src.exists() else self.mentions).append((holder, rel))
            return rel

        return self.re.sub(sub, text)


# ---------------------------------------------------------------- copy and verify


def write_bytes(out: Path, rel: str, data: bytes) -> Path:
    return pc.atomic_write(out / rel, data, base=out)


def copy_file(out: Path, rel: str, src: Path) -> Path:
    dest = pc.safe_path(out, out / rel, "output file")
    dest.parent.mkdir(parents=True, exist_ok=True)
    pc.safe_path(out, dest.parent, "output folder")
    if dest.is_symlink():
        raise Fail(f"{dest} is a symbolic link; refusing to replace it")
    tmp = pc.exclusive_temp(dest.parent, dest.name)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def prepare_out(out: Path, force: bool, planned: set[str]) -> None:
    if out.is_symlink():
        raise Fail(f"{out} is a symbolic link; refusing to export into it")
    if not out.exists():
        out.mkdir(parents=True)
        return
    if not out.is_dir():
        raise Fail(f"{out} exists and is not a folder")
    entries = [p for p in out.rglob("*") if p.is_file() or p.is_symlink()]
    if not entries:
        return
    if not force:
        raise Fail(f"{out} is not empty ({len(entries)} files); pass --force to replace a previous export "
                   f"(only files listed in its {EXPORT_FILE} are removed)")
    prev = out / EXPORT_FILE
    listed: list[str] = []
    if prev.is_file():
        try:
            listed = list((json.loads(prev.read_text(encoding="utf-8")).get("files") or {}).keys())
        except (json.JSONDecodeError, AttributeError):
            raise Fail(f"{prev} is not valid JSON; remove the folder's contents by hand")
    for rel in listed + [EXPORT_FILE]:
        p = pc.safe_path(out, out / rel, "previous export file")
        if p.is_file():
            p.unlink()
    for d in sorted((p for p in out.rglob("*") if p.is_dir() and not p.is_symlink()), key=lambda p: -len(p.parts)):
        try:
            d.rmdir()
        except OSError:
            pass
    clash = sorted(rel for rel in planned if (out / rel).exists())
    if clash:
        raise Fail(f"{out} holds files that this export would overwrite but no previous {EXPORT_FILE} lists them: "
                   f"{clash[:5]}; move them away first")


def md_links(text: str) -> list[str]:
    return [m.group(1) for m in MD_LINK_RE.finditer(text)]


def link_ok(out: Path, holder: str, target: str) -> bool:
    t = target.split("#", 1)[0].split("?", 1)[0]
    if not t:
        return True
    base = (out / holder).parent if holder.endswith(".md") else out
    p = Path(os.path.normpath(base / unquote(t)))
    try:
        p.relative_to(out)
    except ValueError:
        return False
    return p.exists()


def export(ws: Path, slug: str, out: Path, force: bool = False, allow_broken: bool = False) -> dict:
    pc.check_id(slug, "slug")
    ws = Path(ws).expanduser()
    if not ws.is_dir():
        raise Fail(f"workspace {ws} does not exist")
    ws = ws.resolve()
    out = Path(out).expanduser().resolve()
    try:
        out.relative_to(ws)
        raise Fail(f"{out} is inside the workspace {ws}; export to a folder outside it")
    except ValueError:
        pass
    plan, missing_req, missing_opt = build_plan(ws, slug)
    if missing_req:
        raise Fail(f"{slug}: required delivery files missing: {', '.join(missing_req)}; finish steps 11 to 14 first")
    idx = index_record(ws, slug)
    planned = set(plan) | ({"library/index.json"} if idx else set())
    if idx is None:
        missing_opt.append("library/index.json record")
    prepare_out(out, force, planned)

    # delivery.json: the source files it names must still match (the delivery is the delivered one).
    delivery_problems = []
    try:
        dj = json.loads(plan["delivery.json"].read_text(encoding="utf-8"))
        for name, rec in (dj.get("files") or {}).items():
            src = ws / rec.get("path", "")
            if not src.is_file():
                delivery_problems.append(f"{name}: {rec.get('path')} is missing")
            elif sha256(src) != rec.get("sha256"):
                delivery_problems.append(f"{name}: {rec.get('path')} differs from delivery.json")
    except (json.JSONDecodeError, AttributeError) as e:
        delivery_problems.append(f"delivery.json is not valid: {e}")

    rw = Rewriter(ws, slug, out, planned)
    files: dict[str, dict] = {}
    for rel in sorted(plan):
        src = plan[rel]
        src_sha = sha256(src)
        if src.suffix.lower() in TEXT_SUFFIXES:
            raw = src.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                new = rw.rewrite(text, rel)
                if new != text:
                    data = new.encode("utf-8")
                    write_bytes(out, rel, data)
                    files[rel] = {"sha256": bytes_sha256(data), "sourceSha256": src_sha, "rewritten": True}
                    continue
        copy_file(out, rel, src)
        files[rel] = {"sha256": src_sha, "sourceSha256": src_sha, "rewritten": False}
    if idx is not None:
        text = json.dumps(idx, indent=2, ensure_ascii=False) + "\n"
        new = rw.rewrite(text, "library/index.json")
        data = new.encode("utf-8")
        write_bytes(out, "library/index.json", data)
        src_idx = ws / "library" / "index.json"
        files["library/index.json"] = {"sha256": bytes_sha256(data), "sourceSha256": sha256(src_idx),
                                       "rewritten": True, "note": f"one record ({slug}) of the workspace index"}

    # verify
    digest_problems = []
    for rel, rec in files.items():
        p = out / rel
        if not p.is_file():
            digest_problems.append(f"{rel}: not written")
        elif sha256(p) != rec["sha256"]:
            digest_problems.append(f"{rel}: written file differs from its recorded sha256")
        elif not rec["rewritten"] and rec["sha256"] != rec["sourceSha256"]:
            digest_problems.append(f"{rel}: copy differs from its source")
    broken = []
    seen = set()
    checks = list(rw.targets)
    for rel in files:
        if rel.endswith(".md"):
            for target in md_links((out / rel).read_text(encoding="utf-8")):
                if target.startswith(SKIP_SCHEMES):
                    continue
                if target.startswith("file://") or target.startswith("/"):
                    if not any(target in e for e in rw.external):
                        rw.external.append(f"{rel}: {target}")
                    continue
                checks.append((rel, target))
    for holder, target in checks:
        if (holder, target) in seen:
            continue
        seen.add((holder, target))
        if not link_ok(out, holder, target):
            broken.append(f"{holder}: {target}")

    mentions = sorted({f"{h}: {t}" for h, t in rw.mentions if not link_ok(out, h, t)} - set(broken))
    record = {"version": 1, "slug": slug, "sourceWorkspace": str(ws),
              "exportedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
              "files": dict(sorted(files.items())), "missing": missing_opt, "brokenLinks": broken, "unresolvedMentions": mentions,
              "external": sorted(set(rw.external)), "deliveryProblems": delivery_problems,
              "digestProblems": digest_problems}
    pc.atomic_write(out / EXPORT_FILE, json.dumps(record, indent=2, ensure_ascii=False) + "\n", base=out)
    record["ok"] = not digest_problems and not delivery_problems and (allow_broken or not broken)
    return record


def export_series(ws: Path, series: Path, out: Path, force: bool = False, allow_broken: bool = False) -> dict:
    """Export every part of a series plus the series folder and an index with relative links."""
    ws = Path(ws).expanduser().resolve()
    sp = Path(series).expanduser()
    sp = (sp / "series.json" if sp.is_dir() else sp).resolve()
    if not sp.is_file():
        raise Fail(f"series file {sp} not found")
    pc.safe_path(ws, sp, "series file")
    try:
        sj = json.loads(sp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise Fail(f"{sp}: invalid JSON at line {e.lineno}: {e.msg}")
    sid = pc.check_id(str(sj.get("id", "")), "slug")  # a series id follows the slug rule
    if sp.parent != ws / sid:
        raise Fail(f"{sp} must sit in {ws / sid}/ (the series folder named by its id)")
    parts = sorted((p for p in sj.get("parts") or [] if isinstance(p, dict)), key=lambda p: p.get("part", 0))
    if not parts:
        raise Fail(f"{sp} lists no parts")
    out = Path(out).expanduser().resolve()
    if out == ws or ws in out.parents:
        raise Fail(f"{out} is inside the workspace {ws}; export to a folder outside it")
    prev = out / EXPORT_FILE
    if out.exists() and any(out.iterdir()):
        if not force:
            raise Fail(f"{out} is not empty; pass --force to replace a previous series export")
        try:
            old = json.loads(prev.read_text(encoding="utf-8")) if prev.is_file() else {}
        except json.JSONDecodeError:
            raise Fail(f"{prev} is not valid JSON; remove the folder's contents by hand")
        for rel in list((old.get("seriesFiles") or {}).keys()) + ["index.md"]:
            q = pc.safe_path(out, out / rel, "previous export file")
            if q.is_file():
                q.unlink()
    out.mkdir(parents=True, exist_ok=True)
    results, ok = {}, True
    for p in parts:
        slug = pc.check_id(str(p.get("slug", "")), "slug")
        rec = export(ws, slug, out / slug, force, allow_broken)
        results[slug] = {"part": p.get("part"), "ok": rec["ok"], "files": len(rec["files"]), "brokenLinks": rec["brokenLinks"],
                         "deliveryProblems": rec["deliveryProblems"], "digestProblems": rec["digestProblems"]}
        ok = ok and rec["ok"]
    sfiles, problems = {}, []
    for src in walk_tree(ws, ws / sid):
        rel = "series/" + src.relative_to(ws / sid).as_posix()
        copy_file(out, rel, src)
        s_src, s_out = sha256(src), sha256(out / rel)
        sfiles[rel] = {"sha256": s_out, "sourceSha256": s_src}
        if s_src != s_out:
            problems.append(f"{rel}: copy differs from its source")
    lines = [f"# {sj.get('title', sid)}", "", f"Series `{sid}`, {len(parts)} parts." + (f" Objective: {sj['learningObjective']}" if sj.get("learningObjective") else ""), ""]
    for p in parts:
        slug = p["slug"]
        lines += [f"## Part {p.get('part')}: {p.get('title', slug)}", "",
                  f"- [Video]({slug}/out/episode.mp4)", f"- [Transcript]({slug}/transcript.md)", f"- [Self-test]({slug}/learn/selftest.md)", ""]
    lines += ["Series notes: [series.json](series/series.json)" + (", [glossary](series/glossary.json)" if (ws / sid / "glossary.json").is_file() else ""), ""]
    text = "\n".join(lines)
    pc.atomic_write(out / "index.md", text, base=out)
    broken = [t for t in md_links(text) if not link_ok(out, "index.md", t)]
    record = {"version": 1, "series": sid, "sourceWorkspace": str(ws),
              "exportedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
              "parts": results, "seriesFiles": dict(sorted(sfiles.items())), "index": {"sha256": sha256(out / "index.md"), "brokenLinks": broken},
              "digestProblems": problems}
    pc.atomic_write(prev, json.dumps(record, indent=2, ensure_ascii=False) + "\n", base=out)
    record["ok"] = ok and not problems and (allow_broken or not broken)
    return record


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Copy one episode's (or a series') complete delivery into a portable folder.")
    ap.add_argument("--workspace", type=Path, default=Path("explainers"), help="the explainers/ folder (default ./explainers)")
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--slug")
    who.add_argument("--series", type=Path, help="a series.json (or its folder): export every part, the series folder and an index")
    ap.add_argument("--to", type=Path, required=True, help="destination folder (empty, absent, or a previous export with --force)")
    ap.add_argument("--force", action="store_true", help="replace the files a previous export listed in DIR/export.json")
    ap.add_argument("--allow-broken-links", action="store_true", help="exit 0 even when a link does not resolve (still recorded)")
    ap.add_argument("--json", action="store_true", help="print export.json instead of a summary")
    args = ap.parse_args(argv)
    try:
        if args.series:
            rec = export_series(args.workspace, args.series, args.to, args.force, args.allow_broken_links)
        else:
            rec = export(args.workspace, args.slug, args.to, args.force, args.allow_broken_links)
    except (Fail, pc.BadId, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if args.series and not args.json:
        for slug, r in rec["parts"].items():
            print(f"part {r['part']} {slug}: {r['files']} files, {'PASS' if r['ok'] else 'FAIL'}"
                  + "".join(f"\n  ERROR: {x}" for x in r["deliveryProblems"] + r["digestProblems"] + r["brokenLinks"]))
        print(f"series folder: {len(rec['seriesFiles'])} files; index.md links: {'ok' if not rec['index']['brokenLinks'] else rec['index']['brokenLinks']}")
        for x in rec["digestProblems"]:
            print(f"ERROR: {x}")
        print("RESULT: " + ("PASS" if rec["ok"] else "FAIL"))
        return 0 if rec["ok"] else 1
    if args.json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
    else:
        n_rw = sum(1 for r in rec["files"].values() if r["rewritten"])
        print(f"exported {len(rec['files'])} files ({n_rw} with rewritten links) to {Path(args.to).resolve()}")
        for m in rec["missing"]:
            print(f"MISSING (optional): {m}")
        for e in rec["external"]:
            print(f"EXTERNAL (left absolute): {e}")
        for m in rec["unresolvedMentions"]:
            print(f"NOTE (plain-text path that never existed, not a link): {m}")
        for b in rec["brokenLinks"]:
            print(f"BROKEN LINK: {b}")
        for p in rec["deliveryProblems"] + rec["digestProblems"]:
            print(f"ERROR: {p}")
        print("RESULT: " + ("PASS" if rec["ok"] else "FAIL"))
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
