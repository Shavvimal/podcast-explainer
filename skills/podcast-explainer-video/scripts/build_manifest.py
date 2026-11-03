#!/usr/bin/env python3
"""build_manifest.py: script.json + scenes.json + timing.json -> episode.json, synced into Remotion.

usage:
  python3 build_manifest.py --workspace explainers --slug hash-maps
        [--remotion-dir explainers/remotion] [--placeholder-timing] [--auto-chips] [--tail-ms 1000] [--no-sync]

What it does:
  1. Loads <workspace>/<slug>/{script,scenes,timing}.json and checks each against schemas/.
  2. Resolves every anchor to integer ms: scene and overlay anchor.from/to, and inside props every
     key "at" or ending in "At" ({turn, word?, occurrence?, edge?, offsetMs?} or {ms}) gains a
     sibling "<key>Ms" (at -> atMs, answerAt -> answerAtMs). World nodes and edges get revealAtMs.
  3. Lays scenes on one main track: sorted by start, no overlap (error), gaps closed by holding the
     previous scene (warning past 2 s), the first scene starts at 0, the last runs to the end.
  4. Warns when a turn's onScreen term has no visual event near that turn (--auto-chips adds chips).
  5. Clamps video.tailMs to 500..3000, checks episode.wav's real duration, validates episode.json
     against schemas/episode.schema.json, writes <workspace>/<slug>/episode.json and copies
     episode.json, audio/episode.wav, diagrams/, img/ and icons/ into <remotion>/public/episodes/<slug>/.

--placeholder-timing: no audio yet (gate 2 hero stills). Turn times come from word counts at
2.6 words/s; words are marked "estimated"; audio.src is null.

Schema checks use the `jsonschema` package when it is importable, else a built-in checker for the
keyword subset the schemas use. Nothing is downloaded or re-executed (works offline).

Scene entrances (A09): a scene that fades in starts up to 233 ms (ENTER_MS, the template's
7-frame entrance, motionConstants.ts ENTRANCE_MS, read from the Remotion project) before its anchor
when the audio is silent there. When the silence is shorter, the entrance is shortened to fit it:
episode.json scene `enterMs`, which the template uses instead of ENTRANCE_FRAMES; below 100 ms the
scene cuts in (enterMs 0). The first scene gets enterMs too (it cannot start before 0). The check
is on rendered FRAMES, the same maths as Episode.tsx (from = msToFrame(startMs), round(enterMs *
fps / 1000) frames; the fade ends at (from + frames) * 1000 / fps), so frame rounding cannot push
a fade past the next word. A scene anchored on a word inside a spoken turn cuts in (enterMs 0).
So speech never overlaps an entrance, without exceptions.
Holds come from timing.json holdStartMs/holdEndMs (tts.py), else from the turn end.
All checks run before anything is written; outputs are written atomically.

Exit 0 on success (warnings allowed), 1 on any error (all errors are listed), 2 on bad usage.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402

SKILL = Path(__file__).resolve().parent.parent
SCHEMAS = SKILL / "schemas"
TAG_RE = re.compile(r"<([a-z][a-z \-]*)>")  # same as tts.py
PIPE_RE = re.compile(r"\|[^|]*\|")
FPS, WIDTH, HEIGHT = 30, 1920, 1080
TAIL_MIN, TAIL_MAX, TAIL_DEFAULT = 500, 3000, 1000
GAP_WARN_MS = 2000
PLACEHOLDER_WPS, PLACEHOLDER_GAP = 2.6, 250
# A09: the full entrance fade. The one source of truth is the renderer's motionConstants.ts
# ENTRANCE_MS (ENTRANCE_FRAMES 7 at 30 fps = 233 ms). build() re-reads it from the Remotion project
# it syncs to; the skill template is read at import; 233 is the fallback when neither is readable.
ENTRANCE_MS_FALLBACK = 233
_ENTRANCE_RE = re.compile(r"export\s+const\s+ENTRANCE_MS\s*=\s*(\d+)")


def read_entrance_ms(remotion: Path | None = None) -> int:
    """ENTRANCE_MS from <remotion>/src/motionConstants.ts, else the skill template, else 233."""
    for root in ([remotion] if remotion else []) + [SKILL / "templates" / "remotion"]:
        try:
            m = _ENTRANCE_RE.search((Path(root) / "src" / "motionConstants.ts").read_text(encoding="utf-8"))
        except OSError:
            continue
        if m and 0 <= int(m.group(1)) <= 1000:
            return int(m.group(1))
    return ENTRANCE_MS_FALLBACK


ENTER_MS = read_entrance_ms()
MIN_ENTER_MS = 100  # a shorter fade looks like a flicker; below this the scene cuts in (enterMs 0)
# SVG content the renderer must never see (it is inserted as markup): scripts, event handlers,
# foreign HTML and any reference that leaves the file.
UNSAFE_SVG = [
    (re.compile(r"<\s*script", re.I), "a <script> element"),
    (re.compile(r"<\s*foreignObject", re.I), "a <foreignObject> (HTML inside SVG)"),
    (re.compile(r"\son[a-z]+\s*=", re.I), "an event-handler attribute (on...=)"),
    (re.compile(r"(?:href|src)\s*=\s*[\"']\s*(?!#)[^\"']+", re.I), "an href/src that is not a local #fragment"),
    (re.compile(r"javascript:", re.I), "a javascript: URL"),
    (re.compile(r"url\(\s*[\"']?\s*(?:https?:|//|data:)", re.I), "a url() that loads from outside the file"),
    (re.compile(r"<!ENTITY|<!DOCTYPE", re.I), "a DOCTYPE or ENTITY declaration"),
    (re.compile(r"<\s*(iframe|object|embed|use)\b[^>]*(?:https?:|//)", re.I), "an embedded external resource"),
]


# N07: Python mirror of templates/remotion/src/svgSanitize.ts (the render-time allowlist). Every
# refusal there is a build error here, so an unsafe file fails at build time, not mid-render.
# The renderer also scopes selectors and drops non-allowlisted CSS properties; that rewriting is
# not copied (it never refuses). tests/test_w9.py SvgSanitizeParity runs the same payloads through
# both and asserts the same accept / refuse. Change both together.
SVG_ALLOWED_ELEMENTS = {s.lower() for s in (
    "svg", "g", "defs", "title", "desc", "metadata", "symbol", "use", "switch",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "textPath",
    "marker", "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask",
    "filter", "feGaussianBlur", "feOffset", "feBlend", "feFlood", "feComposite", "feMerge", "feMergeNode",
    "feColorMatrix", "feDropShadow", "feMorphology",
    "style")}
_SVG_DROP_SUBTREE = {"metadata", "sodipodi:namedview"}
_CSS_ESCAPE_RE = re.compile(r"\\([0-9a-fA-F]{1,6})\s?|\\([^\n0-9a-fA-F])")
_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)([^)'"]*)\1\s*\)""", re.I)
_CSS_LOCAL_URL_RE = re.compile(r"""url\(\s*(['"]?)#[^)'"]*\1\s*\)""", re.I)
_CSS_LOADER_RE = re.compile(r"url\s*\(|image-set\s*\(|(^|[^\w-])src\s*\(", re.I | re.A)
_CSS_BAD_TEXT = [(re.compile(r"javascript:", re.I), "a javascript: URL"),
                 (re.compile(r"@import", re.I), "an @import"),
                 (re.compile(r"expression\s*\(", re.I), "a CSS expression()"),
                 (re.compile(r"-moz-binding|behavior\s*:", re.I), "a CSS binding")]
_CSS_SELECTOR_RE = re.compile(
    r"""^(?:[a-zA-Z*][\w-]*|#[\w-]+|\.[\w-]+|\[[\w-]+(?:[~|^$*]?=(?:"[^"\\<>]*"|'[^'\\<>]*'|[\w-]+))?\]"""
    r"""|::?[\w-]+(?:\([\w\s+-]*\))?|\s*[>+~]\s*|\s+)+$""", re.A)
_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_XLINK_NS, _XML_NS = "http://www.w3.org/1999/xlink", "http://www.w3.org/XML/1998/namespace"
_SVG_NS = "http://www.w3.org/2000/svg"


