#!/usr/bin/env python3
"""Deterministic checks for podcast-explainer-video JSON files.

Usage:
  python3 scripts/validate_script.py <slug>/script.json --facts <slug>/facts.json --minutes 6 [--brief <slug>/brief.json]
  python3 scripts/validate_script.py <slug>/outline.json --facts <slug>/facts.json
  python3 scripts/validate_script.py <slug>/brief.json
  python3 scripts/validate_script.py <slug>/facts.json
  python3 scripts/validate_script.py <series-id>/series.json [--final]   (every part folder too;
                                                                  --final: all parts must exist)
  add --json for machine-readable output

A clean structure is necessary, not sufficient: these checks cannot prove the episode teaches.
The judge, the blind restater and, in the end, the learner's own self-test score decide that.

The file kind comes from --kind, else from the file name, else from its keys.
Exit codes: 0 = no errors (warnings allowed), 1 = at least one error, 2 = bad command line.
Uses the `jsonschema` package when it can be imported; otherwise a built-in checker for the
keyword subset that schemas/*.schema.json use. Standard library only otherwise.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SKILL_DIR / "schemas"

# Speech rate. Measured on gemini-3.8-flash-tts (Kore and Puck, 2 Nov 2026, references/gemini-tts.md
# section 13): 0.357 s per word, about 168 words per minute. Word budgets use the measured rate.
# 150 wpm (explainer-pedagogy S14) stays only as the planning default for a human writing an outline.
SECS_PER_WORD = 0.357
EXPERT_RUN_WORDS = 60   # W38: back-to-back expert turns over this many words (holds counted at SECS_PER_WORD)
WPM = 60 / SECS_PER_WORD  # about 168
PLANNING_WPM = 150
# 45 words is about 16 s at the measured rate. Pedagogy S5 caps an expert turn at about 20 s.
DEFAULT_MAX_TURN_WORDS = 45
# Total words more than 30% off the target is an error: Gemini pace varies by voice by roughly
# 10 to 20%, so a larger gap means the script, not the voice, is the wrong length.
TOTAL_BUDGET_ERROR = 0.30
TOTAL_BUDGET_WARN = 0.15
# Per segment only a warning, and loose: short segments (check, recap) swing a lot in relative terms.
SEGMENT_BUDGET_WARN = 0.60
# Words per section in the 6-minute template (explainer-pedagogy.md section 4). Used as weights
# to split the total word budget across segments by role. "hook" covers cold open plus roadmap.
# Every role in schemas/common.schema.json needs a weight (checked at start-up).
ROLE_WEIGHTS = {
    "hook": 100, "puzzle": 50, "roadmap": 50, "plain": 150, "terms": 60, "example": 190, "misconception": 150,
    "mechanism": 150, "analogy": 125, "transfer": 125, "compare": 125, "scale": 125, "recap": 75, "check": 40,
    "selftest": 75,
}
# Duplicate-claim heuristic: two segments sharing at least 3 content-word trigrams, covering at
# least 30% of the smaller segment's trigrams, probably make the same core point twice.
DUP_MIN_SHARED = 3
DUP_MIN_OVERLAP = 0.30
# Pedagogy S13: at most one backchannel per 4 turns.
BACKCHANNEL_EVERY = 4
# Pedagogy S1: at least one deep learner question per 30 to 45 s of expert speech. We use 45 s.
DEEP_QUESTION_EVERY_SEC = 45
# Gemini 3.8 inline event tags (gemini-podcast-flows.md section 3 rule 5; references/gemini-tts.md
# section 5). Others are spoken as text.
ALLOWED_TAGS = {
    "laugh", "chuckle", "sigh", "breath", "gasp", "cough", "throat-clearing", "short pause", "long pause",
    "tsk", "exhales", "whispers",
}
# Segment counts per depth (CONTRACT.md "Goal additions"): quick about 5, standard about 8, deep 10 to 16.
DEPTH_SEGMENTS = {"quick": (4, 6), "standard": (6, 10), "deep": (10, 16)}
SERIES_PART_SEGMENTS = (4, 8)  # references/depth.md section 5: each part has 4 to 8 segments
# A final check that also holds the recap (depth.md quick/standard templates) gets recap + check words.
FOLDED_CHECK_WEIGHT = 115
# A deep run is split into parts of at most 12 minutes each (CONTRACT.md "Goal additions").
MAX_PART_MINUTES = 12
MIN_MEASURED_RATIO = 0.8   # E21: measured durationMs is at least 0.8 x words x SECS_PER_WORD (codex round 4, E01)
# New terms per episode: the ONE statement is schemas/common.schema.json $defs.newTermLimits
# (quick 3, standard 5, deep 5 per part, 4 per segment), read here at start-up (A05).
_TERM_LIMITS = json.loads((SCHEMA_DIR / "common.schema.json").read_text())["$defs"]["newTermLimits"]["default"]
MAX_NEW_TERMS = {k: _TERM_LIMITS[k] for k in ("quick", "standard", "deep")}
MAX_TERMS_PER_SEGMENT = _TERM_LIMITS["perSegment"]
DEFAULT_DEPTH = "standard"
FIRST_ROLES = {"hook", "puzzle"}
LAST_ROLES = {"check", "selftest"}  # the episode ends with retrieval or with work handed to the learner
QUESTION_ROLES = {"check", "selftest"}
DUP_EXEMPT_ROLES = {"recap", "check", "selftest"}  # these repeat earlier claims on purpose
# learning-design.md L10: one retrieval pause every 5 to 6 minutes. Warn past 6 minutes without one.
MAX_SEC_WITHOUT_PAUSE = 360
# learning-design.md L11: a hold is 6 to 8 s; an explain-back hold (several sentences aloud) may run to 15 s.
HOLD_RANGE_MS = (6000, 8000)
EXPLAIN_BACK_HOLD_RANGE_MS = (6000, 15000)
MIN_PAUSE_HOLD_MS = 3000
# Rough gaps tts.py adds between turns (gapMs 250) for the time estimate.
TURN_GAP_SEC = 0.25

STOPWORDS = set("""
a about after again all also am an and any are as at be because been before being but by can
could did do does doing don't down each even every few for from get gets got had has have having
he her here hers him his how i i'm if in into is isn't it it's its itself just let like me more
most my no nor not now of off on once one only or other our out over own really right same say
she should so some still such than that that's the their them then there these they this those
through to too two under until up us very was we well were what when where which while who why
will with would yeah yes you your you're okay oh uh um so
""".split())

NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?!\w)")
MULTIPLIER_RE = re.compile(r"\b(hundred|thousand|million|billion|trillion)s?\b", re.I)
SPELLED_RE = re.compile(
    r"\b(eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety)\b", re.I)
TAG_RE = re.compile(r"<([^<>]*)>")
PREFIX_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 .'-]{0,24}):\s")
GENERIC_PREFIX_RE = re.compile(r"^(host|guest|speaker|narrator|expert|learner|interviewer|presenter)(\s*[0-9A-Za-z])?$", re.I)
PIPE_RE = re.compile(r"\|([^|]*)\|")
DEEP_Q_RE = re.compile(
    r"\b(why|how|what if|what happens|what stops|what makes|what decides|what about|"
    r"wouldn't|doesn't|isn't|couldn't|can't|won't|so then)\b", re.I)
PRAISE_RE = re.compile(
    r"\b(great (question|point|explanation)|good (question|point)|well put|brilliant|"
    r"love that|you explain(ed)? (it|that) (so )?well|that's (amazing|fascinating|genius))\b", re.I)
TAUTOLOGY_RE = re.compile(r"([^.?!]{3,}?)\bbecause\b([^.?!]{2,})", re.I)
# Teaching checks (D03 and the 2 Nov 2026 real-run findings, references/script.md section 10).
CAUSAL_RE = re.compile(r"\b(because|so|therefore|thus|hence|which means|that means|means that|as a result|"
                       r"leads? to|causes?|caused|makes?|forces?|if|once|when|whenever|until|that's why|this is why|"
                       r"which is why|only)\b", re.I)
EXAMPLE_RE = re.compile(r"\b(for example|for instance|say|imagine|suppose|picture|like a|like the)\b", re.I)
DEFINE_RE = re.compile(r"\b(means?|meaning|is called|are called|we call|it's called|that's called|is just|are just|"
                       r"is simply|in plain (words|terms|english)|think of it as|stands for|in other words|that's (a|an|the)|"
                       r"that is,|which is (a|an|the)|is a (kind|way|place|list|rule|number|function|map)|divided by|"
                       r"is when|is where|is what|is the name|a name|the name|what's it called|what do you call)\b", re.I)
# The word group is case-insensitive ("In general" opens a sentence); the variable groups need capitals (K over N).
GENERAL_RE = re.compile(r"(?i:\b(in general|generally|on average|as a rule|the general rule|in any|for any|for every|"
                        r"no matter|regardless|whatever the)\b)|"
                        r"\b(\d+|one|[a-z])\s*(over|in|out of|divided by|/)\s*[A-Z]\b|"
                        r"\b[A-Z]\s*(over|divided by|/|plus|minus|times)\s*([A-Z]|\d+)\b|\bmod [A-Z]\b")
# D03 (codex round 3): connectives that state a cause or a consequence. A mechanism segment needs at
# least two DISTINCT ones across its turns (E41); "so" alone is the lazy-lesson pattern.
CONNECTIVE_RE = re.compile(r"\b(because|so that|so|therefore|thus|hence|which means|that means|means that|as a result|"
                           r"leads? to|causes?|caused|forces?|that's why|this is why|which is why|if|then|unless|"
                           r"otherwise|whenever|until)\b", re.I)
_CONNECTIVE_CANON = {"cause": "causes", "caused": "causes", "lead to": "leads to", "force": "forces"}
# A refutation names the wrong belief and says it fails (E44).
REFUTE_RE = re.compile(r"\b(no|not|never|isn't|aren't|doesn't|don't|didn't|won't|can't|cannot|wasn't|wrong|false|"
                       r"actually|mistake|myth|fails?|breaks?|instead)\b|n't\b", re.I)
SPECIFIC_ROLES = {"example", "mechanism", "scale", "compare"}
CIRCULAR_ROLES = {"mechanism", "misconception"}
BACKCHANNEL_START_RE = re.compile(
    r"^\s*(exactly|absolutely|definitely|totally|right|mhm|mm-hmm|yeah|wow|great|true)\b[\s,.!]*", re.I)

SCHEMA_ANNOTATIONS = {"$schema", "$id", "title", "description", "default", "examples", "$defs", "$comment"}
SCHEMA_SUPPORTED = SCHEMA_ANNOTATIONS | {
    "type", "properties", "required", "additionalProperties", "enum", "const", "pattern", "minLength",
    "maxLength", "minimum", "maximum", "minItems", "maxItems", "items", "uniqueItems", "$ref", "allOf",
    "if", "then",
}


# ---------------------------------------------------------------- problems

class Report:
    def __init__(self, file: str):
        self.file = file
        self.items: list[dict] = []
        self.budget: dict | None = None
        self.length: dict | None = None

    def add(self, level: str, code: str, msg: str, segment: str | None = None, turn: str | None = None):
        self.items.append({"level": level, "code": code, "segment": segment, "turn": turn, "message": msg})

    def error(self, code, msg, segment=None, turn=None):
        self.add("error", code, msg, segment, turn)

    def warn(self, code, msg, segment=None, turn=None):
        self.add("warning", code, msg, segment, turn)

    @property
    def errors(self):
        return [p for p in self.items if p["level"] == "error"]

    @property
    def warnings(self):
        return [p for p in self.items if p["level"] == "warning"]


# ---------------------------------------------------------------- schema

def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref {ref!r} (only local #/ refs)")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _type_ok(value, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "null":
        return value is None
    raise ValueError(f"unsupported type {t!r}")


def _fmt_path(path: list) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "(root)"


def mini_validate(value, schema: dict, root: dict, path: list) -> list[str]:
    """Checks the JSON Schema keyword subset in SCHEMA_SUPPORTED. Returns error strings."""
    unknown = set(schema) - SCHEMA_SUPPORTED
    if unknown:
        raise ValueError(f"schema keyword(s) {sorted(unknown)} at {_fmt_path(path)} not supported by the built-in checker")
    errs: list[str] = []
    where = _fmt_path(path)
    if "$ref" in schema:
        errs += mini_validate(value, _resolve(schema["$ref"], root), root, path)
    for sub in schema.get("allOf", []):
        errs += mini_validate(value, sub, root, path)
    if "if" in schema:
        if not mini_validate(value, schema["if"], root, path) and "then" in schema:
            errs += mini_validate(value, schema["then"], root, path)
    if "const" in schema and value != schema["const"]:
        errs.append(f"{where}: must be {json.dumps(schema['const'])}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {json.dumps(value)} is not one of {schema['enum']}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            errs.append(f"{where}: expected {'/'.join(types)}, got {type(value).__name__}")
            return errs
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{where}: missing required field '{key}'")
        for key, sub in value.items():
            if key in props:
                errs += mini_validate(sub, props[key], root, path + [key])
            elif schema.get("additionalProperties") is False:
                errs.append(f"{where}: unknown field '{key}' (allowed: {', '.join(props)})")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{where}: needs at least {schema['minItems']} items, has {len(value)}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{where}: allows at most {schema['maxItems']} items, has {len(value)}")
        if schema.get("uniqueItems"):
            seen = [json.dumps(v, sort_keys=True) for v in value]
            if len(seen) != len(set(seen)):
                errs.append(f"{where}: items must be unique")
        if "items" in schema:
            for i, item in enumerate(value):
                errs += mini_validate(item, schema["items"], root, path + [i])
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{where}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{where}: longer than {schema['maxLength']} characters ({len(value)})")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{where}: {json.dumps(value)} does not match {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{where}: {value} is below the minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{where}: {value} is above the maximum {schema['maximum']}")
    return errs


def _inline_refs(node, base: str):
    """Replace refs into another schema file ("common.schema.json#/$defs/role") with the target,
    so both jsonschema and the built-in checker see one self-contained schema."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            fname, _, pointer = ref.partition("#")
            other = json.loads((SCHEMA_DIR / fname).read_text())
            target = _resolve("#" + pointer, other) if pointer else other
            merged = {k: v for k, v in node.items() if k != "$ref"}
            merged.update(_inline_refs(target, fname))
            return merged
        return {k: _inline_refs(v, base) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_refs(v, base) for v in node]
    return node