def decode_css_escapes(css: str) -> str:
    """svgSanitize.ts decodeCssEscapes: \\72 -> r, \\x -> x."""
    def one(m):
        if m.group(1):
            cp = min(int(m.group(1), 16), 0x10FFFF) or 0xFFFD
            try:
                return chr(cp)
            except ValueError:
                return "\ufffd"
        return m.group(2) or ""
    return _CSS_ESCAPE_RE.sub(one, css)


def css_problems(raw: str, where: str) -> list[str]:
    """svgSanitize.ts cssProblems: escapes, external url(), javascript:, @import, expression(),
    bindings, then any url( / image-set( / src( left after removing url(#id)."""
    out = []
    decoded = decode_css_escapes(raw)
    if decoded != raw:
        out.append(f"a CSS escape sequence in {where} (decoded: {decoded[:60]})")
    for text in (raw, decoded):
        out += [f"url({m.group(2).strip()}) in {where}" for m in _CSS_URL_RE.finditer(text) if not m.group(2).strip().startswith("#")]
        out += [f"{why} in {where}" for rx, why in _CSS_BAD_TEXT if rx.search(text)]
    rest = _CSS_LOCAL_URL_RE.sub("", decoded)
    if _CSS_LOADER_RE.search(rest) and not out:
        out.append(f"an external reference in {where}")
    return out


def stylesheet_problems(css: str) -> list[str]:
    """svgSanitize.ts scopeStylesheet refusals for one <style> body: plain `selectors { decls }`
    rules only, no at-rule, no markup, selectors from the allowed shapes naming SVG elements only."""
    where = "a <style> element"
    out = css_problems(css, where)
    no_comments = re.sub(r"/\*[\s\S]*?\*/", " ", css)
    if re.search(r"/\*|\*/", no_comments):
        out.append(f"an unterminated CSS comment in {where}")
    if "@" in no_comments:
        out.append(f"an at-rule (@...) in {where}")
    if re.search(r"<|</|-->|<!--", re.sub(r"<!--|-->", "", no_comments)):
        out.append(f"markup inside {where}")
    for m in _CSS_RULE_RE.finditer(no_comments):
        for sel in (x.strip() for x in re.sub(r"<!--|-->", "", m.group(1)).split(",")):
            if not sel:
                continue
            if not _CSS_SELECTOR_RE.match(sel):
                out.append(f'an unsupported CSS selector "{sel[:50]}" in {where}')
                continue
            bare = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", sel)
            foreign = [n.lower() for n in re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", bare, re.A) if n.lower() not in SVG_ALLOWED_ELEMENTS]
            if foreign:
                out.append(f"a selector for non-SVG elements ({', '.join(foreign)}) in {where}")
        for decl in m.group(2).split(";"):
            d = decl.strip()
            if d and d.find(":") <= 0:
                out.append(f'a malformed CSS declaration "{d[:40]}" in {where}')
    leftover = re.sub(r"<!--|-->", "", _CSS_RULE_RE.sub("", no_comments)).strip()
    if leftover:
        out.append(f'CSS that is not a plain rule ("{leftover[:40]}") in {where}')
    return out


def _svg_name(qname: str) -> tuple[str, str]:
    """(local name, qualified name as the DOM would spell it) for an ElementTree tag or attribute."""
    if qname.startswith("{"):
        ns, local = qname[1:].split("}", 1)
        if ns == _XLINK_NS:
            return local, f"xlink:{local}"
        if ns == _XML_NS:
            return local, f"xml:{local}"
        if ns == _SVG_NS:
            return local, local
        return local, f"ns:{local}"  # another namespace: the DOM name has a prefix
    return qname, qname


def svg_markup_problems(text: str) -> list[str]:
    """svgSanitize.ts sanitizeSvg refusals: element allowlist, event attributes, href / src that
    leave the file, CSS checks on every attribute value and every <style> body."""
    import xml.etree.ElementTree as ET
    out = []
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        return ["a DOCTYPE or ENTITY declaration"]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [f"malformed XML ({e}); the root element must be <svg>"]
    if _svg_name(root.tag)[0].lower() != "svg":
        return ["a root element that is not <svg>"]

    def walk(el) -> None:
        local, qname = _svg_name(el.tag)
        name = local.lower()
        if name in _SVG_DROP_SUBTREE or qname.lower() in _SVG_DROP_SUBTREE or ":" in qname:
            return  # metadata and editor elements are dropped by the renderer
        if name not in SVG_ALLOWED_ELEMENTS:
            out.append(f"a <{local}> element")
            return
        for an_raw, v in el.attrib.items():
            _, an_q = _svg_name(an_raw)
            an = an_q.lower()
            where = f"{an_q} on <{local}>"
            if an.startswith("on"):
                out.append(f"an event attribute {where}")
                continue
            if an in ("href", "xlink:href", "src"):
                if not v.strip().startswith("#"):
                    out.append(f'{an_q}="{v[:60]}" on <{local}> (only #id links are allowed)')
                continue
            if ":" in an and not an.startswith("xml") and not an.startswith("xlink:"):
                continue  # editor attributes are dropped
            out.extend(css_problems(v, where))
            if an == "style":
                for decl in decode_css_escapes(v).split(";"):
                    d = decl.strip()
                    if d and d.find(":") <= 0:
                        out.append(f'a malformed CSS declaration "{d[:40]}" in {where}')
        if name == "style":
            if len(el):
                out.append("markup inside a <style> element")
            out.extend(stylesheet_problems("".join(el.itertext())))
            return
        for child in el:
            walk(child)

    walk(root)
    return list(dict.fromkeys(out))


def svg_problems(path: Path, markup: bool = True) -> list[str]:
    """Problems in an SVG file. markup=True (a diagram the renderer inserts as markup) adds the full
    svgSanitize.ts mirror; markup=False (an <Img> such as a world anchorImage) keeps the regex scan."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [f"cannot read: {e}"]
    out = [why for rx, why in UNSAFE_SVG if rx.search(text)]
    if markup:
        out += [w for w in svg_markup_problems(text) if w not in out]
    return out


class Problems:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# ----------------------------------------------------------------------------- schema validation

def _load_validator():
    try:
        import jsonschema  # type: ignore

        def validate(instance, schema):
            v = jsonschema.Draft202012Validator(schema)
            return [
                f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
                for e in sorted(v.iter_errors(instance), key=lambda e: list(e.absolute_path))
            ]

        return validate
    except ImportError:
        return _mini_validate


def _mini_validate(instance, schema):
    """Subset of JSON Schema 2020-12 used by this skill's schemas, for machines without jsonschema."""
    root = schema
    errors: list[str] = []
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}

    def is_type(v, t):
        if t == "integer":
            return isinstance(v, int) and not isinstance(v, bool)
        if t == "number":
            return isinstance(v, (int, float)) and not isinstance(v, bool)
        return isinstance(v, types[t])

    def resolve(ref):
        node = root
        for part in ref.lstrip("#/").split("/"):
            node = node[part]
        return node

    def check(v, s, path) -> list[str]:
        out: list[str] = []
        if "$ref" in s:
            out += check(v, resolve(s["$ref"]), path)
        if "type" in s:
            ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(is_type(v, t) for t in ts):
                return out + [f"{path}: expected {'/'.join(ts)}"]
        if "const" in s and v != s["const"]:
            out.append(f"{path}: must be {s['const']!r}")
        if "enum" in s and v not in s["enum"]:
            out.append(f"{path}: {v!r} is not one of {s['enum']}")
        if isinstance(v, str):
            if len(v) < s.get("minLength", 0):
                out.append(f"{path}: shorter than {s['minLength']}")
            if "maxLength" in s and len(v) > s["maxLength"]:
                out.append(f"{path}: longer than {s['maxLength']} characters")
            if "pattern" in s and not re.search(s["pattern"], v):
                out.append(f"{path}: {v!r} does not match {s['pattern']}")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if "minimum" in s and v < s["minimum"]:
                out.append(f"{path}: {v} < {s['minimum']}")
            if "maximum" in s and v > s["maximum"]:
                out.append(f"{path}: {v} > {s['maximum']}")
        if isinstance(v, list):
            if len(v) < s.get("minItems", 0):
                out.append(f"{path}: fewer than {s['minItems']} items")
            if "maxItems" in s and len(v) > s["maxItems"]:
                out.append(f"{path}: more than {s['maxItems']} items")
            if "items" in s:
                for i, item in enumerate(v):
                    out += check(item, s["items"], f"{path}/{i}")
        if isinstance(v, dict):
            for k in s.get("required", []):
                if k not in v:
                    out.append(f"{path}: missing required '{k}'")
            props = s.get("properties", {})
            for k, item in v.items():
                if k in props:
                    out += check(item, props[k], f"{path}/{k}")
                elif s.get("additionalProperties") is False:
                    out.append(f"{path}: unknown key '{k}'")
                elif isinstance(s.get("additionalProperties"), dict):
                    out += check(item, s["additionalProperties"], f"{path}/{k}")
        for sub in s.get("allOf", []):
            out += check(v, sub, path)
        if "anyOf" in s and all(check(v, sub, path) for sub in s["anyOf"]):
            out.append(f"{path}: matches none of anyOf")
        if "oneOf" in s:
            ok = sum(1 for sub in s["oneOf"] if not check(v, sub, path))
            if ok != 1:
                out.append(f"{path}: must match exactly one of oneOf (matched {ok})")
        if "if" in s and not check(v, s["if"], path):
            out += check(v, s.get("then", {}), path)
        return out

    errors += check(instance, schema, "(root)")
    return errors


VALIDATE = _load_validator()


def validate_file(data, schema_name: str, label: str, probs: Problems) -> None:
    path = SCHEMAS / schema_name
    if not path.is_file():
        probs.warn(f"schema {schema_name} not found in {SCHEMAS}; {label} not schema-checked")
        return
    for e in VALIDATE(data, json.loads(path.read_text())):
        probs.err(f"{label}: {e}")


# ----------------------------------------------------------------------------- helpers

def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower().replace("’", "").replace("'", ""))


def spoken(text: str) -> str:
    return re.sub(r"\s{2,}", " ", PIPE_RE.sub(" ", TAG_RE.sub(" ", text))).strip()


def load_json(path: Path, probs: Problems):
    if not path.is_file():
        probs.err(f"missing {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        probs.err(f"{path} is not valid JSON: {e}")
        return None


def probe_ms(path: Path) -> int | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        return round(float(r.stdout.strip()) * 1000)
    except Exception:
        return None


def estimate_words(text: str, start: int, end: int) -> list[dict]:
    toks = [t for t in spoken(text).split() if t]
    merged: list[str] = []
    for t in toks:  # punctuation-only tokens join the previous word (as align.mjs does)
        if not norm(t) and merged:
            merged[-1] += f" {t}"
        else:
            merged.append(t)
    lens = [max(1, len(norm(t))) + 1 for t in merged]
    total = sum(lens) or 1
    out, acc = [], float(start)
    for t, n in zip(merged, lens):
        d = (end - start) * n / total
        out.append({"text": t, "startMs": round(acc), "endMs": round(acc + d), "source": "estimated"})
        acc += d
    return out


# ----------------------------------------------------------------------------- anchors

class Resolver:
    def __init__(self, turns: dict[str, dict]):
        self.turns = turns

    def point(self, p, where: str, probs: Problems, default_edge: str = "start") -> int | None:
        if not isinstance(p, dict):
            probs.err(f"{where}: anchor must be an object like {{\"turn\": \"t03\", \"word\": \"bucket\"}}")
            return None
        if "ms" in p:
            return int(p["ms"])
        tid = p.get("turn")
        turn = self.turns.get(tid)
        if turn is None:
            probs.err(f"{where}: turn {tid!r} is not in script.json/timing.json")
            return None
        edge = p.get("edge", default_edge)
        word = p.get("word")
        off = int(p.get("offsetMs", 0))
        if not word:
            return (turn["endMs"] if edge == "end" else turn["startMs"]) + off
        want = [norm(w) for w in str(word).split() if norm(w)]
        if not want:
            probs.err(f"{where}: anchor word {word!r} has no letters or digits, so it would match anywhere; "
                      f"anchor to a real word of turn {tid}, or drop 'word' to anchor to the turn edge")
            return None
        words = turn["words"]
        normed = [norm(w["text"]) for w in words]
        occ = int(p.get("occurrence", 1))
        seen = 0
        for i in range(len(words) - len(want) + 1):
            if normed[i:i + len(want)] == want:
                seen += 1
                if seen == occ:
                    w = words[i + len(want) - 1] if edge == "end" else words[i]
                    return (w["endMs"] if edge == "end" else w["startMs"]) + off
        probs.err(
            f"{where}: word {word!r} (occurrence {occ}) not found in turn {tid}: \"{turn['text']}\". "
            f"Anchor words must appear verbatim (case and punctuation ignored)."
        )
        return None

    def props(self, obj, where: str, probs: Problems, cues: list[tuple[str, int]]):
        """Resolve every key 'at' or '*At' holding an anchor point; add '<key>Ms' next to it."""
        if isinstance(obj, list):
            for i, item in enumerate(obj):
                self.props(item, f"{where}[{i}]", probs, cues)
        elif isinstance(obj, dict):
            for k in list(obj.keys()):
                v = obj[k]
                if (k == "at" or (k.endswith("At") and len(k) > 2)) and isinstance(v, dict) and ("turn" in v or "ms" in v):
                    ms = self.point(v, f"{where}.{k}", probs)
                    if ms is not None:
                        obj[f"{k}Ms"] = ms
                        cues.append((f"{where}.{k}", ms))
                else:
                    self.props(v, f"{where}.{k}", probs, cues)


# ----------------------------------------------------------------------------- main build

def build(args) -> int:
    probs = Problems()
    ws = Path(args.workspace).resolve()
    try:
        ep = pc.episode_dir(ws, args.slug)
    except pc.BadId as e:
        print(f"build_manifest: error: {e}", file=sys.stderr)
        return 2
    remotion = Path(args.remotion_dir).resolve() if args.remotion_dir else ws / "remotion"

    script = load_json(ep / "script.json", probs)
    scenes_doc = load_json(ep / "scenes.json", probs)
    timing = None if args.placeholder_timing else load_json(ep / "timing.json", probs)
    if probs.errors:
        return report(probs, None)

    validate_file(scenes_doc, "scenes.schema.json", "scenes.json", probs)
    if timing is not None:
        validate_file(timing, "timing.schema.json", "timing.json", probs)
    if probs.errors:
        return report(probs, None)

    # ---- turns: script text + timing
    script_turns: list[dict] = []
    for seg in script.get("segments", []):
        for t in seg.get("turns", []):
            script_turns.append({**t, "segment": seg["id"]})
    if not script_turns:
        probs.err("script.json has no turns")
        return report(probs, None)

    timing_source = "whisper.cpp"
    if timing is None:
        cursor, tturns = PLACEHOLDER_GAP, []
        for t in script_turns:
            dur = max(800, round(len(spoken(t["text"]).split()) / PLACEHOLDER_WPS * 1000))
            hold = int(t.get("holdAfterMs", 0) or 0)
            tturns.append({"id": t["id"], "startMs": cursor, "endMs": cursor + dur, **({"holdAfterMs": hold} if hold else {})})
            cursor += dur + PLACEHOLDER_GAP + hold
        timing = {"durationMs": cursor + 350, "turns": tturns, "sampleRate": 24000, "mode": "placeholder"}
        timing_source = "placeholder"
    tmap = {t["id"]: t for t in timing["turns"]}

    turns: list[dict] = []
    sources: set[str] = set()
    for t in script_turns:
        tt = tmap.get(t["id"])
        if tt is None:
            probs.err(f"turn {t['id']} is in script.json but not in timing.json; rerun tts.py")
            continue
        if tt["endMs"] <= tt["startMs"]:
            probs.err(f"turn {t['id']}: endMs {tt['endMs']} <= startMs {tt['startMs']} in timing.json")
            continue
        words = tt.get("words")
        if words and tt.get("audioSha") and tt.get("alignedAudioSha") != tt.get("audioSha"):
            probs.err(f"turn {t['id']}: words[] were aligned to another take (alignedAudioSha differs from audioSha); "
                      f"rerun align.mjs --only {t['id']}")
            continue
        if not words:
            if timing_source != "placeholder":
                probs.warn(f"turn {t['id']} has no words[]; estimated from letters. Run align.mjs for measured word times.")
            words = estimate_words(t["text"], tt["startMs"], tt["endMs"])
        sources.update(w["source"] for w in words)
        hold = int(t.get("holdAfterMs", 0) or 0)
        if hold != int(tt.get("holdAfterMs", 0) or 0):
            probs.err(f"turn {t['id']}: holdAfterMs is {hold} in script.json but {tt.get('holdAfterMs', 0)} in timing.json; "
                      f"rerun tts.py (cached takes are reused, a hold change costs nothing)")
        turns.append({
            "id": t["id"], "speaker": t["speaker"], "segment": t["segment"], "text": spoken(t["text"]),
            "startMs": int(tt["startMs"]), "endMs": int(tt["endMs"]),
            "onScreen": list(t.get("onScreen", [])),
            **({"holdAfterMs": hold} if hold else {}),
            "words": [{"text": w["text"], "startMs": int(w["startMs"]), "endMs": int(w["endMs"]), "source": w["source"]} for w in words],
            **({"_holdSpan": (int(tt["holdStartMs"]), int(tt["holdEndMs"]))} if "holdStartMs" in tt and "holdEndMs" in tt else {}),
        })
    extra = set(tmap) - {t["id"] for t in script_turns}
    if extra:
        probs.warn(f"timing.json has turns not in script.json (ignored): {', '.join(sorted(extra))}")
    for a, b in zip(turns, turns[1:]):
        if b["startMs"] < a["endMs"]:
            probs.err(f"turns {a['id']} and {b['id']} overlap in timing.json ({a['endMs']} > {b['startMs']})")
    if probs.errors:
        return report(probs, None)

    # ---- holds: pause-and-think silences after a turn (script.json holdAfterMs + pause)
    holds = []
    pauses = {t["id"]: t.get("pause") for t in script_turns}
    for i, t in enumerate(turns):
        h = t.get("holdAfterMs", 0)
        if not h:
            t.pop("_holdSpan", None)
            continue
        nxt = turns[i + 1]["startMs"] if i + 1 < len(turns) else None
        span = t.pop("_holdSpan", None)
        start = span[0] if span else t["endMs"]
        end = span[1] if span else t["endMs"] + h
        if nxt is not None:
            end = min(end, nxt)
        if span and span[1] - span[0] != h:
            probs.err(f"turn {t['id']}: timing.json hold span {span[0]}..{span[1]} is not holdAfterMs {h}; rerun tts.py")
        if nxt is not None and nxt - start < h:
            probs.warn(f"turn {t['id']}: the next turn starts {nxt - t['endMs']} ms after it, less than its holdAfterMs {h}; "
                       f"the pause cue is cut short. Rerun tts.py so the audio carries the hold.")
        pz = pauses.get(t["id"]) or {}
        if not pz:
            probs.warn(f"turn {t['id']}: holdAfterMs {h} without a pause cue; the screen shows no prompt during the hold")
        holds.append({"turn": t["id"], "segment": t["segment"], "holdMs": h, "startMs": int(start), "endMs": int(end),
                      "kind": pz.get("kind"), "prompt": pz.get("prompt")})
    if timing_source != "placeholder":
        timing_source = "whisper.cpp" if sources == {"asr", "interpolated"} or sources == {"asr"} else (
            "estimated" if sources == {"estimated"} else "mixed")

    # ---- audio
    duration = int(timing["durationMs"])
    audio_src = None
    wav = ep / "audio" / "episode.wav"
    if not args.placeholder_timing:
        if not wav.is_file():
            probs.err(f"missing {wav}; run tts.py first, or pass --placeholder-timing for stills without audio")
            return report(probs, None)
        real = probe_ms(wav)
        if real is None:
            probs.warn(f"ffprobe could not read {wav}; using timing.durationMs {duration}")
        elif abs(real - duration) > 40:
            probs.warn(f"episode.wav is {real} ms but timing.durationMs is {duration} ms; using the file's {real} ms")
            duration = real
        audio_src = "episode.wav"
    if turns[-1]["endMs"] > duration:
        probs.err(f"last turn ends at {turns[-1]['endMs']} ms, after the audio ends ({duration} ms)")

    resolver = Resolver({t["id"]: t for t in turns})

    # ---- tail
    tail_req = args.tail_ms if args.tail_ms is not None else (scenes_doc.get("video", {}).get("tailMs", TAIL_DEFAULT))
    tail = min(TAIL_MAX, max(TAIL_MIN, int(tail_req)))
    if tail != tail_req:
        probs.warn(f"video.tailMs {tail_req} clamped to {tail} (allowed {TAIL_MIN}..{TAIL_MAX})")
    end_of_video = duration + tail

    # ---- scenes
    scenes = copy.deepcopy(scenes_doc["scenes"])
    seen_ids: set[str] = set()
    cue_log: dict[str, list[tuple[str, int]]] = {}
    for sc in scenes:
        where = f"scene {sc['id']}"
        if sc["id"] in seen_ids:
            probs.err(f"{where}: duplicate scene id")
        seen_ids.add(sc["id"])
        sc["startMs"] = resolver.point(sc["anchor"]["from"], f"{where} anchor.from", probs)
        to = sc["anchor"].get("to")
        sc["_to"] = resolver.point(to, f"{where} anchor.to", probs, default_edge="start") if to else None
        cues: list[tuple[str, int]] = []
        resolver.props(sc["props"], f"{where} props", probs, cues)
        cue_log[sc["id"]] = cues
    if probs.errors:
        return report(probs, None)

    scenes.sort(key=lambda s: s["startMs"])
    if scenes[0]["startMs"] > 0:
        scenes[0]["startMs"] = 0  # the picture is never empty before the first anchor
    for i, sc in enumerate(scenes):
        nxt = scenes[i + 1] if i + 1 < len(scenes) else None
        limit = nxt["startMs"] if nxt else end_of_video
        end = sc.pop("_to")
        if end is None:
            end = limit
        if nxt and end > nxt["startMs"]:
            probs.err(
                f"scene {sc['id']} ({sc['startMs']}..{end} ms) overlaps scene {nxt['id']} (starts {nxt['startMs']} ms). "
                f"Scenes share one main visual track; end {sc['id']} at or before {nxt['id']}'s anchor.from."
            )
        if end < limit:
            if limit - end > GAP_WARN_MS:
                what = "the next scene" if nxt else "the end of the video (tail pad and video.tailMs)"
                hint = "" if nxt else "; anchor its `to` with no edge, or leave it, the tail is silent"
                probs.warn(f"scene {sc['id']} ends {limit - end} ms before {what}; it holds its last frame through the gap{hint}")
            end = limit
        if end <= sc["startMs"]:
            probs.err(f"scene {sc['id']}: end {end} ms is not after start {sc['startMs']} ms")
        sc["endMs"] = int(end)
        sc["startMs"] = int(sc["startMs"])
        for label, ms in cue_log[sc["id"]]:
            if ms < sc["startMs"] - 50 or ms > sc["endMs"]:
                probs.warn(f"{label} fires at {ms} ms, outside its scene window {sc['startMs']}..{sc['endMs']} ms")
        if sc["type"] == "world" and not scenes_doc.get("world"):
            probs.err(f"scene {sc['id']} is type 'world' but scenes.json has no top-level 'world'")
        if sc["type"] == "compare":
            check_compare(sc, scenes_doc.get("world"), resolver, probs)
        if sc["type"] == "diagram" and sc["props"].get("svg"):
            try:
                svg = pc.safe_path(ep, ep / sc["props"]["svg"], f"scene {sc['id']} diagram")
            except pc.BadId as e:
                probs.err(str(e))
                continue
            if not svg.is_file():
                probs.err(f"scene {sc['id']}: diagram file {svg} not found")
            else:
                for why in svg_problems(svg):
                    probs.err(f"scene {sc['id']}: {svg} contains {why}; the renderer inserts SVG as markup, so only "
                              f"self-contained shapes and text are allowed. Remove it and rebuild.")
        if (lead := empty_stage_ms(sc)) is not None and lead > EMPTY_STAGE_MS:  # W16 (W14b D16)
            probs.warn(f"scene {sc['id']} shows only its title for {lead / 1000:.1f} s before its first line appears; "
                       f"anchor the scene later, or anchor the first line to an earlier word")
        if sc["type"] == "diagram":  # W16 (W14b D11): `hide` is for good, so a later reveal of it never shows
            for msg in diagram_hide_problems(sc["props"].get("steps") or []):
                probs.warn(f"scene {sc['id']}: {msg}")
        if sc["type"] == "check" and sc["props"].get("answer") and "answerAtMs" not in sc["props"]:
            probs.err(f"scene {sc['id']}: check card has an answer but no answerAt; anchor the answer to the word that "
                      f"gives it, or drop the answer (a final self-test card shows no answer)")
        if sc["type"] == "code" and len(sc["props"]["code"].rstrip("\n").split("\n")) > 24:
            probs.warn(f"scene {sc['id']}: code has more than 24 lines; the panel shows about 11 at a time and scrolls")

    # ---- entrances (A09): speech never overlaps a scene's entrance fade. The scene start moves up
    # to ENTER_MS (the Remotion project's ENTRANCE_MS) into the silence before its anchor
    # (enterLeadMs); when that silence is shorter, the entrance is shortened to fit it (enterMs,
    # read by Episode.tsx as round(enterMs * fps / 1000) frames instead of ENTRANCE_FRAMES), or the
    # scene cuts in (enterMs 0); a scene anchored inside a spoken turn cuts in. The check is on
    # rendered frames. Speech left inside a rendered entrance is an error (it should never happen).
    entrances = place_entrances(scenes, turns, read_entrance_ms(remotion))
    for sc_id, overlap_ms, tid in entrances["overlaps"]:
        probs.err(f"scene {sc_id}: speech of {tid} overlaps its rendered entrance by {overlap_ms} ms; "
                  f"anchor the scene to the start of a turn (report this: place_entrances should have shortened it)")

    # ---- world: ids, references, reveal times
    world = copy.deepcopy(scenes_doc.get("world")) if scenes_doc.get("world") else None
    if world:
        build_world(world, scenes, resolver, probs)
        check_route(world, [seg["id"] for seg in script["segments"]], probs)
        for n in world["nodes"]:
            if n.get("anchorImage"):
                try:
                    pc.safe_path(ep, ep / n["anchorImage"], f"world node {n['id']} anchorImage")
                except pc.BadId as e:
                    probs.err(str(e))
                    continue
            if n.get("anchorImage") and not (ep / n["anchorImage"]).is_file():
                probs.err(f"world node {n['id']}: anchorImage {ep / n['anchorImage']} not found")
            elif n.get("anchorImage", "").endswith(".svg"):
                for why in svg_problems(ep / n["anchorImage"], markup=False):
                    probs.err(f"world node {n['id']}: {n['anchorImage']} contains {why}; remove it")

    # ---- overlays
    overlays = []
    for ov in copy.deepcopy(scenes_doc.get("overlays", [])):
        where = f"overlay {ov['id']}"
        s = resolver.point(ov["anchor"]["from"], f"{where} anchor.from", probs)
        to = ov["anchor"].get("to")
        if to:
            e = resolver.point(to, f"{where} anchor.to", probs)
        elif s is not None:
            # default: to the end of the turn it starts in, at least 2.5 s
            host = next((t for t in turns if t["startMs"] <= s <= t["endMs"]), None)
            e = max(s + 2500, host["endMs"] if host else s)
        else:
            e = None
        if s is None or e is None:
            continue
        if e <= s:
            probs.err(f"{where}: ends at {e} ms, not after its start {s} ms")
            continue
        ov.update({"startMs": int(s), "endMs": int(e)})
        overlays.append(ov)

    # ---- onScreen terms need a visual event
    check_on_screen(turns, scenes, overlays, world, probs, args.auto_chips)
    overlays.sort(key=lambda o: o["startMs"])

    if probs.errors:
        return report(probs, None)

    # ---- segments
    segs = []
    for seg in script["segments"]:
        st = [t for t in turns if t["segment"] == seg["id"]]
        if not st:
            continue
        segs.append({"id": seg["id"], "role": seg["role"], **({"title": seg["title"]} if seg.get("title") else {}),
                     "startMs": st[0]["startMs"], "endMs": 0})
    for a, b in zip(segs, segs[1:]):
        a["endMs"] = b["startMs"]
    if segs:
        segs[0]["startMs"] = 0
        segs[-1]["endMs"] = end_of_video

    cap = scenes_doc.get("captions", {})
    speakers = [{k: s[k] for k in ("id", "name", "voice", "color", "side", "role", "avatar") if k in s} for s in script["speakers"]]
    episode = {
        "version": 1,
        "id": script.get("id", args.slug),
        "title": script["title"],
        **({"conceptAngle": scenes_doc["conceptAngle"]} if scenes_doc.get("conceptAngle") else {}),
        "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "timingSource": timing_source,
        "video": {"fps": FPS, "width": WIDTH, "height": HEIGHT, "tailMs": tail},
        "audio": {"src": audio_src, "durationMs": duration, "sampleRate": int(timing.get("sampleRate", 24000)),
                  "scratch": bool(timing.get("scratch", False))},
        "speakers": speakers,
        "segments": segs,
        "turns": turns,
        "holds": holds,
        "scenes": scenes,
        "overlays": overlays,
        "world": world,
        "captions": {"mode": cap.get("mode", "karaoke"), "maxCharsPerSecond": cap.get("maxCharsPerSecond", 17),
                     "minPageMs": cap.get("minPageMs", 700)},
        "rail": {"waveform": bool(scenes_doc.get("rail", {}).get("waveform", False))},
    }
    if episode["id"] != args.slug:
        probs.warn(f"script.json id {episode['id']!r} differs from --slug {args.slug!r}; Remotion reads public/episodes/{args.slug}/")
    for d in ("diagrams", "img", "icons"):  # C02: assets are real files under the episode, never links
        if (ep / d).is_symlink():
            probs.err(f"{ep / d} is a symbolic link; refusing to copy assets through it")
        elif (ep / d).is_dir():
            for root, dirs, files in os.walk(ep / d, followlinks=False):
                for name in dirs + files:
                    if (Path(root) / name).is_symlink():
                        probs.err(f"asset {Path(root) / name} is a symbolic link; replace it with the real file")
    for s in episode["speakers"]:  # assets are checked before anything is written
        if s.get("avatar"):
            try:
                src = pc.safe_path(ep, ep / s["avatar"], f"speaker {s['id']} avatar")
            except pc.BadId as e:
                probs.err(str(e))
                continue
            if not src.is_file():
                probs.err(f"speaker {s['id']}: avatar {s['avatar']} not found under {ep} (put it in img/)")
    # The checks the renderer enforces by throwing (W11b): one ring circle per role, walk arrows that
    # end at the successor, drawable compare tables. Run them here so a render never starts.
    if episode.get("world"):
        for msg in pc.ring_problems(episode["world"]) + pc.walk_problems(episode["world"], pc.world_timeline(episode)):
            probs.err(f"world: {msg}")
        # W13b (judge v6, seg03 t23): a spotlight that dims what the words or a walk are about. Warnings.
        for msg in pc.focus_problems(episode):
            probs.warn(f"focus: {msg}")
    for sc in episode.get("scenes", []):
        if sc.get("type") == "matrix":  # W16: the renderer throws the same messages (matrixLayout.ts)
            for msg in pc.matrix_problems(sc.get("props") or {}):
                probs.err(f"scene {sc['id']} matrix: {msg}")
        if sc.get("type") != "compare":
            continue
        for side in ("left", "right"):
            pn = (sc.get("props") or {}).get(side) or {}
            if pn.get("kind") == "table":
                for msg in pc.table_problems(pn, bool((sc.get("props") or {}).get("title"))):
                    if "cells for" not in msg:  # row lengths are reported by check_compare
                        probs.err(f"scene {sc['id']} {side} table: {msg}")
            elif pn.get("kind") == "world" and isinstance(pn.get("world"), dict):
                tl = pc.local_timeline(pn.get("steps") or [], f"{sc['id']}-{side}", sc.get("startMs", 0))
                for msg in pc.ring_problems(pn["world"]) + pc.walk_problems(pn["world"], tl):
                    probs.err(f"scene {sc['id']} {side} panel: {msg}")
    # Q05 (codex round 4): a count claim's displayed text must state the claim's numbers.
    for sc in episode.get("scenes", []):
        for where, text, claim in pc.claim_texts(sc.get("props") or {}):
            if (why := pc.claim_text_problem(text, claim)):
                probs.err(f"scene {sc.get('id')} {where}: {why}; write the text from the claim (e.g. '{claim.get('value')} of {claim.get('of')} move')")
    for i, ov in enumerate(episode.get("overlays", []) or []):
        for where, text, claim in pc.claim_texts(ov.get("props") or {}):
            if (why := pc.claim_text_problem(text, claim)):
                probs.err(f"overlay {i} {where}: {why}; write the text from the claim")
    validate_file(episode, "episode.schema.json", "episode.json", probs)
    if probs.errors:
        return report(probs, None)

    out = ep / "episode.json"
    write_atomic(out, json.dumps(episode, indent=2, ensure_ascii=False) + "\n")
    synced = None
    if not args.no_sync:
        synced = sync(ep, remotion, args.slug, episode, probs)
    return report(probs, (out, synced, episode))


EMPTY_STAGE_MS = 2000


def empty_stage_ms(sc: dict) -> int | None:
    """How long an equation scene, or a compare scene whose panels are all text with cued lines,
    shows nothing but its title (first line cue minus scene start). None when it never starts empty."""
    p = sc.get("props") or {}
    if sc.get("type") == "equation":
        lines = p.get("lines") or []
    elif sc.get("type") == "compare" and all((p.get(s) or {}).get("kind") == "text" for s in ("left", "right") if p.get(s)):
        lines = [ln for s in ("left", "right") for ln in (p.get(s) or {}).get("lines") or []]
    else:
        return None
    if not lines or any(not isinstance(ln.get("atMs"), (int, float)) for ln in lines):
        return None
    return int(min(ln["atMs"] for ln in lines) - sc["startMs"])


def diagram_hide_problems(steps: list[dict]) -> list[str]:
    """Diagram elements a step reveals after an earlier step hid them. `hide` fades an element out
    for good (DiagramScene.tsx), so the reveal never shows it (W14b D11)."""
    out, hidden = [], {}
    for i, st in enumerate(steps):
        for eid in st.get("reveal") or []:
            if eid in hidden:
                out.append(f"diagram step {i} reveals {eid!r}, but step {hidden[eid]} hid it and `hide` is for good, so it "
                           f"never shows again. Drop the hide (an element with a reveal step is hidden until that step), or "
                           f"reveal a copy with another id")
        for eid in st.get("hide") or []:
            hidden.setdefault(eid, i)
    return out


def place_entrances(scenes: list[dict], turns: list[dict], enter_ms: int | None = None) -> dict:
    """Entrance timing for every fading scene (A09). Sets startMs (moved into silence),
    enterLeadMs and enterMs, and returns the speech overlaps that remain (> 0 ms) with the turn.
    enter_ms is the full fade (default ENTER_MS, the renderer's ENTRANCE_MS)."""
    full = ENTER_MS if enter_ms is None else enter_ms
    speech = sorted((t["startMs"], t["endMs"], t["id"]) for t in turns)
    overlaps = []

    def fit_frames(start_ms: float, enter: float, limit_ms) -> int:
        """enterMs that Episode.tsx renders without speech inside the fade (A09): the fade runs over
        frames [msToFrame(start), msToFrame(start) + round(enter * fps / 1000)) and ends at
        (from + frames) * 1000 / fps ms, which must be at or before `limit_ms` (the next speech
        start). Returns whole-frame ms, or 0 (a cut) when under MIN_ENTER_MS remains."""
        frm = pc.ms_to_frame(start_ms, FPS)
        frames = max(0, pc._js_round(enter * FPS / 1000))
        if limit_ms is not None:
            while frames > 0 and (frm + frames) * 1000 / FPS > limit_ms + 1e-6:
                frames -= 1
        ms = round(frames * 1000 / FPS)
        return int(ms) if ms >= MIN_ENTER_MS else 0
    if scenes:
        # The first scene starts the video: it cannot move earlier, so only its fade length fits the
        # silence before the first word (Episode.tsx fades it over ENTRANCE_FRAMES when enterMs is absent).
        s0 = scenes[0]["startMs"]
        if not any(a < s0 < b for a, b, _ in speech):
            nxt = min((a for a, _, _ in speech if a >= s0), default=None)
            enter = min(full, full if nxt is None else nxt - s0)
            scenes[0]["enterMs"] = fit_frames(s0, enter if enter >= MIN_ENTER_MS else 0, nxt)
    for i in range(1, len(scenes)):
        sc, prev = scenes[i], scenes[i - 1]
        if prev["type"] == "world" and sc["type"] == "world":
            continue  # world -> world keeps the stage, no fade
        a = sc["startMs"]
        inside = next(((s0, e0, tid) for s0, e0, tid in speech if s0 < a < e0), None)
        if inside:
            # Anchored on a word inside a turn: the scene CUTS in on that word (enterMs 0), so no fade
            # ever overlaps speech (A09, codex round 3). Anchor on a turn start for a fade.
            sc["enterMs"] = 0
            continue
        last_end = max((e0 for s0, e0, _ in speech if e0 <= a), default=0)
        lead = max(0, min(full, a - last_end, a - prev["startMs"] - 1000))
        start = a - lead
        f0 = pc.ms_to_frame(start, FPS)
        if lead and f0 * 1000 / FPS < last_end - 1:  # 1 ms: integer ms against a 33.3 ms frame grid
            # rounding to a frame would start the fade inside the previous turn's last word
            start = min(a, int(round((f0 + 1) * 1000 / FPS)))
            lead = a - start
        nxt = min((s0 for s0, _, _ in speech if s0 >= start), default=None)
        room = full if nxt is None else nxt - start
        enter = min(full, room)
        if enter < MIN_ENTER_MS:
            enter = 0
        enter = fit_frames(start, enter, nxt)
        if lead and enter < min(full, room):
            # Frame rounding cost part of the fade: try a start up to a few frames earlier, still in the
            # silence after the previous turn and 1 s after the previous scene start, on a whole frame.
            earliest = max(last_end, prev["startMs"] + 1000)
            f0 = pc.ms_to_frame(start, FPS)
            for f in range(f0 - 1, f0 - 4, -1):
                cand = int(round(f * 1000 / FPS))
                if cand < earliest or pc.ms_to_frame(cand, FPS) != f:
                    break
                e2 = fit_frames(cand, min(full, (nxt - cand) if nxt is not None else full), nxt)
                if e2 > enter:
                    start, enter, lead = cand, e2, a - cand
                if enter >= full:
                    break
        if lead:
            sc["startMs"] = start
            prev["endMs"] = start
            sc["enterLeadMs"] = int(lead)
        sc["enterMs"] = int(enter)
        # Rendered-frame check: the fade interval in frames, converted back to ms, against speech.
        frm = pc.ms_to_frame(start, FPS)
        f_end = (frm + pc._js_round(enter * FPS / 1000)) * 1000 / FPS
        f_start = frm * 1000 / FPS
        spoken = next(((s0, e0, tid) for s0, e0, tid in speech if enter and s0 < f_end - 1 and e0 > f_start + 1), None)
        if spoken:
            overlaps.append((sc["id"], int(math.ceil(min(f_end, spoken[1]) - max(f_start, spoken[0]))), spoken[2]))
    return {"overlaps": [o for o in overlaps if o[1] > 0]}


def place_ring(world: dict, where: str, probs: Problems) -> None:
    """Ring layout: give every node with pos or angle its x, y (same formula as the template's
    worldState.ts placeNodes), so QC geometry and the renderer agree."""
    W, H = world.get("width", 1728), world.get("height", 712)
    ring = world.get("ring")
    on_ring = [n for n in world["nodes"] if "pos" in n or "angle" in n]
    if world.get("layout") != "ring":
        for n in world["nodes"]:
            if n.get("role"):
                probs.warn(f"{where} node {n['id']}: role {n['role']!r} only works with layout 'ring'")
            if "x" not in n or "y" not in n:
                probs.err(f"{where} node {n['id']}: needs x and y (pos and angle need layout 'ring')")
        return
    if not ring:
        probs.err(f"{where}: layout 'ring' needs ring: {{positions: N}}")
        return
    positions = ring["positions"]
    cx, cy = ring.get("cx", W / 2), ring.get("cy", H / 2)
    r = ring.get("r", math.floor(0.31 * min(W, H) + 0.5))
    for n in world["nodes"]:
        if "pos" in n and n["pos"] >= positions:
            probs.err(f"{where} node {n['id']}: pos {n['pos']} is outside 0..{positions - 1}")
        if n in on_ring:
            a = n["angle"] if "angle" in n else n["pos"] * 360 / positions
            rr = r + n.get("ringOffset", 0)
            n["x"] = round(cx + rr * math.sin(math.radians(a)), 2)
            n["y"] = round(cy - rr * math.cos(math.radians(a)), 2)
        elif "x" not in n or "y" not in n:
            probs.err(f"{where} node {n['id']}: needs x and y, or pos or angle on the ring")
        elif n.get("role"):
            probs.warn(f"{where} node {n['id']}: role {n['role']!r} needs pos or angle; it is ignored")
    if not any(n.get("role") == "owner" for n in world["nodes"]) and any(n.get("role") == "item" for n in world["nodes"]):
        probs.warn(f"{where}: ring items but no owner nodes, so no item is coloured")


def world_step_sources(scenes: list[dict]) -> list[tuple[dict, str, list[dict]]]:
    """Every step list that acts on the persistent world: world scenes, custom scenes' worldSteps,
    compare panels with world 'shared' (same rule as worldState.ts buildTimeline)."""
    out = []
    for sc in scenes:
        props = sc.get("props") or {}
        if sc["type"] == "world":
            out.append((sc, f"scene {sc['id']}", props.get("steps", [])))
        elif sc["type"] == "custom" and isinstance(props.get("worldSteps"), list):
            out.append((sc, f"scene {sc['id']} worldSteps", props["worldSteps"]))
        elif sc["type"] == "compare":
            for side in ("left", "right"):
                panel = props.get(side) or {}
                if panel.get("kind") == "world" and panel.get("world") == "shared":
                    out.append((sc, f"scene {sc['id']} {side} panel", panel.get("steps", [])))
    return out


def check_steps(world: dict, steps: list[dict], where: str, start_ms: int, probs: Problems, first_seen: dict) -> None:
    nodes = {n["id"] for n in world["nodes"]}
    edges = {e["id"] for e in world["edges"]}
    roles = {n["id"]: n.get("role") for n in world["nodes"]}
    positions = (world.get("ring") or {}).get("positions")
    for i, st in enumerate(steps):
        t = st.get("atMs", start_ms)
        w = f"{where} step {i}"
        for key in ("focus", "pulse"):
            for nid in st.get(key, []):
                if nid not in nodes:
                    probs.err(f"{w}: {key} names unknown node {nid!r}")
        for key in ("focusEdges", "flow"):
            for eid in st.get(key, []):
                if eid not in edges:
                    probs.err(f"{w}: {key} names unknown edge {eid!r}")
        for key in ("reveal", "hide"):
            for xid in st.get(key, []):
                if xid not in nodes and xid not in edges:
                    probs.err(f"{w}: {key} names unknown node or edge {xid!r}")
        for wk in st.get("walk", []):
            nid = pc.walk_item(wk)  # W11b: an entry is an item id or {item, to?, overshoot?}
            if world.get("layout") != "ring" or roles.get(nid) != "item":
                probs.err(f"{w}: walk names {nid!r}, which is not an item node on a ring")
            to = wk.get("to") if isinstance(wk, dict) else None
            if to is not None and roles.get(to) != "owner":
                probs.err(f"{w}: walk of {nid!r} points to {to!r}, which is not an owner node on the ring")
        if "freeze" in st and world.get("layout") != "ring":
            probs.err(f"{w}: freeze needs layout 'ring'")
        for arc in st.get("arcs", []):
            if world.get("layout") != "ring":
                probs.err(f"{w}: arcs need layout 'ring'")
            elif positions and (arc["from"] >= positions or arc["to"] >= positions):
                probs.err(f"{w}: arc {arc['from']}..{arc['to']} is outside 0..{positions - 1}")
        for nid in st.get("set", {}):
            if nid not in nodes:
                probs.err(f"{w}: set names unknown node {nid!r}")
        cam = st.get("camera") or {}
        if "zoom" in cam and cam["zoom"] < 0.9:
            probs.warn(f"{w}: camera zoom {cam['zoom']} shrinks node text below 30 px; keep zoom >= 0.9")
        for xid in st.get("reveal", []) + st.get("focus", []) + st.get("focusEdges", []) + st.get("flow", []):
            first_seen[xid] = min(first_seen.get(xid, t), t)


def check_world_ids(world: dict, where: str, probs: Problems) -> None:
    nodes = {n["id"]: n for n in world["nodes"]}
    edges = {e["id"]: e for e in world["edges"]}
    if len(nodes) != len(world["nodes"]) or len(edges) != len(world["edges"]):
        probs.err(f"{where}: node or edge ids are not unique")
    if set(nodes) & set(edges):
        probs.err(f"{where}: ids used for both a node and an edge: {sorted(set(nodes) & set(edges))}")
    for e in world["edges"]:
        for end in ("from", "to"):
            if e[end] not in nodes:
                probs.err(f"{where} edge {e['id']}: {end} {e[end]!r} is not a node")


def default_reveals(world: dict, first_seen: dict, first_ms: int) -> None:
    nodes = {n["id"]: n for n in world["nodes"]}
    for n in world["nodes"]:
        n.setdefault("revealAtMs", first_seen.get(n["id"], first_ms))
    for e in world["edges"]:
        if "revealAtMs" not in e:
            ends = [nodes[e["from"]].get("revealAtMs", first_ms), nodes[e["to"]].get("revealAtMs", first_ms)] if e["from"] in nodes and e["to"] in nodes else [first_ms]
            e["revealAtMs"] = first_seen.get(e["id"], max(ends))
    for x in world["nodes"] + world["edges"]:
        x["revealAtMs"] = int(x["revealAtMs"])


def build_world(world: dict, scenes: list[dict], resolver: Resolver, probs: Problems) -> None:
    check_world_ids(world, "world", probs)
    place_ring(world, "world", probs)
    if (world.get("ring") or {}).get("ownershipAt"):
        ms = resolver.point(world["ring"]["ownershipAt"], "world ring.ownershipAt", probs)
        if ms is not None:
            world["ring"]["ownershipAtMs"] = ms
    W, H = world.get("width", 1728), world.get("height", 712)
    for n in world["nodes"]:
        if "x" in n and not (0 <= n["x"] <= W and 0 <= n["y"] <= H):
            probs.warn(f"world node {n['id']} at ({n['x']}, {n['y']}) is outside the world {W}x{H}")
        if "revealAt" in n:
            ms = resolver.point(n["revealAt"], f"world node {n['id']} revealAt", probs)
            if ms is not None:
                n["revealAtMs"] = ms
    for e in world["edges"]:
        if "revealAt" in e:
            ms = resolver.point(e["revealAt"], f"world edge {e['id']} revealAt", probs)
            if ms is not None:
                e["revealAtMs"] = ms

    first_world = None
    first_seen: dict[str, int] = {}
    for sc, where, steps in world_step_sources(scenes):
        first_world = sc["startMs"] if first_world is None else min(first_world, sc["startMs"])
        check_steps(world, steps, where, sc["startMs"], probs, first_seen)
    if first_world is None:
        return
    default_reveals(world, first_seen, first_world)


def check_compare(sc: dict, shared_world: dict | None, resolver: Resolver, probs: Problems) -> None:
    """Compare panels: a local world is built like the episode world (ids, ring places, reveals
    from the scene start); table marks and cells must fit the columns."""
    for side in ("left", "right"):
        panel = sc["props"].get(side) or {}
        where = f"scene {sc['id']} {side} panel"
        if panel.get("kind") == "world":
            w = panel.get("world")
            if w == "shared":
                if not shared_world:
                    probs.err(f"{where}: world 'shared' needs a top-level 'world' in scenes.json")
                continue
            if isinstance(w, dict):
                check_world_ids(w, where, probs)
                place_ring(w, where, probs)
                for x in w["nodes"] + w["edges"]:
                    if "revealAt" in x:
                        ms = resolver.point(x["revealAt"], f"{where} {x['id']} revealAt", probs)
                        if ms is not None:
                            x["revealAtMs"] = ms
                first_seen: dict[str, int] = {}
                check_steps(w, panel.get("steps", []), where, sc["startMs"], probs, first_seen)
                default_reveals(w, first_seen, sc["startMs"])
        elif panel.get("kind") == "table":
            cols = len(panel.get("columns", [])) or max((len(r["cells"]) for r in panel.get("rows", [])), default=0)
            ids = {r["id"] for r in panel.get("rows", [])}
            for r in panel.get("rows", []):
                # R03: every row has exactly one cell per column. The renderer draws the column indexes
                # only, so an extra cell would be dropped while coverage counted it; a short row leaves holes.
                if len(r["cells"]) != cols:
                    probs.err(f"{where} row {r['id']}: {len(r['cells'])} cells for {cols} columns; give every row "
                              f"exactly one cell per column")
            for i, st in enumerate(panel.get("steps", [])):
                for rid, cs in (st.get("fill") or {}).items():
                    if rid not in ids:
                        probs.err(f"{where} step {i}: fill names unknown row {rid!r}")
                    elif cs != "all" and any(c >= cols for c in cs):
                        probs.err(f"{where} step {i}: fill row {rid!r} has a column outside 0..{cols - 1}")
                for rid, cs in (st.get("marks") or {}).items():
                    if rid not in ids:
                        probs.err(f"{where} step {i}: marks names unknown row {rid!r}")
                    elif any(c >= cols for c in cs):
                        probs.err(f"{where} step {i}: marks row {rid!r} has a column outside 0..{cols - 1}")
    v = sc["props"].get("verdict")
    if v and "atMs" in v:
        stats = [st.get("atMs", sc["startMs"]) for side in ("left", "right")
                 for st in (sc["props"].get(side) or {}).get("steps", []) if "stat" in st]
        if not any(t <= v["atMs"] for t in stats):
            probs.warn(f"scene {sc['id']}: the verdict lands before any panel stat; show the evidence (a stat) first")


def check_route(world: dict, seg_order: list[str], probs: Problems) -> None:
    """Route recall (references/memory-palace.md): stations 1..n in order, known nodes,
    and station segments in script order."""
    route = world.get("route")
    if not route:
        return
    nodes = {n["id"] for n in world["nodes"]}
    nums = [r["station"] for r in route]
    if nums != list(range(1, len(route) + 1)):
        probs.err(f"world.route: stations must be numbered 1..{len(route)} in order, got {nums}")
    last = -1
    for r in route:
        for nid in r["nodes"]:
            if nid not in nodes:
                probs.err(f"world.route station {r['station']}: node {nid!r} is not in world.nodes")
        if r["segment"] not in seg_order:
            probs.err(f"world.route station {r['station']}: segment {r['segment']!r} is not in script.json")
            continue
        idx = seg_order.index(r["segment"])
        if idx < last:
            probs.err(
                f"world.route station {r['station']} ({r['segment']}) comes before an earlier station's segment "
                f"in script order; route order must follow segment order"
            )
        last = max(last, idx)


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    if isinstance(obj, dict):
        return [s for k, v in obj.items() if k not in ("component", "language", "svg", "viewBox") for s in _strings(v)]
    return []


def _key(s: str) -> str:
    k = re.sub(r"[^a-z0-9]", "", s.lower())
    return k[:-1] if k.endswith("s") and len(k) > 3 else k


def check_on_screen(turns, scenes, overlays, world, probs: Problems, auto: bool) -> None:
    """A term counts only when it is visible near its turn: world nodes after revealAtMs, step and
    cue items after their atMs, diagram elements after their reveal step (pe_common.visible_text)."""
    view = {"scenes": scenes, "overlays": overlays, "world": world}
    n = 0
    for t in turns:
        for term in t.get("onScreen", []):
            k = _key(term)
            hit = k in _key(pc.visible_text(view, t["startMs"] - 1500, t["endMs"] + 1500))
            if hit:
                continue
            if auto:
                n += 1
                want = [norm(w) for w in term.split() if norm(w)]
                words = t["words"]
                start = t["startMs"]
                for i in range(len(words) - len(want) + 1):
                    if [norm(w["text"]) for w in words[i:i + len(want)]] == want:
                        start = words[i]["startMs"]
                        break
                overlays.append({"id": f"auto{n:02d}", "type": "chip", "auto": True,
                                 "startMs": start, "endMs": max(start + 2500, t["endMs"]), "props": {"text": term[:32]}})
                probs.warn(f"turn {t['id']}: onScreen {term!r} had no visual event; added chip auto{n:02d}")
            else:
                probs.warn(
                    f"turn {t['id']}: onScreen {term!r} has no visual event near {t['startMs']}..{t['endMs']} ms. "
                    f"Add a chip overlay, a node label or a step, or rerun with --auto-chips."
                )


def write_atomic(path: Path, text: str) -> None:
    """Exclusive temporary file in the same folder, then rename (C02): a pre-existing
    'episode.json.tmp' symlink or file is never written through; a link at the target is refused."""
    pc.atomic_write(path, text)


def _copy_if_changed(src: Path, dst: Path) -> bool:
    if src.is_symlink() or dst.is_symlink():
        raise pc.BadId(f"refusing to copy through a symbolic link: {src if src.is_symlink() else dst}")
    if dst.is_file() and dst.stat().st_size == src.stat().st_size and dst.stat().st_mtime >= src.stat().st_mtime:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst, follow_symlinks=False)
    return True