def load_schema(schema_name: str) -> dict:
    return _inline_refs(json.loads((SCHEMA_DIR / schema_name).read_text()), schema_name)


def segment_roles() -> list[str]:
    """The one role enum, from schemas/common.schema.json."""
    return json.loads((SCHEMA_DIR / "common.schema.json").read_text())["$defs"]["role"]["enum"]


def schema_errors(data, schema_name: str) -> tuple[list[str], str]:
    schema = load_schema(schema_name)
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return mini_validate(data, schema, schema, []), "built-in"
    validator = jsonschema.Draft202012Validator(schema)
    errs = []
    for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        errs.append(f"{_fmt_path(list(e.absolute_path))}: {e.message}")
    return errs, "jsonschema"


# ---------------------------------------------------------------- text helpers

def spoken_text(text: str) -> str:
    """Text the listener hears from the speaking host: tags and |backchannels| removed."""
    return re.sub(r"\s+", " ", PIPE_RE.sub(" ", TAG_RE.sub(" ", text))).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:['.,-][A-Za-z0-9]+)*", spoken_text(text)))


def norm(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9.']+", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    t = t.replace("'", "")
    return " " + re.sub(r"\s+", " ", t).strip() + " "


def number_tokens(text: str) -> list[str]:
    t = spoken_text(text)
    toks = [m.group(0).replace(",", "") for m in NUMBER_RE.finditer(t)]
    toks += [m.group(1).lower() for m in MULTIPLIER_RE.finditer(t)]
    return toks


def content_trigrams(text: str) -> set[tuple[str, str, str]]:
    words = [w for w in norm(text).split() if w not in STOPWORDS and len(w) > 2]
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def term_in(term: str, haystack_norm: str) -> bool:
    t = norm(term).strip()
    if not t:
        return True
    variants = {t, t + "s", t + "es"}
    if t.endswith("s"):
        variants.add(t[:-1])
    if t.endswith("es"):
        variants.add(t[:-2])
    return any(f" {v} " in haystack_norm for v in variants)


# ---------------------------------------------------------------- facts

def load_facts(path: Path, rep: Report) -> dict | None:
    try:
        facts = json.loads(path.read_text())
    except FileNotFoundError:
        rep.error("E00", f"facts file not found: {path}")
        return None
    except json.JSONDecodeError as e:
        rep.error("E00", f"{path}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}")
        return None
    errs, _ = schema_errors(facts, "facts.schema.json")
    for e in errs:
        rep.error("E01", f"facts.json {e}")
    check_facts_refs(facts, rep)
    return facts


def check_facts_refs(facts: dict, rep: Report):
    if not isinstance(facts, dict):
        return
    source_ids = {s.get("id") for s in facts.get("sources", []) if isinstance(s, dict)}
    fact_list = [f for f in facts.get("facts", []) if isinstance(f, dict)]
    ids = [f.get("id") for f in fact_list]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        rep.error("E03", f"facts.json: duplicate fact id {dup}")
    id_set = set(ids)
    for f in fact_list:
        fid = f.get("id")
        if f.get("sourceId") and f["sourceId"] not in source_ids:
            rep.error("E10", f"facts.json {fid}: sourceId {f['sourceId']} is not in sources[]")
        for d in f.get("derivedFrom", []) or []:
            if d not in id_set:
                rep.error("E10", f"facts.json {fid}: derivedFrom {d} is not a fact id")
            if d == fid:
                rep.error("E10", f"facts.json {fid}: derives from itself")
        if f.get("kind") == "sourced" and f.get("sourceId") in source_ids:
            src = next(s for s in facts["sources"] if s.get("id") == f["sourceId"])
            if not src.get("url") and not src.get("path"):
                rep.error("E10", f"facts.json source {src.get('id')}: needs url or path")


def fact_number_index(facts: dict | None) -> dict[str, set[str]]:
    """fact id -> set of number tokens it covers."""
    out: dict[str, set[str]] = {}
    if not facts:
        return out
    for f in facts.get("facts", []):
        if isinstance(f, dict) and "id" in f:
            toks: set[str] = set()
            for n in f.get("numbers", []) or []:
                if isinstance(n, str):
                    toks.update(number_tokens(n))
            out[f["id"]] = toks
    return out


# ---------------------------------------------------------------- structure (shared by outline and script)

def check_structure(data: dict, segments: list[dict], minutes: float | None, rep: Report):
    roles = [s.get("role") for s in segments]
    if not roles:
        return
    depth = data.get("depth")
    series = data.get("series") if isinstance(data.get("series"), dict) else None
    part = series.get("part", 1) if series else 1
    first_ok = FIRST_ROLES | ({"recap"} if part > 1 else set())
    if roles[0] not in first_ok:
        rep.error("E13", f"first segment role is '{roles[0]}'; it must be {' or '.join(sorted(first_ok))} (open on a puzzle, pedagogy S2/S9)",
                  segments[0].get("id"))
    if part > 1 and roles[0] == "recap" and (len(roles) < 2 or roles[1] not in FIRST_ROLES | {"example", "mechanism"}):
        rep.warn("W13", "a later part opens with a recap; the next segment should be a hook, puzzle, worked example or mechanism", segments[0].get("id"))
    # The episode ends with a recap, then a check or a selftest (pedagogy S3, S12; learning-design
    # L16). The skeletons may fold the recap into the final segment; that is allowed when it holds a
    # learner explain-back turn (script) or names the recap in its learningGoal or title (outline).
    last = segments[-1]
    if roles[-1] not in LAST_ROLES:
        rep.error("E13", f"last segment role is '{roles[-1]}'; it must be 'check' or 'selftest' (retrieval or work for the learner, pedagogy S12, L16)", last.get("id"))
    elif len(roles) < 2 or roles[-2] != "recap":
        turns = [t for t in last.get("turns", []) or [] if isinstance(t, dict)]
        if turns:
            learner_ids = {s.get("id") for s in data.get("speakers", []) if isinstance(s, dict) and s.get("role") == "learner"}
            folded = any((t.get("kind") == "explain-back" or (t.get("pause") or {}).get("kind") == "explain-back")
                         and t.get("speaker") in learner_ids for t in turns)
        else:  # W16 (W14b D07): the deep skeleton rows say "M7" / "explain-back", not "recap"
            folded = re.search(r"recap|explain(s|ing)?[- ]back|say it back|in (his|her|their) own words|\bm7\b",
                               (last.get("learningGoal", "") + " " + last.get("title", "")).lower()) is not None
        if not folded:
            rep.error("E13", f"no 'recap' segment before the final '{roles[-1]}', and that segment has no learner recap "
                      "(a learner turn with kind 'explain-back' in a script, or 'recap' in the outline learningGoal)", last.get("id"))
    if "misconception" not in roles:
        if series and part > 1:
            rep.warn("W13", "this part has no misconception segment; make sure another part of the series has one")
        else:
            rep.error("E13", "no segment has role 'misconception'; the misconception beat is required (pedagogy Finding 2)")
    if depth in DEPTH_SEGMENTS:
        lo, hi = SERIES_PART_SEGMENTS if series else DEPTH_SEGMENTS[depth]
        if not lo <= len(segments) <= hi:
            rep.warn("W21", f"{len(segments)} segments for depth '{depth}'; expected {lo} to {hi}")
    n_checks = sum(1 for r in roles if r in QUESTION_ROLES)
    # W16 (W14b D06): a series part follows the deep skeleton (one selftest per part); the series check
    # (validate_script.py series.json, E21) counts retrieval checks over the whole series.
    if depth == "deep" and n_checks < 2 and not series:
        rep.error("E21", f"deep run has {n_checks} check or selftest segment(s); it needs at least 2 retrieval checks")
    if series and minutes and minutes > MAX_PART_MINUTES:
        rep.error("E21", f"part of a series targets {minutes:g} min; a part is at most {MAX_PART_MINUTES} min, split it")
    elif depth == "deep" and not series and minutes and minutes > MAX_PART_MINUTES:
        rep.warn("W21", f"deep run of {minutes:g} min in one script; split into parts of at most {MAX_PART_MINUTES} min (set series)")
    seg_ids = [s.get("id") for s in segments]
    for dup in sorted({i for i in seg_ids if seg_ids.count(i) > 1}):
        rep.error("E03", f"duplicate segment id {dup}", dup)
    if seg_ids != sorted(seg_ids):
        rep.warn("W03", f"segment ids are not in ascending order: {seg_ids}")


# ---------------------------------------------------------------- outline

def check_outline(data: dict, facts: dict | None, rep: Report):
    segments = [s for s in data.get("segments", []) if isinstance(s, dict)]
    check_structure(data, segments, data.get("targetMinutes"), rep)
    fact_ids = set(fact_number_index(facts)) if facts else None
    owner: dict[str, str] = {}
    terms = 0
    for s in segments:
        for fid in s.get("ownedFactIds", []) or []:
            if fact_ids is not None and fid not in fact_ids:
                rep.error("E09", f"ownedFactIds {fid} is not in facts.json", s.get("id"))
            if fid in owner and s.get("role") not in DUP_EXEMPT_ROLES:
                rep.error("E19", f"fact {fid} is already the core of {owner[fid]}; one fact, one home", s.get("id"))
            owner.setdefault(fid, s.get("id"))
        terms += len(s.get("newTerms", []) or [])
    core = [s.get("id") for s in segments if s.get("coreSegment") is True]
    if len(core) > 1:
        rep.error("E36", f"{len(core)} segments set coreSegment ({', '.join(core)}); tag the ONE segment that holds the core mechanism step")
    elif not core and (data.get("depth") or DEFAULT_DEPTH) != "quick":
        rep.warn("W36", "no segment sets coreSegment: true; tag the one segment with the core mechanism step so the validator "
                 "checks that the learner gets a hold before its answer (E35)")
    depth = data.get("depth") or DEFAULT_DEPTH
    cap = MAX_NEW_TERMS.get(depth)
    if depth == "deep" and not isinstance(data.get("series"), dict):
        cap = None  # an unsplit deep outline is warned about by W21; the cap applies per part
    if cap is not None and terms > cap:
        rep.warn("W20", f"{terms} new terms across the outline; at most {cap} for depth {depth}"
                 f"{' (per part)' if depth == 'deep' else ''} (pedagogy S7, references/depth.md)")
    minutes = data.get("targetMinutes")
    secs = [s.get("targetSec") for s in segments if isinstance(s.get("targetSec"), (int, float))]
    if minutes and len(secs) == len(segments):
        total = sum(secs)
        if abs(total - minutes * 60) > minutes * 60 * TOTAL_BUDGET_WARN:
            rep.warn("W06", f"segment targetSec sum is {total:.0f} s but targetMinutes is {minutes} ({minutes * 60:.0f} s)")
    hooks = [s for s in segments if s.get("role") in FIRST_ROLES]
    if hooks and data.get("learningObjective"):
        if not shares_content(hooks[0].get("keyQuestion", ""), data["learningObjective"]):
            rep.warn("W25", "the cold-open keyQuestion shares no content word with learningObjective; the prequestion "
                     "must target the core idea (learning-design L1)", hooks[0].get("id"))
    if facts is None:
        rep.warn("W09", "no --facts given: ownedFactIds were not checked")


# ---------------------------------------------------------------- script

def content_words(text: str) -> set[str]:
    out = set()
    for w in norm(text).split():
        if w in STOPWORDS or len(w) < 4:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def shares_content(a: str, b: str) -> bool:
    return bool(content_words(a) & content_words(b))


def turn_secs(t: dict) -> float:
    """Estimated spoken time of a turn at the measured rate, plus tags, gap and hold."""
    text = t.get("text", "") if isinstance(t.get("text"), str) else ""
    secs = word_count(text) * SECS_PER_WORD + TURN_GAP_SEC
    for tag in TAG_RE.findall(text):
        tag = tag.strip().lower()
        secs += 2.3 if tag == "long pause" else 0.5 if tag == "short pause" else 0.0
    hold = t.get("holdAfterMs")
    if isinstance(hold, int) and not isinstance(hold, bool):
        secs += hold / 1000
    return secs


def check_pauses(data: dict, segments: list[dict], spk_role: dict, brief: dict | None, rep: Report):
    """Pause-and-think holds (learning-design L1, L7, L10, L11)."""
    run_sec = 0.0
    warned_at = None
    for seg in segments:
        for t in seg.get("turns", []) or []:
            if not isinstance(t, dict):
                continue
            sid, tid = seg.get("id"), t.get("id")
            hold = t.get("holdAfterMs", 0) or 0
            pause = t.get("pause") if isinstance(t.get("pause"), dict) else None
            if pause and hold < MIN_PAUSE_HOLD_MS:
                rep.error("E22", f"turn has pause '{pause.get('kind')}' but holdAfterMs is {hold}; set holdAfterMs 6000 to 8000 "
                          "so the learner has time to think (learning-design L11)", sid, tid)
            elif pause and not (rng := EXPLAIN_BACK_HOLD_RANGE_MS if pause.get("kind") == "explain-back" else HOLD_RANGE_MS)[0] <= hold <= rng[1]:
                rep.warn("W22", f"{pause.get('kind')} pause hold of {hold} ms; use {rng[0]} to {rng[1]} ms (learning-design L11)", sid, tid)
            elif hold and not pause:
                rep.warn("W22", f"holdAfterMs {hold} without a pause cue: the video shows silence with no prompt; add "
                         "pause {kind, prompt} or drop the hold", sid, tid)
            if pause and "?" not in t.get("text", "") and pause.get("kind") != "explain-back":
                rep.warn("W22", "a pause turn should end on the question the learner thinks about", sid, tid)
            run_sec += turn_secs(t)
            if pause and hold >= MIN_PAUSE_HOLD_MS:
                run_sec = 0.0
                warned_at = None
            elif run_sec > MAX_SEC_WITHOUT_PAUSE and warned_at is None:
                warned_at = tid
                rep.warn("W23", f"about {run_sec / 60:.1f} min of episode since the start or the last pause; add a retrieval "
                         "pause (a turn with pause and holdAfterMs) every 5 to 6 minutes (learning-design L10)", sid, tid)
    # Cold open: the prequestion must exist and target the core idea.
    if segments and segments[0].get("role") in FIRST_ROLES:
        hook = segments[0]
        preds = [t for t in hook.get("turns", []) if isinstance(t, dict) and isinstance(t.get("pause"), dict)
                 and t["pause"].get("kind") == "predict"]
        if not preds:
            rep.error("E25", "the cold open has no prediction pause (a turn with pause kind 'predict' and holdAfterMs); "
                      "ask the learner to predict before the explanation (learning-design L1, L2)", hook.get("id"))
        elif data.get("learningObjective"):
            p = preds[0]
            if not shares_content(p["pause"].get("prompt", "") + " " + p.get("text", ""), data["learningObjective"]):
                rep.warn("W25", "the cold-open prequestion shares no content word with learningObjective; it must target "
                         "the core idea, not a side fact (learning-design L1)", hook.get("id"), p.get("id"))
    # At least one retrieval (or explain-back) pause after the cold open (L10).
    later = [t for s in segments[1:] for t in s.get("turns", []) if isinstance(t, dict) and isinstance(t.get("pause"), dict)
             and t["pause"].get("kind") in ("retrieve", "explain-back") and (t.get("holdAfterMs") or 0) >= MIN_PAUSE_HOLD_MS]
    if len(segments) > 1 and not later:
        rep.error("E23", "no retrieval or explain-back pause after the cold open; add a turn with pause kind 'retrieve' "
                  "and holdAfterMs 6000 to 8000 (learning-design L10)")
    # Prior knowledge (L7).
    level = (brief or {}).get("learnerLevel")
    roles = [s.get("role") for s in segments]
    if level == "near-expert" and "plain" in roles:
        rep.warn("W24", "brief.learnerLevel is near-expert but the script has a 'plain' segment; skip the plain pass and "
                 "give the time to the misconception and a second pause (learning-design L7)",
                 segments[roles.index("plain")].get("id"))
    if level == "novice" and "plain" not in roles and "example" not in roles:
        rep.warn("W24", "brief.learnerLevel is novice but there is no 'plain' or 'example' segment; give the plain "
                 "meaning before any term (learning-design L3, L7)")


def circular(text: str) -> bool:
    """'X because X': the because-clause adds no content word that the claim did not have."""
    for m in TAUTOLOGY_RE.finditer(spoken_text(text)):
        before, after = content_words(m.group(1)), content_words(m.group(2))
        if not after or after <= before:
            return True
    return False


def concrete(text: str) -> bool:
    """A number (digits or number words), a proper name, or an example marker."""
    sp = spoken_text(text)
    if any(any(c.isdigit() for c in w) for w in pc.fidelity_tokens(sp)):
        return True
    if EXAMPLE_RE.search(sp):
        return True
    for sent in re.split(r"(?<=[.?!])\s+", sp):
        words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", sent)
        if any(w[0].isupper() and w != "I" and not w.startswith("I'") for w in words[1:]):
            return True
    return False


def named_case(text: str) -> bool:
    """A proper name or a single-letter label (server A, key k7) inside a sentence, not at its start."""
    sp = spoken_text(text)
    for sent in re.split(r"(?<=[.?!])\s+", sp):
        words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", sent)
        if any((w[0].isupper() and w != "I" and not w.startswith("I'")) for w in words[1:]):
            return True
    return False


def digit_tokens(text: str) -> set[str]:
    return {w for w in pc.fidelity_tokens(spoken_text(text)) if any(c.isdigit() for c in w)}


GENERIC_WORDS = set("""mechanism process step steps thing things happen happens happened result results follow follows
example examples belief beliefs correct wrong right idea ideas work works worked part parts point means mean kind case cases
something someone people person really actually basically simply just question answer""".split())
RULE_RE = re.compile(r"\b(always|never|only|every time|guaranteed|must)\b", re.I)
ABSOLUTE_RE = re.compile(r"\b(always|never)\b", re.I)
SCOPE_RE = re.compile(r"\b(with|in (?:that|this|the|a|our|one)|when|whenever|if|unless|for (?:a|an|the|any|every|each)|under|"
                      r"as long as|per|on (?:a|the|this|that)|within|without|given)\b", re.I)
FACT_ROLES = {"mechanism", "example", "misconception"}
# W14a: W49 is about a GENERAL rule stated without scope. Three sentence kinds carry their scope in
# themselves and do not count: a question ("Is that luck, or always like that?"), a sentence about a
# named case on screen ("It never gets as far as D", "key 4 never moves"), and a determinism
# statement conditioned on equal input ("the same name always gives the same number").
_SENT_RE = re.compile(r"[^.?!]+[.?!]*")
_NAMED_CASE_RE = re.compile(r"(?<![\w'])(?:[B-HJ-Z]|(?<=\s)A)(?![\w'])|\b(?:key|job|server|robot|item|node|bucket)s? \d+\b")
_SAME_RE = re.compile(r"\bsame\b[^.?!]*\b(?:always|never)\b[^.?!]*\bsame\b", re.I)


def unscoped_absolute(text: str):
    """The first always/never in a sentence that is not a question, not about a named case and not
    a same-input determinism statement (W49), else None."""
    for sent in _SENT_RE.findall(text):
        m = ABSOLUTE_RE.search(sent)
        if not m or sent.rstrip().endswith("?") or _NAMED_CASE_RE.search(sent) or _SAME_RE.search(sent):
            continue
        return m
    return None


def _fact_texts(facts: dict | None) -> list[str]:
    out = []
    if isinstance(facts, dict):
        out.append(str(facts.get("concept") or ""))
        for f in facts.get("facts", []) or []:
            if isinstance(f, dict):
                out += [str(f.get("claim") or ""), str(f.get("quote") or ""), " ".join(map(str, f.get("numbers") or []))]
        for m in facts.get("misconceptions", []) or []:
            if isinstance(m, dict):
                out += [str(m.get("statement") or ""), str(m.get("correction") or "")]
    return out


def _outline_texts(outline: dict | None) -> list[str]:
    out = []
    if isinstance(outline, dict):
        for k in ("title", "learningObjective", "conceptAngle", "arc"):
            out.append(str(outline.get(k) or ""))
        mc = outline.get("misconception")
        if isinstance(mc, dict):
            out += [str(mc.get("statement") or ""), str(mc.get("correction") or "")]
        for sg in outline.get("segments", []) or []:
            if isinstance(sg, dict):
                out += [str(sg.get(k) or "") for k in ("title", "learningGoal", "keyQuestion", "visualPlan")]
                out += [str(x) for x in sg.get("newTerms", []) or []]
    return out


def domain_vocab(facts: dict | None, outline: dict | None) -> tuple[set[str], list[str]]:
    """(content words, multi-word newTerms) of the concept's domain: outline newTerms and the words
    of facts.json claims, quotes, misconceptions and concept; generic teaching words are left out."""
    words = set()
    for x in _fact_texts(facts):
        words |= content_words(x)
    phrases = []
    for sg in (outline or {}).get("segments", []) or []:
        for term in (sg.get("newTerms", []) or []) if isinstance(sg, dict) else []:
            words |= content_words(str(term))
            if len(str(term).split()) > 1:
                phrases.append(norm(str(term)))
    return words - GENERIC_WORDS, phrases


def domain_terms_in(text: str, vocab: set[str], phrases: list[str]) -> set[str]:
    found = content_words(text) & vocab
    tn = norm(text)
    found |= {p for p in phrases if p and f" {p} " in f" {tn} "}
    return found


def trace_text(facts: dict | None, outline: dict | None) -> str:
    """facts.json and outline.json text, normalised, for tracing a worked example's numbers and names."""
    return " " + " ".join(norm(x) for x in _fact_texts(facts) + _outline_texts(outline) if x) + " "


def case_traced(text: str, traced: str) -> bool:
    """One of the turn's digit tokens or proper names (not at sentence start) occurs in `traced`."""
    sp = spoken_text(text)
    nums = {n for n in digit_tokens(text)} | set(number_tokens(sp))
    if any(f" {norm(n)} " in traced for n in nums if norm(n)):
        return True
    for sent in re.split(r"(?<=[.?!])\s+", sp):
        words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", sent)
        for w in words[1:]:
            if w[0].isupper() and w != "I" and not w.startswith("I'") and f" {norm(w)} " in traced:
                return True
    return False


def misconception_statements(facts: dict | None, outline: dict | None) -> list[str]:
    mc = (outline or {}).get("misconception")
    if isinstance(mc, dict) and mc.get("statement"):
        return [str(mc["statement"])]
    return [str(m.get("statement")) for m in (facts or {}).get("misconceptions", []) or [] if isinstance(m, dict) and m.get("statement")]


def check_teaching(data: dict, segments: list[dict], spk_role: dict, outline: dict | None, rep: Report,
                   facts: dict | None = None):
    """Hard checks that a hollow lesson cannot pass (D03) and the checks from the 2 Nov 2026 real
    run: on-screen-only numbers, a worked case with no general rule, an answer with no thinking
    time in the core step, and the explain-back order. references/script.md section 10."""
    oseg = {s.get("id"): s for s in (outline or {}).get("segments", []) if isinstance(s, dict)}
    flat = [(seg, t) for seg in segments for t in seg.get("turns", []) or [] if isinstance(t, dict)]
    learner = lambda t: spk_role.get(t.get("speaker")) == "learner"
    expert = lambda t: spk_role.get(t.get("speaker")) == "expert"
    hold_of = lambda t: isinstance(t.get("pause"), dict) and (t.get("holdAfterMs") or 0) >= MIN_PAUSE_HOLD_MS

    # E28: a mechanism segment needs one turn with a cause AND something concrete.
    for seg in segments:
        if seg.get("role") != "mechanism":
            continue
        turns = [t for t in seg.get("turns", []) if isinstance(t, dict)]
        if not any(CAUSAL_RE.search(spoken_text(t.get("text", ""))) and concrete(t.get("text", "")) and not circular(t.get("text", ""))
                   for t in turns):
            rep.error("E28", "mechanism segment has no turn that gives a cause (because, so, which means, if ...) together with "
                      "a concrete number, name or example; state the causal step on a worked case", seg.get("id"))

    # E41 to E44 (D03, codex round 3): a lesson that only has the shape of teaching. Errors only in
    # mechanism and misconception segments; the judge and the restater still decide whether it teaches.
    for seg in segments:
        role = seg.get("role")
        turns = [t for t in seg.get("turns", []) if isinstance(t, dict)]
        if not turns or role not in CIRCULAR_ROLES:
            continue
        sid = seg.get("id")
        if role == "mechanism":
            found = set()
            for t in turns:
                for m in CONNECTIVE_RE.finditer(spoken_text(t.get("text", ""))):
                    w = re.sub(r"\s+", " ", m.group(1).lower())
                    found.add(_CONNECTIVE_CANON.get(w, w))
            if len(found) < 2:
                rep.error("E41", f"mechanism segment uses {len(found)} distinct causal connective(s) ({', '.join(sorted(found)) or 'none'}); "
                          "a mechanism chains at least two steps: say why (because ...) and what follows (so ..., which means ..., "
                          "if ... then ...)", sid)
            if not any(DEFINE_RE.search(spoken_text(t.get("text", ""))) and not circular(t.get("text", "")) for t in turns):
                rep.error("E42", "mechanism segment has no turn that defines its key term in plain words (means, is called, "
                          "think of it as ...)", sid)
            if not any(digit_tokens(t.get("text", "")) or (concrete(t.get("text", "")) and named_case(t.get("text", ""))) for t in turns):
                rep.error("E43", "mechanism segment has no worked example with a number or a named case (a specific "
                          "server, key, person or object); work the step on one case", sid)
        else:
            beliefs = [(i, t) for i, t in enumerate(turns) if learner(t)]
            ok = False
            for i, t in enumerate(turns):
                if not REFUTE_RE.search(spoken_text(t.get("text", ""))):
                    continue
                cw = content_words(spoken_text(t.get("text", "")))
                for j, b in beliefs:
                    if j >= i:
                        continue
                    bw = content_words(spoken_text(b.get("text", "")))
                    need = 1 if len(bw) <= 3 else 2
                    if len(cw & bw) >= need:
                        ok = True
                        break
                if ok:
                    break
            if not ok:
                rep.error("E44", "misconception segment has no turn that refutes the learner's wrong belief: after the learner "
                          "states it, a later turn (the expert, or the learner who sees it fail) must name it (repeat its key "
                          "words) and say that it fails (not, doesn't, can't, wrong, actually ...)", sid)

    # E45 to E47 (codex round 4, the longer lazy lesson): the lesson must be about THIS concept.
    # A mechanism turn uses at least two domain terms (outline newTerms, or content words of facts.json
    # claims, quotes and misconceptions, and the concept); its worked number or name traces to
    # facts.json or the outline; a misconception turn names the outline's (or facts.json's) wrong belief.
    vocab, phrases = domain_vocab(facts, outline)
    traced = trace_text(facts, outline)
    beliefs = misconception_statements(facts, outline)
    for seg in segments:
        role, sid = seg.get("role"), seg.get("id")
        turns = [t for t in seg.get("turns", []) if isinstance(t, dict)]
        if not turns or role not in CIRCULAR_ROLES:
            continue
        if role == "mechanism":
            if vocab or phrases:
                best = max(len(domain_terms_in(spoken_text(t.get("text", "")), vocab, phrases)) for t in turns)
                if best < 2:
                    rep.error("E45", f"no mechanism turn uses two domain terms (the most in one turn is {best}); name the parts "
                              "of THIS concept (outline newTerms, words from facts.json) in the causal step, not 'a process' or "
                              "'a step'", sid)
            if traced:
                cases = [t for t in turns if digit_tokens(t.get("text", "")) or named_case(t.get("text", ""))]
                if cases and not any(case_traced(t.get("text", ""), traced) for t in cases):
                    rep.error("E46", "the mechanism's worked example uses numbers or names that appear nowhere in facts.json "
                              "or outline.json; work the case the outline and facts plan (or add it to facts.json as "
                              "illustrative data)", sid)
        elif role == "misconception" and beliefs:
            if not any(len(content_words(spoken_text(t.get("text", ""))) & content_words(b)) >= min(2, len(content_words(b)))
                       for t in turns for b in beliefs):
                rep.error("E47", "no turn in the misconception segment names the wrong belief from outline.misconception (or "
                          "facts.json misconceptions); voice that belief in its own key words, then refute it", sid)

    # E48/W48 (judge v6, t08's unsourced collision rule): a spoken number or rule-like claim
    # (always, never, only) needs factIds; an error in mechanism, example and misconception segments.
    # W49: an always/never claim with no scope words ("with one point per server", "in that simulation").
    for seg, t in flat:
        text = spoken_text(t.get("text", ""))
        rule = RULE_RE.search(text)
        claim = number_tokens(text) or SPELLED_RE.search(text) or rule
        if claim and not t.get("factIds") and t.get("kind") != "explain-back" and not isinstance(t.get("pause"), dict):
            what = f"rule word '{rule.group(0)}'" if rule else "a number"
            msg = (f"turn states {what} but cites no factIds; trace the claim to facts.json (sourced, arithmetic or "
                   "illustrative) or cut it")
            # An error for the expert's claims in mechanism, example and misconception segments; the
            # learner's guesses and questions (often the wrong belief on purpose) only warn.
            if seg.get("role") in FACT_ROLES and expert(t):
                rep.error("E48", msg, seg.get("id"), t.get("id"))
            else:
                rep.warn("W48", msg, seg.get("id"), t.get("id"))
        m = unscoped_absolute(text)
        if m and not SCOPE_RE.search(text):
            rep.warn("W49", f"'{m.group(0)}' with no scope; say where it holds ('with one point per server', 'in that "
                     "simulation', 'for a fixed fleet')", seg.get("id"), t.get("id"))

    # E29: a term is described in plain words before (or as) it is named.
    defines = [i for i, (_, t) in enumerate(flat) if DEFINE_RE.search(spoken_text(t.get("text", ""))) and not circular(t.get("text", ""))]
    terms = [x for s in (outline or {}).get("segments", []) if isinstance(s, dict) for x in s.get("newTerms", []) or []]
    if not terms:
        terms = [x for _, t in flat for x in t.get("onScreen", []) or [] if not any(c.isdigit() for c in x)]
    first = {}
    for term in dict.fromkeys(terms):
        for i, (_, t) in enumerate(flat):
            if term_in(term, norm(spoken_text(t.get("text", "")))):
                first[term] = i
                break
    if first and not defines:
        rep.error("E29", "no turn defines anything in plain words (means, is called, that's a ..., think of it as ...); "
                  "give the plain meaning before or as each term is named (script.md S7)")
    elif outline is not None:
        for term, i in first.items():
            named = re.search(rf"\b(is|are|called|named)\s+(the |a |an )?{re.escape(term.lower())}\b",
                              spoken_text(flat[i][1].get("text", "")).lower())
            if not named and not any(i - 2 <= d <= i + 1 for d in defines):
                seg, t = flat[i]
                rep.error("E29", f"new term '{term}' is named with no plain-words description in the 2 turns before it or the turn "
                          f"after (means, is called, that's a ..., think of it as ...); plain meaning first, then the term",
                          seg.get("id"), t.get("id"))

    for k, (seg, t) in enumerate(flat):
        sid, tid = seg.get("id"), t.get("id")
        # E34/W34: numbers or positions that are only on screen.
        nums = {n for x in t.get("onScreen", []) or [] for n in digit_tokens(x)}
        if nums:
            near = set()
            for j in (k - 1, k, k + 1):
                if 0 <= j < len(flat) and flat[j][0] is seg:
                    near |= digit_tokens(flat[j][1].get("text", ""))
            silent = sorted(nums - near)
            if silent:
                msg = (f"onScreen shows {', '.join(silent)} but no host says it in this turn or the next to it: a worked example "
                       f"must be followable by ear (say the number or position)")
                if seg.get("role") in ("mechanism", "example"):
                    rep.error("E34", msg, sid, tid)
                else:
                    rep.warn("W34", msg, sid, tid)

    for seg in segments:
        sid, role = seg.get("id"), seg.get("role")
        turns = [t for t in seg.get("turns", []) if isinstance(t, dict)]
        o = oseg.get(sid, {})
        # E33/W33: a specific case (2+ numbers) needs a general statement after it, in the same segment.
        if role in SPECIFIC_ROLES or o.get("requireGeneralRule"):
            spec = next((i for i, t in enumerate(turns) if len(digit_tokens(t.get("text", ""))) >= 2), None)
            if spec is not None and not any(GENERAL_RE.search(spoken_text(t.get("text", ""))) for t in turns[spec:]):
                msg = (f"turn {turns[spec].get('id')} works a specific case with numbers, but no later turn in this segment states "
                       f"the general rule ('in general ...', 'about K over N', 'on average ...'); end the case with its rule")
                if o.get("requireGeneralRule"):
                    rep.error("E33", msg, sid)
                else:
                    rep.warn("W33", msg, sid)
        # E35/W35: in the core step the learner gets thinking time before an answer.
        pairs = [(a, b) for a, b in zip(turns, turns[1:]) if learner(a) and "?" in spoken_text(a.get("text", "")) and expert(b)]
        bare = [a.get("id") for a, b in pairs if not a.get("pause") and not a.get("holdAfterMs")]
        # The expert may pose the core question instead: a predict or retrieve hold on an expert question that the
        # learner then answers also gives the learner thinking time before the answer (W9, 2 Nov 2026).
        posed = any(expert(a) and learner(b) and hold_of(a) and a["pause"].get("kind") in ("predict", "retrieve")
                    for a, b in zip(turns, turns[1:]))
        if posed:
            bare = []
        if o.get("coreSegment") is True:
            if pairs and bare and len(bare) == len(pairs):
                rep.error("E35", f"core segment: every learner question ({', '.join(bare)}) is answered at once; give one of them "
                          f"pause {{kind: 'predict'}} and holdAfterMs 7000 so the learner works the core step before the answer", sid)
        elif role == "mechanism" and bare:
            rep.warn("W35", f"learner question(s) {', '.join(bare)} answered at once with no pause or hold; consider a predict "
                     f"pause before the key step", sid)
        # E37: explain-back pause before the explain-back turn.
        if o.get("explainBack") is True:
            eb = next((i for i, t in enumerate(turns) if t.get("kind") == "explain-back"), None)
            if eb is None:
                rep.error("E37", "outline sets explainBack but the segment has no turn with kind 'explain-back'", sid)
            elif not any(hold_of(t) and t["pause"].get("kind") == "explain-back" for t in turns[:eb]):
                rep.error("E37", f"outline sets explainBack: put a pause {{kind: 'explain-back', prompt}} with holdAfterMs 7000 to "
                          f"8000 on a turn BEFORE {turns[eb].get('id')}, so the learner explains it before the host does", sid, turns[eb].get("id"))


def check_script(data: dict, facts: dict | None, minutes: float | None, max_words: int, audio_mode: str, rep: Report,
                 brief: dict | None = None, outline: dict | None = None):
    speakers = [s for s in data.get("speakers", []) if isinstance(s, dict)]
    segments = [s for s in data.get("segments", []) if isinstance(s, dict)]
    spk_ids = [s.get("id") for s in speakers]
    spk_role = {s.get("id"): s.get("role") for s in speakers}
    names = [s.get("name", "") for s in speakers if s.get("name")]
    prefix_names = {n.lower() for n in names} | {str(i).lower() for i in spk_ids if i}
    if len(set(spk_ids)) != len(spk_ids):
        rep.error("E02", f"speaker ids must be unique: {spk_ids}")
    roles = sorted(spk_role.values(), key=str)
    if len(speakers) == 2 and roles != ["expert", "learner"]:
        rep.error("E02", f"speakers need one 'learner' and one 'expert', got {roles}")
    if len(speakers) == 2 and speakers[0].get("side") == speakers[1].get("side"):
        rep.warn("W02", "both speakers are on the same side of the screen")

    check_structure(data, segments, minutes, rep)
    check_pauses(data, segments, spk_role, brief, rep)

    fact_tokens = fact_number_index(facts)
    numbers_seen = False
    all_turns: list[tuple[dict, dict]] = []
    turn_ids: list[str] = []
    for seg in segments:
        for t in seg.get("turns", []) or []:
            if isinstance(t, dict):
                all_turns.append((seg, t))
                turn_ids.append(t.get("id"))
    for dup in sorted({i for i in turn_ids if turn_ids.count(i) > 1}):
        rep.error("E03", f"duplicate turn id {dup}", turn=dup)

    # E04: no three same-speaker turns in a row (across segment boundaries too).
    run = 0
    prev = None
    for seg, t in all_turns:
        sp = t.get("speaker")
        run = run + 1 if sp == prev else 1
        prev = sp
        if run == 3:
            rep.error("E04", f"third '{sp}' turn in a row; insert a turn from the other host or merge", seg.get("id"), t.get("id"))

    # W38 (J8): expert turns back to back with no learner turn between (across segment boundaries
    # too) over 60 words; a hold counts as words at SECS_PER_WORD (an 8 s hold is 22 words).
    def flush_expert_run(run_turns: list[tuple[dict, dict]]):
        if len(run_turns) < 2:
            return
        spoken = sum(word_count(t.get("text", "") if isinstance(t.get("text"), str) else "") for _, t in run_turns)
        hold = sum(round(t["holdAfterMs"] / 1000 / SECS_PER_WORD) for _, t in run_turns
                   if isinstance(t.get("holdAfterMs"), (int, float)) and not isinstance(t.get("holdAfterMs"), bool) and t["holdAfterMs"] > 0)
        if spoken + hold > EXPERT_RUN_WORDS:
            ids = ", ".join(str(t.get("id")) for _, t in run_turns)
            rep.warn("W38", f"expert turns {ids} run back to back with no learner turn: {spoken + hold} words ({spoken} spoken"
                     + (f" + {hold} for holds at {SECS_PER_WORD} s per word" if hold else "") + f"), over {EXPERT_RUN_WORDS}; "
                     "insert a short learner turn between them (a question, a prediction, a restatement) or merge and cut (J8)",
                     run_turns[0][0].get("id"), run_turns[0][1].get("id"))

    expert_run: list[tuple[dict, dict]] = []
    for seg, t in all_turns:
        if spk_role.get(t.get("speaker")) == "expert":
            expert_run.append((seg, t))
        else:
            flush_expert_run(expert_run)
            expert_run = []
    flush_expert_run(expert_run)

    backchannels = 0
    expert_words = 0
    deep_questions = 0
    for seg, t in all_turns:
        sid, tid = seg.get("id"), t.get("id")
        text = t.get("text", "") if isinstance(t.get("text"), str) else ""
        sp = t.get("speaker")
        if sp not in spk_role:
            rep.error("E02", f"speaker '{sp}' is not in speakers {spk_ids}", sid, tid)
        n = word_count(text)
        if n > max_words:
            rep.error("E05", f"{n} words; the cap is {max_words}. Split into two turns with a learner question between", sid, tid)
        if spk_role.get(sp) == "expert":
            expert_words += n
        if spk_role.get(sp) == "learner" and "?" in text and DEEP_Q_RE.search(text):
            deep_questions += 1
        if spk_role.get(sp) == "learner" and PRAISE_RE.search(text):
            rep.warn("W14", "learner praises the expert; cut it (pedagogy S13)", sid, tid)
        if n <= 4 or BACKCHANNEL_START_RE.match(spoken_text(text)):
            backchannels += 1
        backchannels += len(PIPE_RE.findall(text))

        # E11: stage directions and prefixes that Gemini 3.8 would read aloud.
        for m in re.finditer(r"\([^)]*\)", text):
            rep.error("E11", f"parenthesis {m.group(0)!r} is spoken verbatim; move delivery into 'style' or cut it", sid, tid)
        for m in re.finditer(r"\[[^\]]*\]", text):
            rep.error("E11", f"square-bracket tag {m.group(0)!r} is a stage direction; use an allowed <tag> or 'style'", sid, tid)
        for m in re.finditer(r"\*[^*]+\*", text):
            rep.error("E11", f"asterisk markup {m.group(0)!r} is a stage direction or markdown; remove it", sid, tid)
        # A speaker prefix is a host name or id, or a generic label (Host, Guest, Speaker 2), then a colon.
        # A spoken colon ("So the opening puzzle: ...") is fine.
        m = PREFIX_RE.match(text)
        if m and (m.group(1).strip().lower() in prefix_names or GENERIC_PREFIX_RE.match(m.group(1).strip())):
            rep.error("E11", f"text starts with a '{m.group(1)}:' speaker prefix; the speaker comes from the 'speaker' field", sid, tid)
        else:
            m = None
        for name in names:
            if m and m.group(1).strip() == name:
                continue  # already reported as a leading prefix
            if re.search(rf"\b{re.escape(name)}\s*:", text):
                rep.error("E11", f"'{name}:' prefix inside the text; speakers come from the 'speaker' field", sid, tid)
        for tag in TAG_RE.findall(text):
            if tag.strip().lower() not in ALLOWED_TAGS:
                rep.error("E11", f"<{tag}> is not a Gemini 3.8 event tag and would be spoken; allowed: {sorted(ALLOWED_TAGS)}", sid, tid)
        if text.count("|") % 2:
            rep.error("E11", "unbalanced '|' backchannel markup", sid, tid)
        for bc in PIPE_RE.findall(text):
            if len(bc.split()) > 3:
                rep.error("E11", f"backchannel |{bc}| has more than 3 words", sid, tid)
            elif audio_mode == "per-turn":
                rep.warn("W11", f"backchannel |{bc}| only renders in --chunk mode; in per-turn mode write it as its own short turn", sid, tid)

        # Numbers and facts.
        tids = t.get("factIds", []) or []
        if facts is not None:
            for fid in tids:
                if fid not in fact_tokens:
                    rep.error("E09", f"factId {fid} is not in facts.json", sid, tid)
        pause_prompt = t["pause"].get("prompt", "") if isinstance(t.get("pause"), dict) else ""
        in_text = set(number_tokens(text))
        for tok in dict.fromkeys(number_tokens(text) + number_tokens(pause_prompt)):
            numbers_seen = True
            if facts is None:
                continue
            if any(tok in fact_tokens.get(fid, set()) for fid in tids):
                continue
            where = "" if tok in in_text else " (in pause.prompt)"
            owners = [fid for fid, toks in fact_tokens.items() if tok in toks]
            if owners:
                rep.error("E08", f"number '{tok}'{where} is in facts.json ({', '.join(owners)}) but the turn does not cite it; add the id to factIds", sid, tid)
            else:
                rep.error("E08", f"number '{tok}'{where} has no fact in facts.json; add a sourced, arithmetic or illustrative fact, or cut the number", sid, tid)
        for m in SPELLED_RE.finditer(spoken_text(text)):
            rep.warn("W08", f"spelled number '{m.group(0)}': write numbers above ten as digits so they can be traced to facts.json", sid, tid)

    if numbers_seen and facts is None:
        rep.error("E08", "turns contain numbers but no --facts file was given; every number needs a sourced fact")

    # E07: every onScreen term is spoken somewhere in its segment.
    for seg in segments:
        seg_norm = norm(" ".join(spoken_text(t.get("text", "")) for t in seg.get("turns", []) if isinstance(t, dict)))
        for t in seg.get("turns", []) or []:
            if not isinstance(t, dict):
                continue
            for term in t.get("onScreen", []) or []:
                if not term_in(term, seg_norm):
                    rep.error("E07", f"onScreen term '{term}' is never spoken in {seg.get('id')}; say it or drop it", seg.get("id"), t.get("id"))
                if len(term.split()) > 5:
                    rep.warn("W07", f"onScreen term '{term}' has more than 5 words; labels, not sentences (redundancy rule V5)", seg.get("id"), t.get("id"))

    # Retrieval and recap shape.
    for seg in segments:
        turns = [t for t in seg.get("turns", []) if isinstance(t, dict)]
        if seg.get("role") in QUESTION_ROLES and not any("?" in t.get("text", "") for t in turns):
            rep.error("E16", f"{seg.get('role')} segment has no question; it needs one retrieval question (pedagogy S12)", seg.get("id"))
        if seg.get("role") == "recap":
            lw = sum(word_count(t.get("text", "")) for t in turns if spk_role.get(t.get("speaker")) == "learner")
            tw = sum(word_count(t.get("text", "")) for t in turns) or 1
            if lw / tw < 0.5:
                rep.warn("W16", f"recap is {lw / tw:.0%} learner words; the learner should do most of the recap (pedagogy S3)", seg.get("id"))
        if seg.get("role") == "misconception" and not any(spk_role.get(t.get("speaker")) == "learner" for t in turns):
            rep.error("E17", "misconception segment has no learner turn; the learner must voice the wrong model (pedagogy S2)", seg.get("id"))

    # W14 backchannels, W15 deep questions.
    if all_turns and backchannels > math.ceil(len(all_turns) / BACKCHANNEL_EVERY):
        rep.warn("W14", f"{backchannels} backchannel or filler turns in {len(all_turns)} turns; limit is one per {BACKCHANNEL_EVERY} (pedagogy S13)")
    expert_sec = expert_words * SECS_PER_WORD
    needed = max(1, math.ceil(expert_sec / DEEP_QUESTION_EVERY_SEC)) if expert_words else 0
    if deep_questions == 0 and all_turns:
        rep.error("E15", "the learner never asks a why, how or what-if question; the learner host drives the explanation (pedagogy S1)")
    elif deep_questions < needed:
        rep.warn("W15", f"{deep_questions} deep learner questions (why/how/what if) for {expert_sec:.0f} s of expert speech; want at least {needed} (pedagogy S1)")

    # Required learning actions that structure alone can show is missing (learning-design L1, L10, rule 8).
    if all_turns and not any(t.get("onScreen") for _, t in all_turns):
        rep.error("E07", "no turn has onScreen terms; every spoken claim needs a visible state change, so name what appears on screen")
    if facts is not None and all_turns and not any(t.get("factIds") for _, t in all_turns):
        rep.error("E09", "no turn cites a fact; every claim traces to facts.json (non-negotiable 4)")
    for seg, t in all_turns:
        if circular(t.get("text", "")):
            m = TAUTOLOGY_RE.search(spoken_text(t.get("text", "")))
            if seg.get("role") in CIRCULAR_ROLES:
                rep.error("E27", f"circular explanation in a {seg.get('role')} segment: the 'because' clause repeats its own claim "
                          f"({m.group(0)[:60]!r}); give the cause with a number, a name or an example", seg.get("id"), t.get("id"))
            else:
                rep.warn("W26", f"circular explanation: the 'because' clause repeats its own claim ({m.group(0)[:60]!r}); give the cause", seg.get("id"), t.get("id"))
    check_teaching(data, segments, spk_role, outline, rep, facts)

    # W12: duplicate core claims. Each turn is compared with every earlier segment.
    checked = [s for s in segments if s.get("role") not in DUP_EXEMPT_ROLES]
    seg_grams = {s.get("id"): content_trigrams(" ".join(spoken_text(t.get("text", "")) for t in s.get("turns", []) if isinstance(t, dict)))
                 for s in checked}
    for i, seg in enumerate(checked):
        for t in seg.get("turns", []) or []:
            if not isinstance(t, dict):
                continue
            tg = content_trigrams(spoken_text(t.get("text", "")))
            for earlier in checked[:i]:
                shared = tg & seg_grams[earlier.get("id")]
                if len(shared) >= DUP_MIN_SHARED and len(shared) / (len(tg) or 1) >= DUP_MIN_OVERLAP:
                    sample = "; ".join(" ".join(g) for g in sorted(shared)[:3])
                    rep.warn("W12", f"repeats {earlier.get('id')} ({len(shared)} shared content trigrams: {sample}); one core claim, one home",
                             seg.get("id"), t.get("id"))

    # E06/W06: word budget.
    if minutes is None:
        rep.error("E06", "no target length: pass --minutes or set targetMinutes; the word budget is part of the check")
        return
    # The word budget is the target minus everything that is not speech: holds, the gaps between
    # turns, the segment tails and the lead (codex round 3 stumble 4: gaps and tails were left out).
    pred = pc.predict_length(data)
    silent_sec = pred["holdSec"] + pred["gapSec"] + pred["tailSec"] + pred["leadSec"]
    total_target = max(1.0, (minutes * 60 - silent_sec) / SECS_PER_WORD)
    total = sum(word_count(t.get("text", "")) for _, t in all_turns)
    off = (total - total_target) / total_target
    msg = (f"{total} words is {abs(off):.0%} {'over' if off > 0 else 'under'} the {total_target:.0f}-word budget for "
           f"{minutes:g} min at the measured {SECS_PER_WORD} s per word (about {WPM:.0f} wpm), after {silent_sec:.0f} s "
           f"of holds ({pred['holdSec']:.0f} s), gaps ({pred['gapSec']:.0f} s), segment tails ({pred['tailSec']:.0f} s) and lead")
    if abs(off) > TOTAL_BUDGET_ERROR:
        rep.error("E06", msg)
    elif abs(off) > TOTAL_BUDGET_WARN:
        rep.warn("W06", msg)
    # E39/W39: the predicted final length against the target, before any TTS spend (the v5 script
    # was 15.9% over and nothing caught it). tts.py --dry-run prints the same prediction.
    # Q08 (codex round 4): the same pe_common.length_check that tts.py --dry-run and the paid path run;
    # a series part predicted over 12 min minus 5% headroom is an error here, before any payment.
    for level, code, lmsg in pc.length_check(data, minutes)["problems"]:
        (rep.error if level == "error" else rep.warn)(code, lmsg)
    rep.length = {**{k: round(v, 1) if isinstance(v, float) else v for k, v in pred.items()}, "targetSec": minutes * 60}
    explicit = {s.get("id"): s["targetSec"] / SECS_PER_WORD for s in segments if isinstance(s.get("targetSec"), (int, float))}
    rest = max(0.0, total_target - sum(explicit.values()))

    def weight(i: int) -> float:
        role = segments[i].get("role")
        if role in QUESTION_ROLES and i == len(segments) - 1 and (i == 0 or segments[i - 1].get("role") != "recap"):
            return FOLDED_CHECK_WEIGHT
        return ROLE_WEIGHTS.get(role, 100)

    weight_sum = sum(weight(i) for i, s in enumerate(segments) if s.get("id") not in explicit) or 1
    rep.budget = {"totalWords": total, "budgetWords": round(total_target), "minutes": minutes, "segments": []}
    for i, s in enumerate(segments):
        target = explicit.get(s.get("id"), rest * weight(i) / weight_sum)
        words = sum(word_count(t.get("text", "")) for t in s.get("turns", []) if isinstance(t, dict))
        rep.budget["segments"].append({"id": s.get("id"), "role": s.get("role"), "words": words, "budget": round(target)})
        if target <= 0:
            continue
        dev = (words - target) / target
        if abs(dev) > SEGMENT_BUDGET_WARN:
            rep.warn("W06", f"{words} words vs about {target:.0f} planned for a '{s.get('role')}' segment ({dev:+.0%})", s.get("id"))


# ---------------------------------------------------------------- main

KIND_SCHEMA = {"script": "script.schema.json", "outline": "outline.schema.json",
               "facts": "facts.schema.json", "brief": "brief.schema.json", "series": "series.schema.json"}


CARRIED_KEYS = ("label", "value", "role", "pos", "angle", "x", "y", "shape")


def _resolved(doc) -> bool:
    """True when a manifest has resolved scene times (episode.json from build_manifest.py)."""
    scenes = [sc for sc in (doc or {}).get("scenes", []) or [] if isinstance(sc, dict)]
    return bool(scenes) and all(pc._num(sc.get("startMs")) for sc in scenes)


def world_end_state(doc: dict, episode: dict | None = None) -> dict[str, dict]:
    """Nodes on screen at the end of a part with the label and value they DISPLAY there (Q01, codex
    round 4). It replays the renderer's rules through pe_common (world_visibility, node_overrides,
    node_text_at: the W11b expiry semantics): a `set` value or label shows until the next step on
    the timeline unless the patch has persist, and a node's own value shows from its reveal until the
    next step unless the node has persist. It never applies every historical `set` forever.

    `episode` is the part's resolved episode.json (scene startMs, step atMs); when it is absent the
    scenes.json order stands in for time (scene i starts at i x 10^7 ms, untimed step j at + j x 1500
    ms, the renderer's fallback), which gives the same order of steps and so the same end state."""
    manifest = episode if _resolved(episode) else None
    if manifest is None:
        manifest = {**doc, "scenes": [{**sc, "startMs": i * 10_000_000, "endMs": (i + 1) * 10_000_000}
                                      for i, sc in enumerate(doc.get("scenes", []) or []) if isinstance(sc, dict)]}
    world = manifest.get("world") or doc.get("world") or {}
    nodes = [n for n in world.get("nodes", []) or [] if isinstance(n, dict) and n.get("id")]
    timeline = pc.world_timeline(manifest)
    ends = [sc.get("endMs") for sc in manifest.get("scenes", []) if pc._num(sc.get("endMs"))]
    now = max(ends + [st["t"] for st in timeline] + [0])
    w = {**world, "nodes": nodes, "edges": [e for e in world.get("edges", []) or [] if isinstance(e, dict) and e.get("id")]}
    vis = pc.world_visibility(w, timeline, now)
    over = pc.node_overrides(timeline, now)
    out = {}
    for n in nodes:
        v = vis.get(n["id"])
        if not (v and v[0]):
            continue
        label, value = pc.node_text_at(n, v, over.get(n["id"]), timeline, now)
        out[n["id"]] = {**n, "label": label, "value": value}
    return out


def world_start_state(doc: dict) -> dict[str, dict]:
    """Nodes a part declares, with the label and value they display when first drawn."""
    return {x.get("id"): {**x, "value": x.get("value")} for x in (doc.get("world") or {}).get("nodes", []) if isinstance(x, dict)}


def check_series(data: dict, path: Path, rep: Report, final: bool = False):
    """Cross-part checks (references/depth.md section 5). The workspace is the folder that holds
    <series-id>/series.json and the part folders <series-id>-p<N>/. With final=True (--final, the
    delivery check of a whole series) a missing part, a part without measured audio or a world
    that does not carry over is an error, not a warning (E01)."""
    ws = path.resolve().parent.parent
    parts = sorted([p for p in data.get("parts", []) if isinstance(p, dict)], key=lambda p: p.get("part", 0))
    nums = [p.get("part") for p in parts]
    if nums != list(range(1, len(parts) + 1)):
        rep.error("E30", f"parts must be numbered 1..{len(parts)} in order, got {nums}")
    hosts, glossaries, retrieval, misconception, worlds = {}, {}, 0, False, []
    for p in parts:
        slug, n = p.get("slug", ""), p.get("part")
        if slug != f"{data.get('id')}-p{n}":
            rep.error("E30", f"part {n}: slug {slug!r} must be {data.get('id')}-p{n}")
        d = ws / slug
        sp = d / "script.json"
        if not sp.is_file():
            if final:
                rep.error("E30", f"part {n}: {sp} does not exist; a final series check needs every part")
            else:
                rep.warn("W30", f"part {n}: {sp} does not exist yet; cross-part checks skip it (--final makes this an error)")
            continue
        try:
            sc = json.loads(sp.read_text())
        except json.JSONDecodeError as e:
            rep.error("E00", f"{sp}: invalid JSON at line {e.lineno}: {e.msg}")
            continue
        ser = sc.get("series") or {}
        if ser.get("id") != data.get("id") or ser.get("part") != n or ser.get("parts") != len(parts):
            rep.error("E30", f"part {n}: script.json series is {ser}; want id {data.get('id')}, part {n}, parts {len(parts)}")
        hosts[n] = [(s.get("id"), s.get("name"), s.get("voice"), s.get("color"), s.get("side")) for s in sc.get("speakers", [])]
        segs = [s for s in sc.get("segments", []) if isinstance(s, dict)]
        # Distinct retrievals: a check or selftest segment counts once, however many pauses it holds;
        # a retrieve pause counts only outside such a segment.
        retrieval += sum(1 for s in segs if s.get("role") in QUESTION_ROLES)
        retrieval += sum(1 for s in segs if s.get("role") not in QUESTION_ROLES for t in s.get("turns", [])
                         if isinstance(t, dict) and isinstance(t.get("pause"), dict) and t["pause"].get("kind") == "retrieve")
        misconception |= any(s.get("role") == "misconception" for s in segs)
        g = d / "glossary.json"
        if g.is_file():
            try:
                gl = json.loads(g.read_text())
                glossaries[n] = json.dumps(gl, sort_keys=True)
                if not isinstance(gl, dict) or not isinstance(gl.get("terms"), list):
                    rep.error("E31", f"part {n}: {g} must be an object with a 'terms' list")
            except json.JSONDecodeError as e:
                rep.error("E31", f"part {n}: {g} is not valid JSON (line {e.lineno}: {e.msg})")
                glossaries[n] = f"<invalid {n}>"
        else:
            glossaries[n] = None
            if final:
                rep.error("E31", f"part {n}: no glossary.json; a final series check needs the shared series glossary in every part")
        tp = d / "timing.json"
        if tp.is_file():
            # E01 (codex round 3): malformed or unmeasured timing is an error, never a duration of 0.
            try:
                tdoc = json.loads(tp.read_text())
            except json.JSONDecodeError as e:
                tdoc = None
                rep.error("E21", f"part {n}: {tp} is not valid JSON (line {e.lineno}: {e.msg}); its length cannot be measured. Rerun tts.py")
            if tdoc is not None:
                dur = tdoc.get("durationMs") if isinstance(tdoc, dict) else None
                if not (isinstance(dur, int) and not isinstance(dur, bool) and dur > 0) or not isinstance(tdoc.get("turns"), list):
                    rep.error("E21", f"part {n}: {tp} has no positive integer durationMs and turns list (got durationMs {dur!r}); rerun tts.py")
                else:
                    # E01 (codex round 4): a measured part has one timing turn per script turn and at least
                    # 80% of the words x 0.357 s the script predicts; {"durationMs": 1, "turns": []} is not audio.
                    words = sum(word_count(t.get("text", "") if isinstance(t.get("text"), str) else "")
                                for s in segs for t in s.get("turns", []) or [] if isinstance(t, dict))
                    n_script = sum(1 for s in segs for t in s.get("turns", []) or [] if isinstance(t, dict))
                    floor_ms = MIN_MEASURED_RATIO * words * SECS_PER_WORD * 1000
                    if n_script and len(tdoc["turns"]) != n_script:
                        rep.error("E21", f"part {n}: {tp} has {len(tdoc['turns'])} timing turns for {n_script} script turns; "
                                  "it is not this part's measured audio. Rerun tts.py")
                    if words and dur < floor_ms:
                        rep.error("E21", f"part {n}: {tp} durationMs {dur} is under {floor_ms:.0f} ms ({MIN_MEASURED_RATIO:g} x {words} "
                                  f"words x {SECS_PER_WORD} s); that is not measured speech. Rerun tts.py")
                    if dur > MAX_PART_MINUTES * 60000:
                        rep.error("E21", f"part {n}: measured audio is {dur / 60000:.1f} min; a part is at most {MAX_PART_MINUTES} min. "
                                  f"Cut turns or move a segment to the next part, then rerun tts.py")
                    draft = pc.production_problems(tdoc)
                    if final and draft:
                        rep.error("E21", f"part {n}: timing.json is not measured delivery audio ({draft[0]}); run tts.py and align.mjs without draft flags")
        elif final:
            rep.error("E21", f"part {n}: no timing.json, so its length is not measured; run tts.py for it")
        scp = d / "scenes.json"
        if scp.is_file():
            try:
                doc = json.loads(scp.read_text())
            except json.JSONDecodeError as e:
                doc = None
                rep.error("E32", f"part {n}: {scp} is not valid JSON (line {e.lineno}: {e.msg}); its world cannot be checked")
            if doc is not None:
                if not isinstance(doc, dict) or not isinstance(doc.get("scenes"), list):
                    rep.error("E32", f"part {n}: {scp} has no scenes list")
                else:  # the full scenes schema is build_manifest.py's check; here only the world carry-over
                    episode = None
                    epp = d / "episode.json"
                    if epp.is_file():
                        try:
                            episode = json.loads(epp.read_text())
                        except json.JSONDecodeError as e:
                            rep.error("E32", f"part {n}: {epp} is not valid JSON (line {e.lineno}: {e.msg}); rerun build_manifest.py")
                    elif final:
                        rep.warn("W32", f"part {n}: no episode.json; the end-of-part world is replayed from scenes.json order, "
                                 "not from resolved times (run build_manifest.py)")
                    worlds.append((n, world_end_state(doc, episode if isinstance(episode, dict) else None), world_start_state(doc)))
        elif final:
            rep.error("E32", f"part {n}: no scenes.json, so its world cannot be checked against the other parts")
    if len(set(map(tuple, hosts.values()))) > 1:
        rep.error("E31", "hosts differ between parts (id, name, voice, colour or side); keep the same two hosts in every part")
    if len({v for v in glossaries.values()}) > 1:
        (rep.error if final else rep.warn)("E31" if final else "W31", "glossary.json differs between parts (or is missing in some); "
                                           "keep one series glossary and copy it into each part")
    if final and not hosts:
        rep.error("E30", "no part of the series exists")
    if hosts and retrieval < 2:
        rep.error("E21", f"the series has {retrieval} distinct retrieval checks; a deep run needs at least 2")
    if hosts and not misconception:
        rep.error("E13", "no part has a misconception segment")
    say = rep.error if final else rep.warn
    for (a, end_a, _), (b, _, start_b) in zip(worlds, worlds[1:]):
        dropped = sorted(set(end_a) - set(start_b))
        if dropped:
            say("E32" if final else "W32", f"part {b}'s world drops nodes that are on screen at the end of part {a} ({dropped[:5]}); "
                f"part {b} starts from part {a}'s final world")
        changed = [f"{nid}.{k} {end_a[nid].get(k)!r} -> {start_b[nid].get(k)!r}" for nid in sorted(set(end_a) & set(start_b))
                   for k in CARRIED_KEYS if end_a[nid].get(k) != start_b[nid].get(k)]
        if changed:
            say("E32" if final else "W32", f"part {b}'s world does not carry part {a}'s final state: {'; '.join(changed[:4])}"
                f"{' ...' if len(changed) > 4 else ''}; copy the end-of-part labels, values and positions")


def detect_kind(path: Path, data) -> str | None:
    stem = path.stem.lower()
    for k in KIND_SCHEMA:
        if stem == k or stem.endswith("-" + k) or stem.endswith("_" + k):
            return k
    if isinstance(data, dict):
        segs = data.get("segments")
        if isinstance(segs, list) and segs and isinstance(segs[0], dict) and "turns" in segs[0]:
            return "script"
        if isinstance(segs, list):
            return "outline"
        if "facts" in data:
            return "facts"
        if "learner" in data:
            return "brief"
        if isinstance(data.get("parts"), list):
            return "series"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic checks for script.json, outline.json, facts.json and brief.json.")
    ap.add_argument("file", type=Path, help="script.json, outline.json, facts.json or brief.json")
    ap.add_argument("--facts", type=Path, help="facts.json; required whenever the script contains numbers")
    ap.add_argument("--brief", type=Path, help="brief.json for learnerLevel checks (default: brief.json next to the script, if present)")
    ap.add_argument("--outline", type=Path, help="outline.json for coreSegment, explainBack, requireGeneralRule and newTerms "
                    "(default: outline.json next to the script, if present)")
    ap.add_argument("--minutes", type=float, help="target length in minutes (else script.targetMinutes)")
    ap.add_argument("--max-turn-words", type=int, default=DEFAULT_MAX_TURN_WORDS, help=f"turn length cap (default {DEFAULT_MAX_TURN_WORDS})")
    ap.add_argument("--audio-mode", choices=["per-turn", "chunk"], default="per-turn", help="TTS mode the script is written for (default per-turn)")
    ap.add_argument("--kind", choices=sorted(KIND_SCHEMA), help="file kind; default from the file name or keys")
    ap.add_argument("--final", action="store_true", help="series.json only: strict delivery check (every part exists, "
                    "is measured and carries the previous part's world)")
    ap.add_argument("--json", action="store_true", help="print a JSON report instead of text")
    args = ap.parse_args(argv)

    rep = Report(str(args.file))
    data = None
    try:
        data = json.loads(args.file.read_text())
    except FileNotFoundError:
        rep.error("E00", f"file not found: {args.file}")
    except json.JSONDecodeError as e:
        rep.error("E00", f"{args.file}: invalid JSON at line {e.lineno} column {e.colno}: {e.msg}")

    kind = args.kind or (detect_kind(args.file, data) if data is not None else None)
    engine = "-"
    if data is not None and kind is None:
        rep.error("E00", f"cannot tell the file kind of {args.file}; pass --kind script|outline|facts|brief")
    elif data is not None:
        errs, engine = schema_errors(data, KIND_SCHEMA[kind])
        for e in errs:
            rep.error("E01", f"schema: {e}")
        if isinstance(data, dict):
            facts = load_facts(args.facts, rep) if args.facts else None
            if kind == "script":
                minutes = args.minutes if args.minutes is not None else data.get("targetMinutes")
                brief_path = args.brief or (args.file.parent / "brief.json")
                brief = None
                if brief_path.is_file():
                    try:
                        brief = json.loads(brief_path.read_text())
                    except json.JSONDecodeError as e:
                        rep.error("E00", f"{brief_path}: invalid JSON at line {e.lineno}: {e.msg}")
                elif args.brief:
                    rep.error("E00", f"brief file not found: {brief_path}")
                outline_path = args.outline or (args.file.parent / "outline.json")
                outline = None
                if outline_path.is_file():
                    try:
                        outline = json.loads(outline_path.read_text())
                    except json.JSONDecodeError as e:
                        rep.error("E00", f"{outline_path}: invalid JSON at line {e.lineno}: {e.msg}")
                elif args.outline:
                    rep.error("E00", f"outline file not found: {outline_path}")
                check_script(data, facts, minutes, args.max_turn_words, args.audio_mode, rep, brief, outline)
            elif kind == "outline":
                check_outline(data, facts, rep)
            elif kind == "brief":
                # E40: an ASR alias may not stand for a number, sign, negation or direction word, or a
                # negating-prefix variant of its term (it would hide a meaning change from fidelity.py).
                for prob in pc.lexicon_problems(data.get("lexicon")):
                    rep.error("E40", prob)
            elif kind == "facts":
                check_facts_refs(data, rep)
            elif kind == "series":
                check_series(data, args.file, rep, final=args.final)

    ok = not rep.errors
    if args.json:
        print(json.dumps({"file": rep.file, "kind": kind, "schemaEngine": engine, "ok": ok,
                          "errors": len(rep.errors), "warnings": len(rep.warnings), "problems": rep.items,
                          "budget": rep.budget, "length": rep.length}, indent=2))
    else:
        print(f"{rep.file} ({kind or 'unknown'}, schema check: {engine}): {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
        ordered = rep.errors + rep.warnings
        for i, p in enumerate(ordered, 1):
            loc = "/".join(x for x in (p["segment"], p["turn"]) if x) or "-"
            print(f"{i}. {p['level'].upper()} {p['code']} {loc}: {p['message']}")
        if rep.budget:
            b = rep.budget
            print(f"budget: {b['totalWords']} words for a {b['budgetWords']}-word budget ({b['minutes']:g} min); per segment: "
                  + ", ".join(f"{x['id']} {x['words']}/{x['budget']}" for x in b["segments"]))
        if rep.length:
            L = rep.length
            print(f"length: predicted {L['totalSec'] / 60:.2f} min for a {L['targetSec'] / 60:g}-min target (speech {L['speechSec']:.0f} s, "
                  f"holds {L['holdSec']:.0f} s, gaps {L['gapSec']:.0f} s, tails {L['tailSec']:.0f} s, lead {L['leadSec']:.2f} s)")
        print("RESULT: " + ("PASS" if ok else "FAIL") + (" (warnings only)" if ok and rep.warnings else ""))
    return 0 if ok else 1


missing = set(segment_roles()) - set(ROLE_WEIGHTS)
if missing:  # the enum in common.schema.json grew without a weight here
    raise SystemExit(f"validate_script.py: ROLE_WEIGHTS lacks roles {sorted(missing)} from schemas/common.schema.json")

if __name__ == "__main__":
    sys.exit(main())