def sync(ep: Path, remotion: Path, slug: str, episode: dict, probs: Problems) -> Path | None:
    if not (remotion / "package.json").is_file():
        probs.warn(f"no Remotion project at {remotion}; skipped sync. Copy templates/remotion/ there and npm install.")
        return None
    pub = pc.inside(remotion / "public" / "episodes", remotion / "public" / "episodes" / slug, "Remotion episode folder")
    pub.mkdir(parents=True, exist_ok=True)
    try:
        if episode["audio"]["src"]:
            _copy_if_changed(pc.safe_path(ep, ep / "audio" / "episode.wav", "episode.wav"), pc.safe_path(pub, pub / "episode.wav"))
        elif (pub / "episode.wav").exists() or (pub / "episode.wav").is_symlink():
            (pub / "episode.wav").unlink()  # placeholder build: do not play stale audio
        for d in ("diagrams", "img", "icons"):
            if (ep / d).is_dir() and not (ep / d).is_symlink():
                for root, _dirs, files in os.walk(ep / d, followlinks=False):
                    for name in files:
                        f = Path(root) / name
                        src = pc.safe_path(ep, f, "asset")
                        _copy_if_changed(src, pc.safe_path(pub, pub / d / f.relative_to(ep / d), "Remotion asset"))
        # episode.json last, so Remotion never reads a manifest whose assets are not there yet
        write_atomic(pc.safe_path(pub, pub / "episode.json", "Remotion episode.json"),
                     json.dumps(episode, indent=2, ensure_ascii=False) + "\n")
    except pc.BadId as e:
        probs.err(str(e))
        return None
    return pub


def report(probs: Problems, result) -> int:
    for i, w in enumerate(probs.warnings, 1):
        print(f"warning {i}: {w}", file=sys.stderr)
    if probs.errors:
        for i, e in enumerate(probs.errors, 1):
            print(f"error {i}: {e}", file=sys.stderr)
        print(f"build_manifest: {len(probs.errors)} error(s), nothing written", file=sys.stderr)
        return 1
    out, synced, ep = result
    print(f"wrote {out}")
    if synced:
        print(f"synced to {synced}")
    total = ep["audio"]["durationMs"] + ep["video"]["tailMs"]
    print(f"{len(ep['turns'])} turns, {len(ep['holds'])} holds, {len(ep['scenes'])} scenes, {len(ep['overlays'])} overlays, "
          f"{total / 1000:.2f} s = {-(-total * FPS // 1000)} frames at {FPS} fps, timing {ep['timingSource']}")
    for sc in ep["scenes"]:
        print(f"  {sc['id']:<6} {sc['type']:<9} {sc['startMs'] / 1000:7.2f} .. {sc['endMs'] / 1000:7.2f} s")
    if probs.warnings:
        print(f"{len(probs.warnings)} warning(s) above")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge script.json + scenes.json + timing.json into episode.json and sync to Remotion.")
    ap.add_argument("--workspace", default="explainers", help="workspace folder (default ./explainers)")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--remotion-dir", default=None, help="Remotion project (default <workspace>/remotion)")
    ap.add_argument("--placeholder-timing", action="store_true", help="no audio yet: estimate turn times from word counts")
    ap.add_argument("--auto-chips", action="store_true", help="add a keyword chip for every onScreen term with no visual event")
    ap.add_argument("--tail-ms", type=int, default=None, help="hold after the audio, clamped to 500..3000")
    ap.add_argument("--no-sync", action="store_true", help="write episode.json only, do not copy into Remotion")
    args = ap.parse_args()
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
