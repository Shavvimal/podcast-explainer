"""pe_common.py: helpers shared by the podcast-explainer-video scripts. Standard library only.

Holds the one implementation of:
  - the GEMINI_API_KEY loader (env, else the single variable in the env file: default_env_file()),
    key validation before any header is built, and secret redaction for every log, error,
    report and cache file;
  - identifier rules (slug, turn id, segment id, voice name) and path containment, used at
    every command-line boundary;
  - canonical spoken text (what a host actually says, per audio mode);
  - the audio-fidelity comparison of raw ASR words against the script, in both directions;
  - the visible-text model used by coverage checks and --auto-chips (what is on screen at a given
    time), a Python port of the renderer's visibility rules (see visible_text for the parity list);
  - loudness targets (MONO_LUFS, MONO_TRUE_PEAK), read by tts.py defaults and qc.py fix hints;
  - provenance digests that bind derived files (transcript, learn/) to the script and timing.

Python 3.10 or later. Import it from a script in the same folder: `import pe_common as pc`.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path

# Loudness of the mono episode.wav (references/gemini-tts.md section 10). The ONE place these
# defaults live: tts.py uses them as --lufs and --true-peak defaults, qc.py names them in its hints.
MONO_LUFS = -19.0
MONO_TRUE_PEAK = -4.5

KEY_NAME = "GEMINI_API_KEY"


def default_env_file() -> Path:
    """The dotenv file read when GEMINI_API_KEY is not in the environment: `PODCAST_EXPLAINER_ENV_FILE`
    when set, else `$XDG_CONFIG_HOME/podcast-explainer/env`, else `~/.config/podcast-explainer/env`.
    The file holds the line `GEMINI_API_KEY=...`; other variables in it are ignored."""
    override = os.environ.get("PODCAST_EXPLAINER_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "podcast-explainer" / "env"


ENV_FILE = default_env_file()

# ----------------------------------------------------------------------------------- secrets

# Google API keys are 39 characters of [A-Za-z0-9_-] starting with AIza. The regex also catches
# a key that was never registered (for example one read by another process).
_GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_QUERY_KEY_RE = re.compile(r"(?i)((?:api[_-]?)?key=)[^&\s\"']+")
_HEADER_KEY_RE = re.compile(r"(?i)(x-goog-api-key['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+")
_KEY_OK_RE = re.compile(r"^[A-Za-z0-9_.\-]{8,256}$")
_SECRETS: set[str] = set()
REDACTED = "<redacted>"


class KeyError_(ValueError):
    """A key problem. The message never contains the key, its prefix or its length."""


def register_secret(value: str | None) -> None:
    """Every later redact() call removes this value (and its stripped form)."""
    if value:
        _SECRETS.add(value)
        if value.strip():
            _SECRETS.add(value.strip())


def redact(text) -> str:
    """Remove registered secrets, Google-style keys and key=... query values from any text."""
    s = str(text)
    for sec in sorted(_SECRETS, key=len, reverse=True):
        if sec:
            s = s.replace(sec, REDACTED)
            # also the forms a library may produce in an error message
            s = s.replace(repr(sec)[1:-1], REDACTED)
    s = _GOOGLE_KEY_RE.sub(REDACTED, s)
    s = _QUERY_KEY_RE.sub(lambda m: m.group(1) + REDACTED, s)
    s = _HEADER_KEY_RE.sub(lambda m: m.group(1) + REDACTED, s)
    return s


def redact_obj(obj):
    """redact() applied to every string inside a JSON-like value (for reports and cache metadata)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, dict):
        return {redact(k) if isinstance(k, str) else k: redact_obj(v) for k, v in obj.items()}
    return obj


def parse_env_value(raw: str) -> str:
    """Value part of a dotenv assignment: quoted values may be followed by a comment,
    unquoted values lose an inline ` # comment`."""
    v = raw.strip()
    if v[:1] in ("'", '"'):
        q = v[0]
        end = v.find(q, 1)
        if end > 0:
            rest = v[end + 1:].strip()
            if not rest or rest.startswith("#"):
                return v[1:end]
        # unbalanced quote: fall through and treat as unquoted
    v = re.split(r"\s+#", v, maxsplit=1)[0]
    return v.strip()


def read_env_file(path: Path, name: str = KEY_NAME) -> str | None:
    """The single variable `name` from a dotenv file, parsed in code. Never prints it."""
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for raw in lines:
        m = re.match(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=(.*)$", raw)
        if m:
            val = parse_env_value(m.group(1))
            if val:
                return val
    return None


def validate_key(key: str) -> str:
    """Return the key if it can travel in an HTTP header. The error never shows the key."""
    if not _KEY_OK_RE.match(key or ""):
        raise KeyError_(f"{KEY_NAME} is malformed: it must be one line of letters, digits, '_', '-' or '.', "
                        f"with no spaces, quotes or control characters. Re-export it in your shell; do not paste it into chat.")
    return key


def load_api_key(env_file: Path | None = None) -> tuple[str | None, str]:
    """(key, where) with `where` safe to print. The key is validated and registered for redaction."""
    env_file = env_file or ENV_FILE
    key = os.environ.get(KEY_NAME, "")
    where = f"env {KEY_NAME}"
    if not key.strip():
        key = read_env_file(env_file) or ""
        where = env_file.as_posix().replace(Path.home().as_posix(), "~", 1)
    if not key.strip():
        return None, "not found"
    register_secret(key)
    validate_key(key.strip())
    return key.strip(), where


# ----------------------------------------------------------------------------------- identifiers

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TURN_RE = re.compile(r"^t[0-9]{2,3}$")
SEGMENT_RE = re.compile(r"^seg[0-9]{2}$")
VOICE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")


class BadId(ValueError):
    pass


def check_id(value: str, kind: str) -> str:
    rx = {"slug": SLUG_RE, "turn": TURN_RE, "segment": SEGMENT_RE, "voice": VOICE_RE}[kind]
    if not isinstance(value, str) or not rx.match(value) or (kind == "slug" and len(value) > 60):
        hint = {"slug": "lowercase letters, digits and single hyphens, at most 60 characters (e.g. hash-maps)",
                "turn": "t followed by 2 or 3 digits (e.g. t07)", "segment": "seg followed by 2 digits (e.g. seg03)",
                "voice": "a voice name of letters, digits, '_' or '-' (e.g. Sulafat)"}[kind]
        raise BadId(f"invalid {kind} {value!r}: use {hint}")
    return value


def inside(base: Path, path: Path, what: str = "path") -> Path:
    """Resolve `path` (following symlinks) and require it to stay inside `base`."""
    b = Path(base).resolve()
    p = Path(path).resolve()
    if p != b and b not in p.parents:
        raise BadId(f"{what} {p} is outside {b}; refusing to read or write it")
    return p


def episode_dir(workspace, slug: str) -> Path:
    """Validated <workspace>/<slug> folder (slug rules plus containment, symlinks included)."""
    check_id(slug, "slug")
    ws = Path(workspace).expanduser().resolve()
    return inside(ws, ws / slug, "episode folder")


def safe_path(base, path, what: str = "path") -> Path:
    """`path` as a descendant of the trusted folder `base`, with NO symbolic link anywhere between
    them (the target itself included, when it exists). Use it for every read and write under an
    episode or Remotion folder: audio/, audio/cache/, turn clips, assets. `inside()` resolves links
    first, so a link that points back inside passes it; this refuses every link (C02)."""
    b = Path(base).resolve()
    ap = Path(os.path.abspath(path if Path(path).is_absolute() else Path(base) / path))
    rel = None
    for root in (Path(os.path.abspath(base)), b):
        try:
            rel = ap.relative_to(root)
            break
        except ValueError:
            continue
    if rel is None or ".." in rel.parts:
        raise BadId(f"{what} {ap} is outside {b}; refusing to read or write it")
    cur = b
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise BadId(f"{what}: {cur} is a symbolic link; refusing to follow it (replace it with a real folder or file)")
    return cur


def atomic_write(path, data, base=None, encoding: str = "utf-8") -> Path:
    """Write `data` (str or bytes) to `path` through an EXCLUSIVE temporary file in the same folder,
    then rename it over `path` (C02). The temporary name is new and opened with O_CREAT|O_EXCL, so a
    pre-existing file or symbolic link at a guessable '.tmp' / '.part' name is never written through.
    With `base`, the folder and the target are checked with safe_path (no symbolic link between
    `base` and `path`); without it, the folder and the target must not be symbolic links."""
    import tempfile
    p = Path(path)
    if base is not None:
        p = safe_path(base, p, "output file")
    parent = p.parent
    parent.mkdir(parents=True, exist_ok=True)
    if base is not None:
        safe_path(base, parent, "output folder")
    elif parent.is_symlink():
        raise BadId(f"output folder {parent} is a symbolic link; refusing to write through it")
    if p.is_symlink():
        raise BadId(f"{p} is a symbolic link; refusing to replace it (delete it and rerun)")
    raw = data.encode(encoding) if isinstance(data, str) else bytes(data)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def exclusive_temp(parent, name: str, suffix: str = ".tmp") -> Path:
    """A new, empty, exclusively created file in `parent` (for a tool such as ffmpeg that writes
    its own output). The caller replaces or deletes it. Never reuses an existing path (C02)."""
    import tempfile
    par = Path(parent)
    if par.is_symlink():
        raise BadId(f"folder {par} is a symbolic link; refusing to write through it")
    fd, tmp = tempfile.mkstemp(prefix=f".{name}.", suffix=suffix, dir=str(par))
    os.close(fd)
    return Path(tmp)


# ----------------------------------------------------------------------------------- spoken text

TAG_RE = re.compile(r"<([a-z][a-z \-]*)>")
PIPE_RE = re.compile(r"\|([^|]*)\|")


def spoken_text(text: str, mode: str = "per-turn") -> str:
    """What the active host says. Gemini <tags> are never words. |backchannels| are the other
    host's interjection in chunk mode and are not spoken at all in per-turn mode, so both modes
    remove them from the active host's text."""
    t = TAG_RE.sub(" ", text or "")
    t = PIPE_RE.sub(" ", t)
    t = t.replace("|", " ")
    return re.sub(r"\s+", " ", t).strip()


def backchannels(text: str) -> list[str]:
    return [b.strip() for b in PIPE_RE.findall(text or "") if b.strip()]


def file_sha(path: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:n]


def bytes_sha(data: bytes, n: int = 16) -> str:
    return hashlib.sha256(data).hexdigest()[:n]


# ----------------------------------------------------------------------------------- fidelity

NEGATIONS = {"not", "no", "never", "none", "nothing", "nobody", "nowhere", "neither", "nor", "without", "cannot"}
# A sign word changes a number's meaning: "-5" is "minus 5", and dropping it gives "5" (N03).
SIGNS = {"minus", "plus"}
_ONES = {"zero": 0, "oh": None, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_ONES.pop("oh")
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9}
_ORD = {"first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
        "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "eleventh": "11th", "twelfth": "12th",
        "half": "half", "quarter": "quarter", "negative": "minus"}
_CONTRACT = [(r"\bcan['’]t\b", "can not"), (r"\bwon['’]t\b", "will not"), (r"\bcannot\b", "can not"),
             (r"\bshan['’]t\b", "shall not"), (r"n['’]t\b", " not")]

# Direction words (N03): a substitution between two of these with a different sign on the same
# axis, or between one of these and any other word, changes the meaning ("increases" heard as
# "decreases"). Such a substitution is critical, so the turn fails; it is never a spelling slip.
_AXES = {
    "size": ({"increase", "increases", "increased", "increasing", "grow", "grows", "grew", "growing", "rise", "rises",
              "rising", "higher", "bigger", "larger", "more", "most", "above", "gain", "gains", "max", "maximum",
              "faster", "longer"},
             {"decrease", "decreases", "decreased", "decreasing", "shrink", "shrinks", "shrank", "shrinking", "fall",
              "falls", "falling", "lower", "smaller", "less", "fewer", "least", "fewest", "below", "loss", "min",
              "minimum", "slower", "shorter"}),
    "truth": ({"true", "correct", "always"}, {"false", "incorrect", "wrong", "never"}),
    "time": ({"before", "earlier", "prior"}, {"after", "later"}),
    "place": ({"inside", "include", "includes", "included"}, {"outside", "exclude", "excludes", "excluded"}),
}
DIRECTION: dict[str, tuple[str, int]] = {}
for _axis, (_pos, _neg) in _AXES.items():
    for _w in _pos:
        DIRECTION.setdefault(_w, (_axis, 1))
    for _w in _neg:
        DIRECTION.setdefault(_w, (_axis, -1))


def _words_to_numbers(toks: list[str]) -> list[str]:
    """'twenty five' -> '25', 'three hundred' -> '300'. Two plain numbers in a row stay two
    numbers ('three four' -> '3 4'): a ones word joins only a preceding tens or scale word."""
    out: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] not in _ONES and toks[i] not in _TENS:
            out.append(toks[i])
            i += 1
            continue
        total, cur, last, j = 0, 0, None, i
        while j < len(toks):
            w = toks[j]
            if w in _ONES and last in (None, "tens", "scale"):
                cur += _ONES[w]
                last = "ones"
            elif w in _TENS and last in (None, "scale"):
                cur += _TENS[w]
                last = "tens"
            elif w in _SCALES and last in ("ones", "tens"):
                cur *= _SCALES[w]
                if _SCALES[w] >= 1000:
                    total, cur = total + cur, 0
                last = "scale"
            else:
                break
            j += 1
        if j == i + 1 and toks[i] == "one" and not _number_near(toks, i):
            out.append("one")  # W16 (D12): a lone "one" is a pronoun or determiner, not the digit 1
        else:
            out.append(str(total + cur))
        i = j
    return out


# Units that make a neighbouring "one" a count ("one byte", "one percent").
_UNITS = {"percent", "ms", "millisecond", "milliseconds", "seconds", "minute", "minutes", "hour", "hours", "day", "days",
          "byte", "bytes", "bit", "bits", "kb", "mb", "gb", "tb", "times", "point", "dollar", "dollars", "pound",
          "pounds", "cent", "cents", "x"}


def _number_near(toks: list[str], i: int) -> bool:
    """True when a token within two places of toks[i] is a number word, a digit or a unit."""
    for k in (i - 2, i - 1, i + 1, i + 2):
        if 0 <= k < len(toks):
            w = toks[k]
            if _is_number(w) or w in _ONES or w in _TENS or w in _SCALES or w in _UNITS:
                return True
    return False


def _join_decimals(toks: list[str]) -> list[str]:
    """Spoken decimals become one token, the same token as the digits: 'zero point seven five',
    'point seven five', '0.75' -> '0point75'. Digits after 'point' are read one by one, so every
    following digit token joins (N03)."""
    out: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] == "point" and i + 1 < len(toks) and toks[i + 1].isdigit():
            j = i + 1
            frac = ""
            while j < len(toks) and toks[j].isdigit():
                frac += toks[j]
                j += 1
            whole = out.pop() if out and out[-1].isdigit() else "0"
            out.append(f"{whole}point{frac}")
            i = j
            continue
        out.append(toks[i])
        i += 1
    return out


def fidelity_tokens(text: str) -> list[str]:
    """Normalised word tokens for comparing script and ASR text. Both sides go through the same
    rules: contractions expand (doesn't -> does not), number words become digits, ranges and
    percents are spelled one way ("5-10%" == "5 to 10 percent"), a leading minus sign is the word
    "minus" ("-5" == "minus 5" == "negative 5"), spoken decimals are digits ("zero point seven
    five" == "0.75"), punctuation goes."""
    t = (text or "").lower().replace("’", "'").replace("−", "-")
    for pat, rep in _CONTRACT:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\b([a-z])-one\b", r"\1 1", t)                 # W18: "A-one" is an id, the digit 1 (ASR "A1")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)                 # 1,000 -> 1000
    t = re.sub(r"(?<=\d)\s*[-–—]\s*(?=\d)", " to ", t)         # 100-200 -> 100 to 200
    t = re.sub(r"(?<![\w.])[-–](?=\.?\d)", " minus ", t)        # -5 -> minus 5 (a sign, not a range)
    t = t.replace("%", " percent ").replace("&", " and ").replace("+", " plus ")
    t = re.sub(r"(?<![\d])\.(?=\d)", " point ", t)                # .75 -> point 75
    t = re.sub(r"(?<=\d)\.(?=\d)", " point ", t)                  # 0.75 -> 0 point 75
    t = re.sub(r"'s\b", "s", t)
    t = t.replace("'", "")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    toks = [w for w in t.split() if w]
    toks = [_ORD.get(w, w) for w in toks]
    toks = _words_to_numbers(toks)
    toks = _join_decimals(toks)
    return toks


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i]
        for j in range(1, len(b) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1])))
        prev = cur
    return prev[-1]


def _is_number(w: str) -> bool:
    return any(c.isdigit() for c in w)


# Words that sound exactly like a digit: ASR cannot tell "two" from "to" (2 Nov 2026: script
# "Two seems small", heard "to seem small"). Same sound, so not a fidelity error.
HOMOPHONES = {"2": {"to", "too"}, "4": {"for", "fore"}, "1": {"won", "one"}, "8": {"ate"}}
# Narrow spelling allowances: British/American endings. Nothing else is fuzzy.
_SPELLING_PAIRS = [("our", "or"), ("ise", "ize"), ("ised", "ized"), ("ising", "izing"), ("isation", "ization"),
                   ("yse", "yze"), ("re", "er"), ("ogue", "og"), ("lled", "led"), ("lling", "ling")]
_NEG_PREFIXES = ("un", "in", "im", "il", "ir", "dis", "non", "de", "anti", "mis")
# W16 (W14b D12): a negating prefix counts only on a known stem. "detail"/"tail" and
# "untired"/"tired" (whisper merging "on tired") are coincidences, not negations. Each stem also
# matches with a plain suffix (s, es, d, ed, ing, ly, ion, ions, ity): "connects"/"disconnects".
NEGATABLE_STEMS = frozenset("""
able abled accessible accurate activate activated active agree allowed approve approved authentic authenticated
authorised authorized available aware balanced bounded cached certain changed checked clear common complete
compressed connect connected consistent correct coupled defined deterministic direct enabled encrypted equal even
expected finite formatted frozen important interpreted known legal likely limited linked loaded locked logical
lucky mounted mutable necessary normal official ordered paid parsed possible proven reachable readable regular
related relevant reliable resolved responsive reversible safe secure sensitive signed sorted stable successful
sufficient supported sure synced trusted true typed usual valid validated verified visible wanted
""".split())
_STEM_SUFFIXES = ("", "s", "es", "d", "ed", "ing", "ly", "ion", "ions", "ity")


def _negatable(word: str) -> bool:
    for suf in _STEM_SUFFIXES:
        if suf and not word.endswith(suf):
            continue
        base = word[: len(word) - len(suf)] if suf else word
        if base in NEGATABLE_STEMS or base + "e" in NEGATABLE_STEMS:
            return True
    return False


def _plural_pair(a: str, b: str) -> bool:
    lo, hi = sorted((a, b), key=len)
    return hi in (lo + "s", lo + "es") or (lo.endswith("y") and hi == lo[:-1] + "ies")


def _spelling_pair(a: str, b: str) -> bool:
    for x, y in _SPELLING_PAIRS:
        for p, q in ((a, b), (b, a)):
            if p.endswith(x) and q.endswith(y) and p[: -len(x)] == q[: -len(y)] and len(p) > len(x) + 2:
                return True
    return False


def critical_word(w: str | None) -> bool:
    return bool(w) and (_is_number(w) or w in NEGATIONS or w in SIGNS)


def similar(a: str, b: str) -> bool:
    """Same word for fidelity purposes. Numbers, signs, negations and direction words must match
    exactly, except a digit and its exact-sound homophone. Allowed spelling differences are
    narrow and listed: singular/plural (seem/seems), British/American endings (colour/color,
    normalise/normalize), and one slip in a long word (8+ letters, e.g. ASR 'kubernetis'), never
    when the two words differ by a negating prefix or sit on a direction axis."""
    if a == b:
        return True
    if b in HOMOPHONES.get(a, ()) or a in HOMOPHONES.get(b, ()):
        return True
    if critical_word(a) or critical_word(b) or a in DIRECTION or b in DIRECTION:
        return False
    if negated_pair(a, b):
        return False
    if _plural_pair(a, b) or _spelling_pair(a, b):
        return True
    return min(len(a), len(b)) >= 8 and _lev(a, b) == 1


def meaning_change(s: str, h: str) -> bool:
    """A substitution that changes meaning: a direction word swapped for its opposite or for a
    non-direction word (increase/decrease, true/false, more/less, before/after), or two words that
    differ only by a negating prefix (valid/invalid, authenticated/unauthenticated; B01)."""
    ds, dh = DIRECTION.get(s), DIRECTION.get(h)
    if ds and dh:
        return ds[0] != dh[0] or ds[1] != dh[1]
    if ds or dh:
        return True
    return negated_pair(s, h)


def negated_pair(a: str | None, b: str | None) -> bool:
    """True when one word is the other with a negating prefix: valid/invalid, able/unable,
    authenticated/unauthenticated, connect/disconnect (B01). The base word must be a known
    negatable stem (NEGATABLE_STEMS, W16): detail/tail and untired/tired are not negations."""
    if not a or not b or a == b:
        return False
    for x, y in ((a, b), (b, a)):
        for pre in _NEG_PREFIXES:
            if x == pre + y and len(y) >= 3 and _negatable(y):
                return True
    return False


# ----------------------------------------------------------------------------------- ASR lexicon
#
# brief.json `lexicon` (names and terms ASR mishears, e.g. {"Priya": ["pria", "prayer"]}): a heard
# alias is read as its term before the comparison, so a mishearing of a name is not a warning. An
# alias can never stand for a number, a sign, a negation, a direction word or a negating-prefix
# variant of its term: such aliases are dropped (and validate_script.py reports them), so the
# lexicon cannot hide a meaning change.

def lexicon_problems(lexicon) -> list[str]:
    """Why a brief.json lexicon entry is refused (empty list: all usable)."""
    out = []
    if lexicon is None:
        return out
    if not isinstance(lexicon, dict):
        return ["lexicon must be an object {term: [aliases]}"]
    for term, aliases in lexicon.items():
        if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
            out.append(f"lexicon {term!r}: aliases must be a list of non-empty strings")
            continue
        tt = fidelity_tokens(term)
        if not tt:
            out.append(f"lexicon {term!r}: the term has no word")
        tbad = [w for w in tt if critical_word(w) or w in DIRECTION]
        if tbad:  # Q06 (codex round 4): {"not": ["really"]} would turn "really safe" into "not safe"
            out.append(f"lexicon {term!r}: the term contains {tbad[0]!r} (a number, sign, negation or direction word); "
                       "a lexicon term cannot be a meaning-changing word. A misheard number or negation needs a retake or a "
                       "take-specific fidelity-accept.json entry")
            continue
        for a in aliases:
            at = fidelity_tokens(a)
            bad = [w for w in at if critical_word(w) or w in DIRECTION]
            if at and _split_or_joined(at, tt):
                continue  # W16 (D04): "soft max" for "softmax" is the same word split; it hides no meaning change
            if bad:
                out.append(f"lexicon {term!r}: alias {a!r} contains {bad[0]!r} (a number, sign, negation or direction word); "
                           "an alias cannot stand for a meaning-changing word")
            elif any(negated_pair(x, y) for x in at for y in tt):
                out.append(f"lexicon {term!r}: alias {a!r} is a negating-prefix variant of the term")
            elif not at:
                out.append(f"lexicon {term!r}: alias {a!r} has no word")
    return out


def _split_or_joined(at: list[str], tt: list[str]) -> bool:
    """True when the alias is the term split into words or joined ("soft max" / "softmax")."""
    return at != tt and "".join(at) == "".join(tt) and not any(critical_word(w) for w in at)


def lexicon_map(lexicon) -> list[tuple[list[str], list[str]]]:
    """[(alias tokens, term tokens)], longest alias first; refused aliases are left out."""
    pairs = []
    if not isinstance(lexicon, dict):
        return pairs
    for term, aliases in lexicon.items():
        tt = fidelity_tokens(term)
        if not tt or not isinstance(aliases, list) or any(critical_word(w) or w in DIRECTION for w in tt):
            continue
        for a in aliases:
            if not isinstance(a, str):
                continue
            at = fidelity_tokens(a)
            if at and _split_or_joined(at, tt):
                pairs.append((at, tt))
                continue
            if (not at or any(critical_word(w) or w in DIRECTION for w in at)
                    or any(negated_pair(x, y) for x in at for y in tt)):
                continue
            pairs.append((at, tt))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def apply_lexicon(heard: list[str], pairs) -> list[str]:
    """Replace every heard alias sequence by its term's tokens."""
    if not pairs:
        return heard
    out, i = [], 0
    while i < len(heard):
        for at, tt in pairs:
            if heard[i:i + len(at)] == at:
                out.extend(tt)
                i += len(at)
                break
        else:
            out.append(heard[i])
            i += 1
    return out


def load_lexicon(ep: Path) -> dict:
    """brief.json `lexicon` of an episode folder ({} when absent or unreadable)."""
    p = Path(ep) / "brief.json"
    try:
        lx = json.loads(p.read_text(encoding="utf-8")).get("lexicon") if p.is_file() else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    return lx if isinstance(lx, dict) else {}


def diff_words(script: list[str], heard: list[str]) -> list[tuple[str, str | None, str | None]]:
    """Edit-distance alignment in both directions. Ops: ('ok'|'sub'|'del'|'ins'|'join', script, heard).
    'del' = a script word nobody said; 'ins' = a spoken word that is not in the script;
    'join' = 'hash map' vs 'hashmap' (not an error)."""
    n, m = len(script), len(heard)
    INF = float("inf")
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    P = [[0] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            here = D[i][j]
            if here == INF:
                continue

            def relax(ii, jj, cost, mv):
                if ii <= n and jj <= m and here + cost < D[ii][jj]:
                    D[ii][jj] = here + cost
                    P[ii][jj] = mv

            if i < n and j < m:
                relax(i + 1, j + 1, 0.0 if similar(script[i], heard[j]) else 1.0, 1)
            if i < n:
                relax(i + 1, j, 1.0, 2)
            if j < m:
                relax(i, j + 1, 1.0, 3)
            if i < n and j + 1 < m and script[i] == heard[j] + heard[j + 1]:
                relax(i + 1, j + 2, 0.1, 4)
            if i + 1 < n and j < m and script[i] + script[i + 1] == heard[j]:
                relax(i + 2, j + 1, 0.1, 5)
    ops: list[tuple[str, str | None, str | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        mv = P[i][j]
        if mv == 1:
            a, b = script[i - 1], heard[j - 1]
            ops.append(("ok" if similar(a, b) else "sub", a, b))
            i, j = i - 1, j - 1
        elif mv == 2:
            ops.append(("del", script[i - 1], None))
            i -= 1
        elif mv == 3:
            ops.append(("ins", None, heard[j - 1]))
            j -= 1
        elif mv == 4:
            ops.append(("join", script[i - 1], f"{heard[j - 2]} {heard[j - 1]}"))
            i, j = i - 1, j - 2
        elif mv == 5:
            ops.append(("join", f"{script[i - 2]} {script[i - 1]}", heard[j - 1]))
            i, j = i - 2, j - 1
        else:
            break
    ops.reverse()
    return ops


# Thresholds for one turn (references/qc.md section 2a, audio.fidelity).
FID_FAIL_WER = 0.20
FID_FAIL_MIN_ERRORS = 3


def turn_fidelity(script_text: str, heard_text: str, lexicon=None) -> dict:
    """Compare what the script says with what ASR heard, in both directions.

    status: ok (no difference), warn (small non-critical differences), fail (a number, sign or
    negation differs; a direction word is substituted (increase/decrease, true/false, more/less,
    before/after), deleted or inserted; two words differ by a negating prefix (valid/invalid,
    authenticated/unauthenticated); or 3+ differences and word error rate over 20%).
    `lexicon` is brief.json `lexicon` ({term: [aliases]}): a heard alias counts as its term."""
    a = fidelity_tokens(script_text)
    b = apply_lexicon(fidelity_tokens(heard_text), lexicon_map(lexicon))
    ops = diff_words(a, b)
    subs = [(s, h) for k, s, h in ops if k == "sub"]
    dels = [s for k, s, h in ops if k == "del"]
    ins = [h for k, s, h in ops if k == "ins"]
    critical = []
    for s, h in subs:
        if critical_word(s) or critical_word(h):
            critical.append(f"said '{h}' for '{s}'")
        elif meaning_change(s, h):
            critical.append(f"said '{h}' for '{s}' (meaning changes)")
    for s in dels:
        if critical_word(s):
            critical.append(f"'{s}' missing from the audio")
        elif s in DIRECTION:
            critical.append(f"direction word '{s}' missing from the audio (meaning changes)")
    for h in ins:
        if critical_word(h):
            critical.append(f"extra '{h}' in the audio")
        elif h in DIRECTION:
            critical.append(f"extra direction word '{h}' in the audio (meaning changes)")
    errors = len(subs) + len(dels) + len(ins)
    wer = errors / max(1, len(a))
    if critical or (errors >= FID_FAIL_MIN_ERRORS and wer > FID_FAIL_WER):
        status = "fail"
    elif errors:
        status = "warn"
    else:
        status = "ok"
    return {"status": status, "scriptWords": len(a), "heardWords": len(b), "substitutions": len(subs),
            "deletions": len(dels), "insertions": len(ins), "wer": round(wer, 3), "critical": critical,
            "diff": [{"op": k, "script": s, "heard": h} for k, s, h in ops if k in ("sub", "del", "ins")][:20]}


def canonical_text(text: str) -> str:
    """The expected spoken text an acceptance binds to: spoken_text with whitespace collapsed."""
    return re.sub(r"\s+", " ", spoken_text(text)).strip()


def production_problems(timing: dict) -> list[str]:
    """Why this timing.json cannot be delivered (B02, N04): scratch voices, chunk or experimental
    mode, or estimated / draft alignment. An empty list means a per-turn Gemini take with
    measured word times."""
    out = []
    if timing.get("scratch"):
        out.append("scratch voices (tts.py --scratch): a timing draft, never delivered")
    mode = timing.get("mode", "per-turn")
    if mode != "per-turn":
        out.append(f"audio mode {mode!r}: only per-turn takes can be delivered (chunk mode guesses turn cuts)")
    if timing.get("experimental"):
        out.append("experimental audio (tts.py --experimental)")
    al = timing.get("alignment") or {}
    if al.get("draft"):
        out.append("alignment.draft is true (estimated word times)")
    est = [t.get("id") for t in timing.get("turns", []) if any((w or {}).get("source") == "estimated" for w in t.get("words") or [])]
    if est:
        out.append(f"estimated word times in {len(est)} turn(s) (first {est[0]})")
    if al and al.get("engine", "whisper.cpp") != "whisper.cpp":
        out.append(f"alignment engine {al.get('engine')!r} is not whisper.cpp")
    return out


def _accept_entries(accept: dict | None) -> dict[str, list[dict]]:
    acc: dict[str, list[dict]] = {}
    for a in (accept or {}).get("accept", []) or []:
        if isinstance(a, dict) and a.get("turn"):
            acc.setdefault(a["turn"], []).append(a)
    return acc


def accept_entry_problem(entry: dict, audio_sha: str | None, expected: str) -> str | None:
    """None when a fidelity-accept.json entry resolves this take, else why not (N04). An entry
    binds to the take (audioSha), to the canonical expected text and carries a listen reason."""
    if not entry.get("audioSha") or entry.get("audioSha") != audio_sha:
        return f"acceptance is for take {entry.get('audioSha')!r}, this take is {audio_sha!r}: listen again"
    if canonical_text(entry.get("text", "")) != expected:
        return "acceptance text differs from the current script text (the turn changed): listen again"
    if not str(entry.get("reason", "")).strip():
        return "acceptance has no reason: write what you heard"
    return None


def episode_fidelity(script: dict, timing: dict, accept: dict | None = None, lexicon=None) -> dict:
    """Fidelity for every turn of timing.json that holds raw ASR (turn.asr from align.mjs).

    A fail is resolved only by a new take or by an entry in fidelity-accept.json
    {turn, audioSha, text, reason} that names the take a person listened to and the exact
    canonical text they checked it against. Scratch, chunk, experimental and estimated timing is
    a draft and never ok (production_problems). `lexicon`: brief.json name and term aliases."""
    texts = {t.get("id"): t.get("text", "") for seg in script.get("segments", []) for t in seg.get("turns", [])}
    acc = _accept_entries(accept)
    alignment = timing.get("alignment") or {}
    engine = alignment.get("engine", "none")
    turns, counts = [], {"ok": 0, "warn": 0, "fail": 0, "accepted": 0, "missing": 0, "stale": 0}
    for t in timing.get("turns", []):
        tid = t.get("id")
        rec = {"turn": tid, "audioSha": t.get("audioSha")}
        if t.get("words") and t.get("audioSha") and t.get("alignedAudioSha") and t["alignedAudioSha"] != t["audioSha"]:
            rec.update(status="stale", detail="words were aligned to an older take; rerun align.mjs for this turn")
        elif not isinstance(t.get("asr"), list):
            rec.update(status="missing", detail="no raw ASR for this turn (estimated alignment or align.mjs not run)")
        else:
            heard = " ".join(w.get("text", "") for w in t["asr"])
            expected = canonical_text(texts.get(tid, ""))
            rec.update(turn_fidelity(expected, heard, lexicon))
            rec["heard"] = heard
            rec["expected"] = expected
            if rec["status"] == "fail":
                why = []
                for a in acc.get(tid, []):
                    p = accept_entry_problem(a, t.get("audioSha"), expected)
                    if p is None:
                        rec["status"] = "accepted"
                        rec["acceptedReason"] = a.get("reason", "")
                        break
                    why.append(p)
                if rec["status"] == "fail" and why:
                    rec["acceptProblems"] = why
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
        turns.append(rec)
    rejected = production_problems(timing)
    draft = engine != "whisper.cpp" or counts["missing"] > 0 or bool(rejected)
    blocking = counts["fail"] + counts["stale"]
    return {"engine": engine, "draft": draft, "rejected": rejected, "counts": counts, "blocking": blocking,
            "ok": blocking == 0 and not draft, "turns": turns}


def load_accept(ep: Path) -> dict:
    p = ep / "fidelity-accept.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{p}: invalid JSON at line {e.lineno}: {e.msg}") from e


# ----------------------------------------------------------------------------------- provenance

def json_digest(path: Path) -> str | None:
    """sha256 of a file's bytes, or None when it does not exist."""
    p = Path(path)
    return file_sha(p, 64) if p.is_file() else None


def source_digests(ep: Path) -> dict:
    """What a derived artefact was built from (N06): the digests of script.json, timing.json and
    learn.json at build time. transcript.py writes this into transcript.json `provenance`, learn.py
    into learn/provenance.json; qc.py --final compares them with the current files."""
    return {"script": json_digest(ep / "script.json"), "timing": json_digest(ep / "timing.json"),
            "learn": json_digest(ep / "learn.json")}


# Brief fields that change what the reviewers judge against (R04): readability reference (viewing),
# length target, depth, learner level, the ASR lexicon, the outcome the restate question comes from.
REVIEW_BRIEF_KEYS = ("viewing", "depth", "minutes", "targetMinutes", "learnerLevel", "lexicon", "learnerOutcome",
                     "coreMessage")


def review_brief(brief: dict | None, learn: dict | None = None) -> dict:
    """The canonical review-relevant part of brief.json plus the designated held-out item of
    learn.json (R04, R05). Missing keys are null, so adding one later changes the digest."""
    b = brief if isinstance(brief, dict) else {}
    out = {k: b.get(k) for k in REVIEW_BRIEF_KEYS}
    out["viewing"] = out["viewing"] or "desktop"
    ho = held_out_item(learn)
    out["heldout"] = {k: ho.get(k) for k in ("question", "answer", "level")} if ho else None
    return out


def review_brief_digest(brief: dict | None, learn: dict | None = None) -> str:
    return bytes_sha(json.dumps(review_brief(brief, learn), sort_keys=True, ensure_ascii=False).encode(), 64)


HELD_OUT_LEVELS = ("transfer", "apply", "analyse", "analyze", "create")


def held_out_items(learn: dict | None) -> list[dict]:
    """learn.json selfTest items with heldOut: true (R05)."""
    return [q for q in (learn or {}).get("selfTest", []) or [] if isinstance(q, dict) and q.get("heldOut") is True]


def held_out_item(learn: dict | None) -> dict | None:
    """The ONE designated held-out self-test item, or None (none, or more than one)."""
    items = held_out_items(learn)
    return items[0] if len(items) == 1 else None


# ----------------------------------------------------------------------------------- length budget
#
# One prediction of the final audio length, used by validate_script.py (before any TTS spend) and
# by tts.py --dry-run, so the two agree. It is the same assembly tts.py does: lead, then per turn
# speech + hold + gap (the last turn of a segment gets the tail pad instead of the gap).

SECS_PER_WORD = 0.357           # measured on gemini-3.8-flash-tts, 2 Nov 2026 (references/gemini-tts.md section 13)
DEFAULT_GAP_MS = 250            # tts.py --gap-ms
DEFAULT_TAIL_PAD_MS = 600       # tts.py --tail-pad-ms
DEFAULT_LEAD_MS = 250           # tts.py --lead-ms
LENGTH_ERROR = 0.15             # predicted length more than 15% over the target: error (E39)
LENGTH_WARN = 0.08              # more than 8% over: warning (W39)
_LEN_TAG_RE = re.compile(r"<([^<>]*)>")
_LEN_WORD_RE = re.compile(r"[A-Za-z0-9]")


def speech_secs(text: str) -> float:
    """Spoken seconds of one turn at the measured rate: words, plus <long pause> 2.3 s and
    <short pause> 0.5 s. |backchannels| are not spoken in per-turn mode."""
    plain = PIPE_RE.sub(" ", _LEN_TAG_RE.sub(" ", text or ""))
    words = [w for w in re.split(r"\s+", plain) if _LEN_WORD_RE.search(w)]
    secs = len(words) * SECS_PER_WORD
    for tag in _LEN_TAG_RE.findall(text or ""):
        tag = tag.strip().lower()
        secs += 2.3 if tag == "long pause" else 0.5 if tag == "short pause" else 0.0
    return secs


def predict_length(script: dict, gap_ms: int = DEFAULT_GAP_MS, tail_pad_ms: int = DEFAULT_TAIL_PAD_MS,
                   lead_ms: int = DEFAULT_LEAD_MS) -> dict:
    """Predicted episode.wav length in seconds, with its parts: speech (words x 0.357 s plus
    pause tags), holds (holdAfterMs), gaps (gap_ms after each turn that is not last in its
    segment), tails (tail_pad_ms after the last turn of each segment) and the lead. Same assembly
    as tts.py (per-turn mode)."""
    speech = holds = gaps = tails = 0.0
    turns = 0
    for seg in (script or {}).get("segments", []) or []:
        if not isinstance(seg, dict):
            continue
        ts = [t for t in seg.get("turns", []) or [] if isinstance(t, dict)]
        for i, t in enumerate(ts):
            turns += 1
            speech += speech_secs(t.get("text", "") if isinstance(t.get("text"), str) else "")
            h = t.get("holdAfterMs")
            if isinstance(h, (int, float)) and not isinstance(h, bool) and h > 0:
                holds += h / 1000
            if i == len(ts) - 1:
                tails += tail_pad_ms / 1000
            else:
                gaps += gap_ms / 1000
    total = speech + holds + gaps + tails + lead_ms / 1000
    return {"totalSec": total, "speechSec": speech, "holdSec": holds, "gapSec": gaps, "tailSec": tails,
            "leadSec": lead_ms / 1000, "turns": turns}


def length_verdict(pred: dict, minutes) -> tuple[str, str]:
    """('error' | 'warn' | 'ok' | 'none', message) for a predicted length against targetMinutes."""
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
        return "none", "no target length"
    target = minutes * 60
    off = (pred["totalSec"] - target) / target
    msg = (f"predicted length {pred['totalSec'] / 60:.2f} min is {abs(off):.1%} {'over' if off > 0 else 'under'} the "
           f"{minutes:g}-min target (speech {pred['speechSec']:.0f} s at {SECS_PER_WORD} s per word, holds "
           f"{pred['holdSec']:.0f} s, gaps {pred['gapSec']:.0f} s, segment tails {pred['tailSec']:.0f} s, lead "
           f"{pred['leadSec']:.2f} s)")
    if off > LENGTH_ERROR:
        return "error", msg
    if off > LENGTH_WARN:
        return "warn", msg
    return "ok", msg


MAX_PART_SEC = 12 * 60          # a series part is at most 12 minutes of measured audio (validate_script.py E21)
SERIES_HEADROOM = 0.05          # a series part's PREDICTION stays 5% under that cap (684 s): planning headroom (Q08)


def length_check(script: dict, minutes=None, gap_ms: int = DEFAULT_GAP_MS, tail_pad_ms: int = DEFAULT_TAIL_PAD_MS,
                 lead_ms: int = DEFAULT_LEAD_MS) -> dict:
    """THE length gate (codex round 4, Q08), shared by validate_script.py (E39/W39), tts.py --dry-run
    and the paid tts.py path, so the three cannot disagree. Returns {pred, verdict, problems}:
    problems is a list of (level 'error'|'warn', code, message). Errors: predicted length more than
    15% over the target; a series part (script.series set) predicted over 12 min minus 5% headroom,
    because the strict series check rejects measured audio over 12 min and that is knowable before
    any payment."""
    if minutes is None:
        minutes = (script or {}).get("targetMinutes")
    pred = predict_length(script, gap_ms, tail_pad_ms, lead_ms)
    verdict, msg = length_verdict(pred, minutes)
    problems = []
    if verdict == "error":
        problems.append(("error", "E39", f"{msg}; more than {LENGTH_ERROR:.0%} over: cut words (or holds) before paying for audio"))
    elif verdict == "warn":
        problems.append(("warn", "W39", f"{msg}; more than {LENGTH_WARN:.0%} over: trim before paying for audio"))
    if isinstance((script or {}).get("series"), dict):
        cap = MAX_PART_SEC * (1 - SERIES_HEADROOM)
        if pred["totalSec"] > cap:
            problems.append(("error", "E39", f"series part: predicted length {pred['totalSec']:.1f} s ({pred['totalSec'] / 60:.2f} min) is over "
                             f"the {cap:.0f}-s planning cap ({MAX_PART_SEC // 60} min minus {SERIES_HEADROOM:.0%} headroom); the "
                             f"series check rejects a part over {MAX_PART_SEC // 60} min of measured audio. Cut words or move a "
                             "segment to the next part before paying for audio"))
    worst = "error" if any(p[0] == "error" for p in problems) else "warn" if problems else verdict
    return {"pred": pred, "verdict": worst, "problems": problems, "minutes": minutes}


# Delivered derivatives (N06): every searchable or delivered copy transcript.py writes, keyed by
# its path relative to the workspace. transcript.py records their sha256 in <slug>/delivery.json;
# qc.py --final re-reads every file and fails on a missing, stale or edited one.
DELIVERY_FILE = "delivery.json"


RECORD_UNBOUND_KEYS = ("openGaps",)   # gaplog.md is the learner's to edit; its open-gap count is not part of the delivery


def record_digest(record: dict | None) -> str | None:
    """sha256 of ONE episode's library/index.json record (Q04), canonical JSON, without the keys
    the learner changes after delivery (openGaps). transcript.py binds it into delivery.json; qc.py --final
    recomputes the record from the current inputs and compares both."""
    if not isinstance(record, dict):
        return None
    canon = {k: v for k, v in record.items() if k not in RECORD_UNBOUND_KEYS}
    return bytes_sha(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode(), 64)


def delivery_paths(ws: Path, slug: str, mp4: Path | None) -> dict[str, Path]:
    """name -> path of every derivative transcript.py writes for one episode."""
    ep = Path(ws) / slug
    out = {"transcript.md": ep / "transcript.md", "transcript.json": ep / "transcript.json",
           "captions.vtt": ep / "captions.vtt", "captions.srt": ep / "captions.srt",
           "chapters.ffmetadata": ep / "chapters.ffmetadata", "library": Path(ws) / "library" / f"{slug}.md"}
    if mp4 is not None:
        m = Path(mp4)
        out["sidecar.srt"] = m.with_suffix(".srt")
        out["sidecar.vtt"] = m.with_suffix(".vtt")
        if (m.parent / "transcript.md").resolve() != (ep / "transcript.md").resolve():
            out["sidecar.transcript.md"] = m.parent / "transcript.md"
    return out


# ----------------------------------------------------------------------------------- count claims (Q05)

_CLAIM_X_OF_Y_RE = re.compile(r"(?<![\d.])(\d+)\s+of\s+(\d+)(?![\d.])")     # qc.py X_OF_Y_RE
_CLAIM_NUM_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?!\w)")              # qc.py NUM_RE
_NONE_RE = re.compile(r"\b(none|no|zero|nothing)\b", re.I)
_ALL_RE = re.compile(r"\b(all|every|each)\b", re.I)


def claim_text_problem(text: str, claim: dict) -> str | None:
    """Q05 (codex round 4): the displayed text must say what its structured count claim says. A
    claim is checked against the table, and its text is checked against the claim: 'X of Y' must be
    value of of; a bare number must be the value; 'none'/'no' means 0 and 'all' means of. Text with
    no supported numeric wording returns None (nothing to compare; the claim stands)."""
    if not isinstance(text, str):
        return None
    if not isinstance(claim, dict):
        return (f"text '{text}' uses a {{value}}, {{of}} or {{to}} placeholder but has no claim"
                if _PLACEHOLDER_RE.search(text) else None)
    if claim.get("kind") != "count":
        return None
    text = claim_fill(text, claim)
    val, of = claim.get("value"), claim.get("of")
    m = _CLAIM_X_OF_Y_RE.search(text)
    if m:
        x, y = int(m.group(1)), int(m.group(2))
        if x != val or (of is not None and y != of):
            return f"text says '{m.group(0)}' but its claim says {val} of {of if of is not None else '?'}"
        return None
    nums = [int(float(n.replace(",", ""))) for n in _CLAIM_NUM_RE.findall(text)]
    if nums:
        return None if val in nums else f"text shows {', '.join(map(str, nums))} but its claim value is {val}"
    if _NONE_RE.search(text) and val != 0:
        return f"text says none but its claim value is {val}"
    if _ALL_RE.search(text) and of is not None and val != of:
        return f"text says all but its claim says {val} of {of}"
    return None



_PLACEHOLDER_RE = re.compile(r"\{(value|of|to)\}")


def claim_fill(text, claim) -> str:
    """compareState.ts claimText (W13b): {value}, {of} and {to} in a label are filled from its count
    claim; without a claim the text is shown as written."""
    if not isinstance(text, str) or not isinstance(claim, dict):
        return text
    of = claim.get("of")
    return (text.replace("{value}", _js_str(claim.get("value")))
            .replace("{of}", "undefined" if of is None else _js_str(of)).replace("{to}", str(claim.get("to") or "")))


def claim_texts(obj, where: str = "") -> list[tuple[str, str, dict | None]]:
    """Every (where, text, claim) pair in scenes or overlays: a stat object, a banner or verdict, chip
    props; and every text with a {value}/{of}/{to} placeholder but no claim (claim None)."""
    out = []
    if isinstance(obj, dict):
        if isinstance(obj.get("text"), str) and (isinstance(obj.get("claim"), dict) or _PLACEHOLDER_RE.search(obj["text"])):
            out.append((where, obj["text"], obj.get("claim") if isinstance(obj.get("claim"), dict) else None))
        if isinstance(obj.get("stat"), str) and _PLACEHOLDER_RE.search(obj["stat"]):
            out.append((f"{where}.stat" if where else "stat", obj["stat"], None))
        for k, v in obj.items():
            out += claim_texts(v, f"{where}.{k}" if where else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += claim_texts(v, f"{where}[{i}]")
    return out


# ----------------------------------------------------------------------------------- visible text
#
# Parity with the renderer (templates/remotion/src). This section is the ONE Python copy of the
# rules that decide what is on screen; qc.py coverage and build_manifest.py --auto-chips both call
# visible_text(). It is a line-for-line port of src/visibleText.ts (rules: references/visuals.md
# section 11). tests/test_w9.py VisibleTextParity runs both on shared fixtures at many times and
# asserts the same texts. Keep each function in step with its TypeScript twin:
#
#   ms_to_frame, cue_frame,     frames.ts msToFrame, cueFrame (LEAD_FRAMES 3: state changes land 3
#   answer_frame, parse_lines              frames early), answerFrame (results: zero lead, never
#                                          without a cue), parseLines
#   world_timeline              worldState.ts buildTimeline (world scenes, custom worldSteps, compare
#                                          panels with world "shared"; untimed step i at scene
#                                          start + i * 1500 ms)
#   local_timeline              worldState.ts localTimeline (a compare panel's own world)
#   world_visible_ids           worldState.ts visibilityAt (revealAtMs, then hide / reveal steps in
#                                          time order; a hide and a reveal at one time: hide first)
#   node_overrides              worldState.ts nodeOverrides (`set` label / value patches up to now)
#   ring_inset_filter           worldState.ts ringInsetFilter (inset views of a ring world)
#   world_texts_at              visibleText.ts worldTextsAt (reveal, hide and set from now + 3 frames;
#                                          the latest step's note from now; tint has no text effect)
#   banner_at                   compareState.ts bannerAt (verdict + banners[] one list, the latest
#                                          whose answer frame has passed; text "" shows nothing)
#   panel_state_at              compareState.ts panelStateAt (title, tag, stat inherited from the
#                                          latest result; tag "" hides, stat "" clears; table fill
#                                          shows "?" until the cell's fill result; rows and lines
#                                          from their atMs; untimed step i at frame 15 + 45 i)
#   _props_texts                visibleText.ts propsTexts (custom scenes)
#   scene_texts_at              visibleText.ts sceneTextsAt (title question at frame 45, recap point
#                                          i at 12 + 30 i, equation / code / diagram step i at
#                                          15 + 45 i; diagram element at its FIRST reveal step)
#   visible_texts_at            visibleText.ts visibleTextsAt (active scenes + chip overlays)
#   visible_text                Python only: the union of visible_texts_at over every frame of a
#                                          window at which the texts can change
#   resolve_steps               worldState.ts resolveSteps (W13b marks expire: focus, focusEdges,
#                                          arcs, tint end at the next step unless persist; walk
#                                          arrows end at the next step or turnEndMs, min 1500 ms)
#   ownership_at, change_visible worldState.ts ownershipAt, changeVisible (change band and moved
#                                          outlines until the next step unless persist "change")
#   world_marks_at, marks_at    worldState.ts worldMarksAt, visibleText.ts marksAt
#   world_label_sources,        visibleText.ts worldLabelSources and the node part of
#   node_label_sources_at                  labelSourcesAt (W13b: expires false for base labels)
#
# A change to one of those TypeScript functions needs the same change here; the parity test fails
# until it is made.

LEAD_FRAMES = 3                 # motionConstants.ts LEAD_FRAMES
STEP_FALLBACK_START = 15        # motionConstants.ts STEP_FALLBACK_START (frames)
STEP_FALLBACK_FRAMES = 45       # motionConstants.ts STEP_FALLBACK_FRAMES
STEP_FALLBACK_MS = 1500         # worldState.ts STEP_FALLBACK_MS (world timeline, ms)
_SKIP_KEYS = {"component", "language", "svg", "viewBox", "worldSteps"}
_INF = float("inf")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _js_round(x: float) -> int:
    """Math.round: halves round up (towards +infinity)."""
    return int(math.floor(x + 0.5))


def ms_to_frame(ms: float, fps: float) -> int:
    return _js_round((ms / 1000) * fps)


def cue_frame(at_ms, fallback_local: int, from_frame: int, fps: float, lead: int = LEAD_FRAMES) -> int:
    return fallback_local if not _num(at_ms) else ms_to_frame(at_ms, fps) - from_frame - lead


def answer_frame(at_ms, from_frame: int, fps: float):
    return None if not _num(at_ms) else ms_to_frame(at_ms, fps) - from_frame


def _parse_int(s: str):
    m = re.match(r"\s*([+-]?\d+)", s)
    return int(m.group(1)) if m else None


def parse_lines(spec) -> set[int]:
    out: set[int] = set()
    if spec is None:
        return out
    if isinstance(spec, list):
        return set(spec)
    for part in str(spec).split(","):
        bits = part.split("-")
        a = _parse_int(bits[0].strip())
        if a is None:
            continue
        b = _parse_int(bits[1].strip()) if len(bits) > 1 else None
        end = a if b is None else b
        out.update(range(a, end + 1))
    return out


def _fallback(i: int) -> int:
    return STEP_FALLBACK_START + i * STEP_FALLBACK_FRAMES


def _js_str(v) -> str:
    """String(number) for the numbers JSON gives: 3.0 is "3"."""
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e21:
        return str(int(v))
    return str(v)


def _step_time(st: dict, start: float, i: int) -> float:
    return st["atMs"] if _num(st.get("atMs")) else start + i * STEP_FALLBACK_MS


def turn_ends(manifest: dict) -> dict[str, float]:
    """worldState.ts turnEnds (W13b): end of each turn's speech plus its hold, by turn id (a walk
    arrow ends there)."""
    return {t.get("id"): t.get("endMs", 0) + (t.get("holdAfterMs") or 0) for t in manifest.get("turns") or []}


def _timed(st: dict, i: int, scene_id, start: float, ends: dict | None) -> dict:
    """worldState.ts timed: the step with its time `t`, scene id and, when its `at.turn` is known,
    `turnEndMs`."""
    out = {**st, "t": _step_time(st, start, i), "sceneId": scene_id}
    turn = (st.get("at") or {}).get("turn") if isinstance(st.get("at"), dict) else None
    if turn and ends and ends.get(turn) is not None:
        out["turnEndMs"] = ends[turn]
    return out


def world_timeline(manifest: dict) -> list[dict]:
    """Every step that acts on the episode world, in time order (buildTimeline)."""
    out = []
    ends = turn_ends(manifest)
    for sc in manifest.get("scenes", []):
        props = sc.get("props") or {}
        lists = []
        if sc.get("type") == "world":
            lists = [props.get("steps") or []]
        elif sc.get("type") == "custom" and isinstance(props.get("worldSteps"), list):
            lists = [props["worldSteps"]]
        elif sc.get("type") == "compare":
            for side in ("left", "right"):
                panel = props.get(side) or {}
                if panel.get("kind") == "world" and panel.get("world") == "shared":
                    lists.append(panel.get("steps") or [])
        for steps in lists:
            for i, st in enumerate(steps):
                out.append(_timed(st, i, sc.get("id"), sc.get("startMs", 0), ends))
    out.sort(key=lambda x: x["t"])
    return out


def local_timeline(steps: list[dict], scene_id: str, start: float, ends: dict | None = None) -> list[dict]:
    """worldState.ts localTimeline (a compare panel with its own world)."""
    return sorted((_timed(st, i, scene_id, start, ends) for i, st in enumerate(steps or [])), key=lambda x: x["t"])


def world_visibility(world: dict, timeline: list[dict], now: float) -> dict[str, tuple[bool, float]]:
    """visibilityAt: id -> (on, since) for every node and edge. A step reveal of an item that is
    already on keeps the earlier reveal (its `since`)."""
    items = (world.get("nodes") or []) + (world.get("edges") or [])
    out = {x["id"]: (False, -_INF) for x in items}
    ev = []
    for x in items:
        r = x.get("revealAtMs")
        ev.append((r if _num(r) else -_INF, x["id"], True))
    for st in timeline:
        ev += [(st["t"], i, False) for i in st.get("hide") or []]
        ev += [(st["t"], i, True) for i in st.get("reveal") or []]
    ev.sort(key=lambda e: (e[0], e[2]))
    for t, xid, flag in ev:
        if t > now:
            break
        if xid not in out:
            continue
        if flag and out[xid][0]:
            continue
        out[xid] = (flag, t)
    return out


def world_visible_ids(world: dict, timeline: list[dict], now: float) -> set[str]:
    """Ids of nodes and edges on screen at `now` (visibilityAt)."""
    return {k for k, (on, _) in world_visibility(world, timeline, now).items() if on}


def next_step_after(timeline: list[dict], t: float) -> float:
    """worldState.ts nextStepAfter: time of the first step strictly after t (inf if none)."""
    for st in timeline:
        if st["t"] > t:
            return st["t"]
    return _INF


def node_overrides(timeline: list[dict], now: float) -> dict[str, dict]:
    """worldState.ts nodeOverrides (W11b stale labels): a `set` patch's value and label show until
    the next step on the same timeline, unless the patch has persist; the latest patch wins, and an
    expired one leaves no value (never an older one). color never expires."""
    out: dict[str, dict] = {}
    for st in timeline:
        if st["t"] > now:
            break
        live = next_step_after(timeline, st["t"]) > now
        for nid, patch in (st.get("set") or {}).items():
            patch = patch or {}
            o = out.setdefault(nid, {"changedAt": -_INF})
            if patch.get("color") is not None:
                o["color"] = patch["color"]
            keep = live or bool(patch.get("persist"))
            if patch.get("value") is not None:
                o["valueSet"] = True
                o["value"] = patch["value"] if keep else None
            if patch.get("label") is not None:
                o["labelSet"] = True
                o["label"] = patch["label"] if keep else None
            if keep and (patch.get("value") is not None or patch.get("label") is not None):
                o["changedAt"] = st["t"]
    return out


def node_text_at(n: dict, vis, over, timeline: list[dict], now: float) -> tuple:
    """worldState.ts nodeTextAt: (label, value) a visible node draws. The node's own value shows
    from its reveal until the next step after it unless the node has persist, and never after a
    `set` gave the node a value."""
    over = over or {}
    label = (over.get("label") if over.get("label") is not None else n.get("label")) if over.get("labelSet") else n.get("label")
    if over.get("valueSet"):
        return label, over.get("value")
    if n.get("value") is None:
        return label, None
    since = vis[1] if vis and vis[0] else -_INF
    own = bool(n.get("persist")) or next_step_after(timeline, since) > now
    return label, (n["value"] if own else None)


# Ring and node geometry (worldState.ts), for the inset filter of compare world panels.
RING_DEFAULTS = {"owner": 96, "item": 72}
NODE_DEFAULTS = {"box": (280, 120), "pill": (260, 88), "circle": (160, 160)}
CHAR_W = 0.62


def world_size(world: dict) -> tuple[float, float]:
    return world.get("width") or 1728, world.get("height") or 712


def ring_geometry(world: dict):
    ring = world.get("ring")
    if world.get("layout") != "ring" or not ring:
        return None
    W, H = world_size(world)
    return {"cx": ring.get("cx") if ring.get("cx") is not None else W / 2,
            "cy": ring.get("cy") if ring.get("cy") is not None else H / 2,
            "r": ring.get("r") if ring.get("r") is not None else _js_round(0.31 * min(W, H)),
            "positions": ring.get("positions")}


def _node_angle(n: dict, g: dict):
    if n.get("angle") is not None:
        return n["angle"]
    if n.get("pos") is not None:
        return n["pos"] * 360 / g["positions"]
    return None


def place_nodes(world: dict) -> list[dict]:
    g = ring_geometry(world)
    nodes = world.get("nodes") or []
    if not g:
        return nodes
    out = []
    for n in nodes:
        a = _node_angle(n, g)
        if a is None:
            out.append(n)
            continue
        r = g["r"] + (n.get("ringOffset") or 0)
        rad = a * math.pi / 180
        out.append({**n, "x": g["cx"] + r * math.sin(rad), "y": g["cy"] - r * math.cos(rad)})
    return out


def node_size(n: dict) -> tuple[float, float]:
    if n.get("role") and n.get("shape") is None:
        d = n.get("w") if n.get("w") is not None else RING_DEFAULTS[n["role"]]
        return d, d
    shape = n.get("shape") or "box"
    dw, dh = NODE_DEFAULTS[shape]
    w = n.get("w") if n.get("w") is not None else dw
    grow = 0 if n.get("value") is None or shape == "circle" else ((160 - dh if n.get("sublabel") else 40) if shape == "pill" else 40)
    h = n.get("h") if n.get("h") is not None else dh + grow   # W16 (D15): pills grow for a value line too
    return w, (w if shape == "circle" else h)


# WorldScene.tsx node text (full-stage world, minFont = type.min): title type.label + 4 at line height
# 1.1, sublabel type.min at 1.1 with a 4 px gap, value type.body + 2 at about 1.2 with a 6 px gap, 12 px
# vertical padding and a 3 px border each side. Used by qc.py world.nodefit (W16, W14b D15).
NODE_TEXT = {"title": 34, "sub": 28, "value": 38, "pad": 12, "border": 6, "slack": 4}


def node_text_height(n: dict, has_value: bool) -> float:
    t = NODE_TEXT
    return (t["title"] * 1.1 + (4 + t["sub"] * 1.1 if n.get("sublabel") else 0)
            + (6 + t["value"] * 1.2 if has_value else 0) + t["pad"] + t["border"])


def node_fit_problems(world: dict, timeline: list[dict]) -> list[str]:
    """Box, pill and circle nodes whose label, sublabel and value (own or from any `set`) need more
    height than the node draws: the value overlaps the sublabel or spills out (W14b D15)."""
    out = []
    for n in world.get("nodes") or []:
        if n.get("role") and n.get("shape") is None:
            continue  # ring discs: one label, sized by ring rules
        has_value = n.get("value") is not None or any(((st.get("set") or {}).get(n["id"]) or {}).get("value") is not None
                                                      for st in timeline)
        _, h = node_size({**n, **({"value": n.get("value") or ""} if has_value else {})})
        need = node_text_height(n, has_value)
        if need > h + NODE_TEXT["slack"]:
            parts = "label" + (", sublabel" if n.get("sublabel") else "") + (" and value" if has_value else "")
            out.append(f"node {n['id']} ({n.get('shape') or 'box'}): {parts} need {need:.0f} px but the node is {h:.0f} px tall; "
                       f"drop the explicit h, drop the sublabel, or show the value in another node")
    return out


def ring_tracks(world: dict) -> dict:
    g = ring_geometry(world)

    def of(role):
        n = next((x for x in world.get("nodes") or [] if x.get("role") == role and (x.get("pos") is not None or x.get("angle") is not None)), None)
        return g["r"] + (n.get("ringOffset") or 0) if g and n else None
    return {"owner": of("owner"), "item": of("item")}


def ring_face_radius(world: dict):
    g = ring_geometry(world)
    if not g:
        return None
    t = ring_tracks(world)
    item = next((x for x in world.get("nodes") or [] if x.get("role") == "item"), None)
    item_edge = (t["item"] if t["item"] is not None else g["r"]) + (node_size(item)[0] / 2 if item else 0) + 20
    return t["owner"] if t["owner"] is not None and t["owner"] > item_edge - 20 else max(g["r"] + 20, item_edge)


def fit_camera(world: dict, w: float, h: float, pad: float = 24) -> dict:
    nodes = place_nodes(world)
    ring = ring_geometry(world)
    pick = [n for n in nodes if n.get("pos") is not None or n.get("angle") is not None] if ring else nodes
    lst = pick or nodes
    x0 = y0 = _INF
    x1 = y1 = -_INF
    for n in lst:
        sw, sh = node_size(n)
        x0, x1 = min(x0, n["x"] - sw / 2 - 14), max(x1, n["x"] + sw / 2 + 14)
        y0, y1 = min(y0, n["y"] - sh / 2 - 14), max(y1, n["y"] + sh / 2 + 14)
    if ring:
        face = (ring_face_radius(world) or ring["r"]) + 4
        x0, x1 = min(x0, ring["cx"] - face), max(x1, ring["cx"] + face)
        y0, y1 = min(y0, ring["cy"] - face), max(y1, ring["cy"] + face)
    W, H = world_size(world)
    fit = min(w / W, h / H)
    scale = min((w - 2 * pad) / (x1 - x0), (h - 2 * pad) / (y1 - y0))
    return {"x": (x0 + x1) / 2, "y": (y0 + y1) / 2, "zoom": scale / fit}


def view_scale(world: dict, w: float, h: float, camera: dict) -> float:
    W, H = world_size(world)
    return min(w / W, h / H) * camera.get("zoom", 1)


def ring_inset_filter(world: dict, scale=None):
    """worldState.ts ringInsetFilter: in an inset view of a ring world only ring nodes and nodes
    inside the ring; with `scale`, a free node inside the ring only when its label fits inside the
    item ring at 28 px or more."""
    g = ring_geometry(world)
    if not g:
        return None
    item = next((x for x in world.get("nodes") or [] if x.get("role") == "item"), None)
    t = ring_tracks(world)["item"]
    inner = 2 * ((t if t is not None else g["r"]) - (node_size(item)[0] / 2 if item else 0)) - 16

    def keep(n: dict) -> bool:
        if n.get("pos") is not None or n.get("angle") is not None:
            return True
        x, y = n.get("x"), n.get("y")
        if not (_num(x) and _num(y)) or math.hypot(x - g["cx"], y - g["cy"]) >= g["r"]:
            return False
        if scale is None:
            return True
        font = max(34, 28 / scale)
        return max(node_size(n)[0], len(str(n.get("label") or "")) * font * CHAR_W + 32) <= inner
    return keep


def walk_item(w) -> str:
    """worldState.ts walkItem: a walk entry is an item id or {item, to?, overshoot?}."""
    return w if isinstance(w, str) else (w or {}).get("item")


def owners_at(nodes: list[dict], g: dict, visible: set[str]) -> dict[str, str | None]:
    """worldState.ts ownersAt: each item belongs to the first visible owner at or clockwise after it."""
    owners = [(n["id"], _node_angle(n, g)) for n in nodes if n.get("role") == "owner" and n["id"] in visible]
    owners = [(i, a) for i, a in owners if a is not None]
    out: dict[str, str | None] = {}
    for n in nodes:
        if n.get("role") != "item":
            continue
        a = _node_angle(n, g)
        if a is None or not owners:
            out[n["id"]] = None
            continue
        best = None
        for oid, oa in owners:
            d = ((oa - a) % 360 + 360) % 360
            if best is None or d < best[1] - 1e-9:
                best = (oid, d)
        out[n["id"]] = best[0]
    return out


def ring_problems(world: dict) -> list[str]:
    """worldState.ts ringProblems: every owner shares one ringOffset, every item shares one."""
    if not ring_geometry(world):
        return []
    out = []
    for role in ("owner", "item"):
        offs = []
        for n in world.get("nodes") or []:
            if n.get("role") == role and (n.get("pos") is not None or n.get("angle") is not None):
                o = n.get("ringOffset") or 0
                if o not in offs:
                    offs.append(o)
        if len(offs) > 1:
            out.append(f"ring {role} nodes use ringOffset {', '.join(_js_str(o) for o in offs)}; give every {role} the same "
                       f"ringOffset so they sit on one circle")
    return out


def walk_problems(world: dict, timeline: list[dict]) -> list[str]:
    """worldState.ts walkProblems: a walk arrow ends at the item's successor (the first visible owner
    clockwise, at the step time) unless `to` names another owner with overshoot: true."""
    g = ring_geometry(world)
    if not g:
        return []
    nodes = place_nodes(world)
    out = []
    for st in timeline:
        if not st.get("walk"):
            continue
        live = owners_at(nodes, g, world_visible_ids(world, timeline, st["t"]))
        for w in st["walk"]:
            item = walk_item(w)
            succ = live.get(item)
            to = None if isinstance(w, str) else (w or {}).get("to")
            over = not isinstance(w, str) and bool((w or {}).get("overshoot"))
            target = to if to is not None else succ
            if target is not None and (target == succ or over):
                continue
            if succ is None:
                out.append(f"walk of {item} at {_js_round(st['t'])} ms (scene {st.get('sceneId')}): no visible owner on the ring, "
                           "so the arrow has no end")
            else:
                out.append(f"walk of {item} at {_js_round(st['t'])} ms (scene {st.get('sceneId')}) ends at {target}, but its successor "
                           f"is {succ}; point it at {succ}, or set \"overshoot\": true if the walk passes {succ} on purpose")
    return out


def persists(st: dict | None, kind: str) -> bool:
    """worldState.ts persists (W13b): the step keeps a mark of this kind past the next step."""
    if not st:
        return False
    p = st.get("persist")
    return p is True or (isinstance(p, list) and kind in p)


WALK_MIN_MS = 1500   # worldState.ts WALK_MIN_MS: shortest time a walk arrow stays
WALK_MS = 900        # worldState.ts WALK_MS: an item walked before colouring starts colours after this
MARK_KINDS = ("focus", "focusEdges", "arcs", "change", "tint", "walk")


def resolve_steps(timeline: list[dict], world: dict | None = None) -> list[dict]:
    """worldState.ts resolveSteps (W13b, marks expire): per step, the marks the world draws.

    focus, focusEdges, arcs and tint are a mark for one step: a step that omits one shows none,
    unless the step that set it has persist (true, or a list naming the kind); then it stays until
    a later step sets that kind. [] (or {} for tint) always clears. camera inherits. flow, pulse and
    note belong to their own step. A walk arrow shows from its step until the next step or until
    turnEndMs (end of its anchor turn plus the hold), whichever is first, but at least WALK_MIN_MS;
    with persist "walk" it stays until a later step walks."""
    focus = (set(), False)
    edges = (set(), False)
    W, H = world_size(world or {})
    camera = {"x": W / 2, "y": H / 2, "zoom": 1, **((world or {}).get("camera") or {})}   # initialCamera
    arcs = ([], False)
    arcs_at = -_INF
    tint = ({}, False)
    walk = {"v": [], "keep": False, "at": -_INF, "until": _INF}
    out = []
    for st in timeline:
        if st.get("tint") is not None:
            m = {}
            for cls, ids in (st["tint"] or {}).items():
                for i in ids or []:
                    m[i] = cls
            tint = (m, persists(st, "tint"))
        elif not tint[1]:
            tint = ({}, False)
        if st.get("focus") is not None:
            focus = (set(st["focus"]), persists(st, "focus"))
        elif not focus[1]:
            focus = (set(), False)
        if st.get("focusEdges") is not None:
            edges = (set(st["focusEdges"]), persists(st, "focusEdges"))
        elif not edges[1]:
            edges = (set(), False)
        if st.get("camera"):
            camera = {**camera, **st["camera"]}
        if st.get("arcs") is not None:
            arcs = (st["arcs"], persists(st, "arcs"))
            arcs_at = st["t"]
        elif not arcs[1]:
            arcs = ([], False)
        if st.get("walk") is not None:
            keep = persists(st, "walk")
            te = st.get("turnEndMs")
            until = _INF if keep or te is None else max(te, st["t"] + WALK_MIN_MS)
            walk = {"v": st["walk"], "keep": keep, "at": st["t"], "until": until}
        elif not walk["keep"]:
            walk = {"v": [], "keep": False, "at": -_INF, "until": _INF}
        out.append({"t": st["t"], "sceneId": st.get("sceneId"), "focus": focus[0], "focusEdges": edges[0], "camera": camera,
                    "flow": set(st.get("flow") or []), "pulse": set(st.get("pulse") or []),
                    "walk": walk["v"], "walkAt": walk["at"], "walkUntil": walk["until"],
                    "arcs": arcs[0], "arcsSetAt": arcs_at, "tint": tint[0],
                    "speaksOf": set(st.get("speaksOf") or []), "note": st.get("note")})
    return out


def resolve_focus(timeline: list[dict]) -> list[dict]:
    """The focus part of resolve_steps (kept for callers that need only focus and speaksOf)."""
    return resolve_steps(timeline)


def freeze_intervals(timeline: list[dict]) -> list[tuple[float, float]]:
    """worldState.ts freezeIntervals: [start, end) from steps with freeze true / false."""
    out, open_ = [], None
    for st in timeline:
        if st.get("freeze") is True and open_ is None:
            open_ = st["t"]
        if st.get("freeze") is False and open_ is not None:
            out.append((open_, st["t"]))
            open_ = None
    if open_ is not None:
        out.append((open_, _INF))
    return out


def _effective(t: float, freezes) -> float:
    for a, b in freezes:
        if a <= t < b:
            return a - 0.5
    return t


def owner_change_times(world: dict, timeline: list[dict], now: float, freezes) -> list[float]:
    """worldState.ts ownerChangeTimes: owner reveals and hides outside a freeze, and the end of every
    freeze that held one, up to now."""
    owner_ids = {n["id"] for n in world.get("nodes") or [] if n.get("role") == "owner"}
    raw = [n["revealAtMs"] for n in world.get("nodes") or [] if n["id"] in owner_ids and n.get("revealAtMs") is not None]
    for st in timeline:
        if any(i in owner_ids for i in (st.get("hide") or []) + (st.get("reveal") or [])):
            raw.append(st["t"])
    ts = set()
    for t in raw:
        f = next(((a, b) for a, b in freezes if a <= t < b), None)
        at = f[1] if f else t
        if at <= now:
            ts.add(at)
    return sorted(ts)


def _on_ids(vis: dict) -> set[str]:
    return {k for k, (on, _) in vis.items() if on}


def ownership_at(world: dict, nodes: list[dict], timeline: list[dict], now: float) -> dict | None:
    """worldState.ts ownershipAt: owners shown now (frozen inside a freeze), live owners, the owners
    before the last change, changedAt, the moved items and the change arcs."""
    g = ring_geometry(world)
    if not g or (world.get("ring") or {}).get("ownership") == "none" or not any(n.get("role") == "owner" for n in nodes):
        return None
    freezes = freeze_intervals(timeline)
    live = owners_at(nodes, g, _on_ids(world_visibility(world, timeline, now)))
    owners = owners_at(nodes, g, _on_ids(world_visibility(world, timeline, _effective(now, freezes))))
    start_all = (world.get("ring") or {}).get("ownershipAtMs")
    start_all = -_INF if start_all is None else start_all
    coloured = {n["id"]: start_all for n in nodes if n.get("role") == "item"}
    for st in timeline:
        for w in st.get("walk") or []:
            i = walk_item(w)
            if i in coloured:
                coloured[i] = min(coloured[i], st["t"] + WALK_MS)
    changes = [t for t in owner_change_times(world, timeline, now, freezes) if t >= start_all]
    changed_at = changes[-1] if changes else -_INF
    base = {"owners": owners, "live": live, "colouredFrom": coloured}
    if changed_at == -_INF:
        return {**base, "before": owners, "changedAt": changed_at, "moved": set(), "changeArcs": []}
    vis_before = world_visibility(world, timeline, _effective(changed_at - 0.5, freezes))
    vis_after = world_visibility(world, timeline, _effective(changed_at, freezes))
    before = owners_at(nodes, g, _on_ids(vis_before))
    moved = {i for i in owners if before.get(i) is not None and before.get(i) != owners[i] and coloured.get(i, _INF) <= changed_at}
    owner_nodes = [n for n in nodes if n.get("role") == "owner"]

    def angle_of(i):
        n = next(x for x in owner_nodes if x["id"] == i)
        a = _node_angle(n, g)
        return 0 if a is None else a
    arcs = []
    for n in owner_nodes:
        was = (vis_before.get(n["id"]) or (False,))[0]
        is_ = (vis_after.get(n["id"]) or (False,))[0]
        if was == is_:
            continue
        vs = vis_after if is_ else vis_before
        others = [o for o in owner_nodes if o["id"] != n["id"] and (vs.get(o["id"]) or (False,))[0]]
        a1 = angle_of(n["id"])
        if not others:
            arcs.append({"a0": a1, "a1": a1})
            continue
        pred, best = others[0], _INF
        for o in others:
            d = ((a1 - angle_of(o["id"])) % 360 + 360) % 360
            if 1e-9 < d < best:
                best, pred = d, o
        arcs.append({"a0": angle_of(pred["id"]), "a1": a1})
    return {**base, "before": before, "changedAt": changed_at, "moved": moved, "changeArcs": arcs}


def walk_plan(world: dict, nodes: list[dict], timeline: list[dict], step: dict) -> list[dict]:
    """worldState.ts walkPlan: per walk entry {item, successor, target, overshoot, ok}; the successor
    is the next visible owner clockwise at the step (live ownership)."""
    g = ring_geometry(world)
    if not g or not step.get("walk"):
        return []
    live = owners_at(nodes, g, world_visible_ids(world, timeline, step["t"]))
    out = []
    for w in step["walk"]:
        item = walk_item(w)
        succ = live.get(item)
        to = None if isinstance(w, str) else (w or {}).get("to")
        over = not isinstance(w, str) and bool((w or {}).get("overshoot"))
        target = to if to is not None else succ
        out.append({"item": item, "successor": succ, "target": target, "overshoot": over,
                    "ok": target is not None and (target == succ or over)})
    return out


def change_visible(own: dict | None, timeline: list[dict], cur: dict | None, now: float) -> bool:
    """worldState.ts changeVisible (W13b): the automatic change band and moved outlines show from the
    ownership change until the next step after it, unless the step at the change persists "change";
    a later step that sets `arcs` always hides them."""
    if not own or own["changedAt"] == -_INF or not own["moved"]:
        return False
    if cur is not None and own["changedAt"] <= cur["arcsSetAt"]:
        return False
    causer = next((st for st in timeline if st["t"] == own["changedAt"]), None)
    if persists(causer, "change"):
        return True
    return next_step_after(timeline, own["changedAt"]) > now


def world_marks_at(world: dict, timeline: list[dict], now: float) -> dict:
    """worldState.ts worldMarksAt (W13b): the marks a world draws at now, after expiry: focus,
    focusEdges, speaksOf, arcs, tint, walk arrows {item, target} and the automatic change
    {moved, arcs} (None when hidden)."""
    res = resolve_steps(timeline, world)
    idx = last_index_at_or_before(res, now)
    cur = res[idx] if idx >= 0 else None
    nodes = place_nodes(world)
    own = ownership_at(world, nodes, timeline, now) if ring_geometry(world) else None
    walks = []
    if cur and cur["walk"] and now < cur["walkUntil"]:
        walks = [{"item": p["item"], "target": p["target"]}
                 for p in walk_plan(world, nodes, timeline, {"t": cur["walkAt"], "walk": cur["walk"]})]
    change = {"moved": sorted(own["moved"]), "arcs": own["changeArcs"]} if change_visible(own, timeline, cur, now) else None
    return {"focus": list(cur["focus"]) if cur else [], "focusEdges": list(cur["focusEdges"]) if cur else [],
            "speaksOf": list(cur["speaksOf"]) if cur else [], "arcs": cur["arcs"] if cur else [],
            "tint": dict(cur["tint"]) if cur else {}, "walks": walks, "change": change}


def marks_at(manifest: dict, now: float) -> dict | None:
    """visibleText.ts marksAt: marks of the episode world at now when a world scene is on screen."""
    world = manifest.get("world")
    if not world:
        return None
    if not any(sc.get("type") == "world" and sc.get("startMs", 0) <= now < sc.get("endMs", 0) for sc in manifest.get("scenes", [])):
        return None
    return world_marks_at(world, world_timeline(manifest), now)


def last_index_at_or_before(timeline: list[dict], now: float) -> int:
    idx = -1
    for i, st in enumerate(timeline):
        if st["t"] <= now:
            idx = i
        else:
            break
    return idx


_STOP_AFTER_A = {"and", "or"}


def _tokenise(s: str) -> list[str]:
    return [w for w in re.split(r"\s+", re.sub(r"[^A-Za-z0-9'\-\s]", " ", s)) if w]


def names_in_words(words: list[str], label: str) -> list[int]:
    """worldState.ts namesInWords: word indexes where a node label is named (whole words, case
    sensitive); "A" or "I" at a sentence start before a lowercase word is English, not a name."""
    want = _tokenise(label)
    if not want or re.fullmatch(r"\d+", label.strip()):
        return []
    clean = [re.sub(r"'s$", "", re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9']+$", "", w)) for w in words]
    single = len(want) == 1 and len(want[0]) == 1
    out = []
    for i in range(len(clean) - len(want) + 1):
        if any(clean[i + k] != w for k, w in enumerate(want)):
            continue
        if single and want[0] in ("A", "I"):
            start = i == 0 or re.search(r"[.?!:][\"')]*$", words[i - 1]) is not None
            nxt = clean[i + 1] if i + 1 < len(clean) else None
            if start and nxt and re.match(r"^[a-z]", nxt) and nxt not in _STOP_AFTER_A:
                continue
        out.append(i)
    return out


def focus_problems(manifest: dict) -> list[str]:
    """worldState.ts focusProblems (W13b, judge v6 seg03 t23): WARNINGS when a spotlight dims what
    the words or a walk are about: a walk item or target outside the current non-empty focus and
    speaksOf; a speaksOf id not visible at its step; a turn naming a visible node (label with a
    capital letter) while the focus at that word, inside a world scene, dims it."""
    world = manifest.get("world")
    if not world:
        return []
    timeline = world_timeline(manifest)
    res = resolve_focus(timeline)
    nodes = place_nodes(world)
    g = ring_geometry(world)
    out = []

    def where(st):
        at = st.get("at") or {}
        extra = (f", {at.get('turn')}" + (f" \"{at.get('word')}\"" if at.get("word") else "")) if at else ""
        return f"{_js_round(st['t'])} ms (scene {st.get('sceneId')}{extra})"

    for r, st in zip(res, timeline):
        vis = world_visibility(world, timeline, st["t"])
        for i in st.get("speaksOf") or []:
            if not (vis.get(i) or (False,))[0]:
                out.append(f"step at {where(st)}: speaksOf names {i}, which is not visible then; reveal it or drop it from speaksOf")
        if not st.get("walk") or not r["focus"] or not g:
            continue
        live = owners_at(nodes, g, {k for k, (on, _) in vis.items() if on})
        dim = []
        for w in st["walk"]:
            item = walk_item(w)
            to = None if isinstance(w, str) else (w or {}).get("to")
            target = to if to is not None else live.get(item)
            for i in (item, target):
                if i and i not in r["focus"] and i not in r["speaksOf"] and i not in dim:
                    dim.append(i)
        if dim:
            them = "them" if len(dim) > 1 else "it"
            out.append(f"step at {where(st)}: the walk names {', '.join(dim)} but focus [{', '.join(sorted(r['focus']))}] dims {them}; "
                       f"add {them} to focus or speaksOf, or set \"focus\": []")
    world_scenes = [sc for sc in manifest.get("scenes", []) if sc.get("type") == "world"]
    named = [n for n in world.get("nodes") or [] if n.get("role") != "item" and re.search(r"[A-Z]", str(n.get("label") or ""))
             and not re.fullmatch(r"\d+", str(n.get("label")).strip())]
    labels = list(dict.fromkeys(n["label"] for n in named))
    seen = set()
    for turn in manifest.get("turns") or []:
        words = turn.get("words") or None
        texts = [w.get("text", "") for w in words] if words else str(turn.get("text", "")).split()
        for label in labels:
            for i in names_in_words(texts, label):
                at = words[i].get("startMs", 0) if words else turn.get("startMs", 0)
                if not any(sc.get("startMs", 0) <= at < sc.get("endMs", 0) for sc in world_scenes):
                    continue
                idx = last_index_at_or_before(res, at + 100)
                if idx < 0 or not res[idx]["focus"]:
                    continue
                r = res[idx]
                vis = world_visibility(world, timeline, at)
                ids = [n["id"] for n in named if n["label"] == label and (vis.get(n["id"]) or (False,))[0]]
                if not ids or any(i in r["focus"] or i in r["speaksOf"] for i in ids):
                    continue
                key = f"{turn.get('id')}:{label}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(f"turn {turn.get('id')} names \"{label}\" at {_js_round(at)} ms while the focus from the step at "
                           f"{where(timeline[idx])} [{', '.join(sorted(r['focus']))}] dims {', '.join(ids)}; add a step on that word "
                           f"with focus including {ids[0]} or \"speaksOf\": [\"{ids[0]}\"], or \"focus\": []")
    return out


def point_of(n: dict, nodes: list[dict]):
    """worldState.ts pointOf (W13b virtual nodes): the node's `point`, else its 1-based index among
    the nodes with the same virtualOf (world order); None for a plain node."""
    if n.get("point") is not None:
        return n["point"]
    if n.get("virtualOf") is None:
        return None
    same = [x.get("id") for x in nodes if x.get("virtualOf") == n["virtualOf"]]
    return same.index(n.get("id")) + 1 if n.get("id") in same else 0


def label_with_point(label, n: dict, nodes: list[dict]):
    """worldState.ts labelWithPoint: the label plus the point subscript ("A" + 1 reads "A1")."""
    p = point_of(n, nodes)
    return label if p is None else f"{'undefined' if label is None else label}{_js_str(p)}"


def world_texts_at(world: dict, timeline: list[dict], now: float, fps: float, only=None, note_scene=None) -> list:
    """worldTextsAt: visible labels, sublabels and values (after `set`, with expiry), edge labels,
    current note."""
    t = now + (LEAD_FRAMES / fps) * 1000
    vis = world_visibility(world, timeline, t)
    over = node_overrides(timeline, t)
    out: list = []
    for n in world.get("nodes") or []:
        v = vis.get(n["id"])
        if not (v and v[0]) or (only and not only(n)):
            continue
        label, value = node_text_at(n, v, over.get(n["id"]), timeline, t)
        out.append(label_with_point(label, n, world.get("nodes") or []))
        if n.get("sublabel"):
            out.append(n["sublabel"])
        if value is not None:
            out.append(value)
    for e in world.get("edges") or []:
        v = vis.get(e["id"])
        if v and v[0] and e.get("label"):
            out.append(e["label"])
    cur = None
    for st in timeline:
        if st["t"] <= now:
            cur = st
        else:
            break
    if cur and cur.get("note") and (not note_scene or cur.get("sceneId") == note_scene):
        out.append(cur["note"])
    return out


def _props_texts(obj, now: float, key: str = "") -> list:
    if isinstance(obj, str):
        return [obj]
    if _num(obj):
        return [] if key.endswith("Ms") else [_js_str(obj)]
    if isinstance(obj, list):
        return [s for v in obj for s in _props_texts(v, now, key)]
    if isinstance(obj, dict):
        if _num(obj.get("atMs")) and obj["atMs"] > now:
            return []
        out = []
        for k, v in obj.items():
            if k in _SKIP_KEYS:
                continue
            gate = obj.get(f"{k}AtMs")
            if _num(gate) and gate > now:
                continue
            out += _props_texts(v, now, k)
        return out
    return []


def step_frames(panel, from_frame: int, fps: float) -> list[tuple[int, int]]:
    """compareState.ts stepFrames: (cue, result) frames of a panel's steps."""
    out = []
    for i, st in enumerate((panel or {}).get("steps") or []):
        r = answer_frame(st.get("atMs"), from_frame, fps)
        out.append((cue_frame(st.get("atMs"), _fallback(i), from_frame, fps), r if r is not None else _fallback(i)))
    return out


def expiry_frame(at: int, frames: list[tuple[int, int]]) -> float:
    """compareState.ts expiryFrame: the cue frame of the first step whose word comes after `at`,
    never before at + 1; inf when no step follows."""
    e = _INF
    for cue, res in frames:
        if res > at:
            e = min(e, max(at + 1, cue))
    return e


def banner_at(props: dict, from_frame: int, fps: float, frame: int):
    """bannerAt: the latest verdict or banner whose answer frame has passed, until the next step of
    either panel after its word unless persist; expired means None (not the previous banner)."""
    lst = ([props["verdict"]] if props.get("verdict") else []) + list(props.get("banners") or [])
    best = None
    for b in lst:
        at = answer_frame(b.get("atMs"), from_frame, fps)
        if at is None or at > frame:
            continue
        if best is None or at >= best[1]:
            best = (b, at)
    if best is None:
        return None
    b, at = best
    frames = step_frames(props.get("left"), from_frame, fps) + step_frames(props.get("right"), from_frame, fps)
    until = _INF if b.get("persist") else expiry_frame(at, frames)
    if frame >= until:
        return None
    out = {"text": claim_fill(b.get("text"), b.get("claim")), "winner": b.get("winner") or "none", "labels": b.get("labels") or {},
           "at": at, "until": until}
    if b.get("claim"):
        out["claim"] = b["claim"]
    return out


def panel_state_at(panel: dict, from_frame: int, fps: float, frame: int) -> dict:
    """panelStateAt: title, tag, stat (until the panel's next step unless persist), table rows (with
    fill) and text lines at a local frame. A stat may be a string or {text, persist?, claim?}."""
    steps = panel.get("steps") or []
    frames = step_frames(panel, from_frame, fps)
    results = [r for _, r in frames]
    stat, stat_latest, title, tag = None, -_INF, panel.get("title"), panel.get("tag")
    filled: dict[str, dict[int, int]] = {}
    fill_rows: set = set()
    rows = panel.get("rows") or []
    for i, s in enumerate(steps):
        if "stat" in s and frame >= results[i] and results[i] >= stat_latest:
            stat_latest = results[i]
            st = {"text": s["stat"]} if isinstance(s["stat"], str) else dict(s["stat"] or {})
            until = _INF if st.get("persist") else expiry_frame(results[i], frames)
            stat = None if st.get("text", "") == "" else {"text": claim_fill(st["text"], st.get("claim")), "at": results[i], "until": until,
                                                         **({"claim": st["claim"]} if st.get("claim") else {})}
        if "title" in s and frame >= results[i]:
            title = s["title"]
        if "tag" in s and frame >= results[i]:
            tag = None if s["tag"] == "" else s["tag"]
        for rid, cs in (s.get("fill") or {}).items():
            fill_rows.add(rid)
            if frame < results[i]:
                continue
            row = next((r for r in rows if r.get("id") == rid), None)
            lst = list(range(len((row or {}).get("cells") or []))) if cs == "all" else cs
            d = filled.setdefault(rid, {})
            for c in lst:
                d.setdefault(c, results[i])
    row_states = []
    for r in rows:
        at = answer_frame(r.get("atMs"), from_frame, fps)
        cells = []
        for c, text in enumerate(r.get("cells") or []):
            if r.get("id") not in fill_rows:
                cells.append(text)
            else:
                cells.append(text if c in filled.get(r.get("id"), {}) else "?")
        row_states.append({"label": r.get("label"), "cells": cells, "visible": at is None or frame >= at})
    lines = []
    for ln in panel.get("lines") or []:
        at = answer_frame(ln.get("atMs"), from_frame, fps)
        lines.append({"text": ln.get("text"), "visible": at is None or frame >= at})
    if stat is not None and frame >= stat["until"]:
        stat = None
    return {"title": title, "tag": tag, "stat": stat, "rows": row_states, "lines": lines}


# tableLayout.ts (W11b): the compare-table layout, ported 1:1 (qc.py text checks use it too).
GRID_TEXT_PX, TABLE_LABEL_W, TABLE_CELL_GAP, TABLE_ROW_PAD, TABLE_BAND_GAP = 36, 180, 6, 12, 16
TABLE_LABEL_MAX = 320   # W13b: the row-label column grows to hold the longest label, up to this width
TABLE_PAD_X, TABLE_PAD_TOP, TABLE_MAX_CELL, CELL_TEXT_PAD, MIN_TEXT_PX = 24, 8, 110, 8, 28
COMPARE_GAP, COMPARE_HEADER_H, COMPARE_STAT_H, COMPARE_VERDICT_H, COMPARE_TITLE_H = 40, 64, 84, 72, 80


def compare_body_size(titled: bool) -> tuple[float, float]:
    panel_w = (1728 - COMPARE_GAP) / 2
    panel_h = 712 - (COMPARE_TITLE_H if titled else 0) - COMPARE_VERDICT_H - 16
    return panel_w - 12, panel_h - COMPARE_HEADER_H - COMPARE_STAT_H - 12


def label_width(chars: int, font: float) -> int:
    """tableLayout.ts labelWidth: px a row label of `chars` characters needs at `font` px."""
    return math.ceil(chars * CHAR_W * font)


def table_label_w(label_chars: int) -> int:
    """tableLayout.ts tableLabelW: the row-label column, wide enough for the longest label at
    GRID_TEXT_PX, between TABLE_LABEL_W and TABLE_LABEL_MAX."""
    return min(TABLE_LABEL_MAX, max(TABLE_LABEL_W, label_width(label_chars, GRID_TEXT_PX)))


def _layout_for(n: int, nb: int, n_rows: int, w: float, h: float, header: bool, chars: int, label_chars: int = 0) -> dict:
    per = math.ceil(n / nb)
    bands_n = math.ceil(n / per)
    bands = [list(range(b * per, min(n, (b + 1) * per))) for b in range(bands_n)]
    rows_per_band = max(1, n_rows) + (1 if header else 0)
    label_w = table_label_w(label_chars)
    room_w = math.floor((w - 2 * TABLE_PAD_X - label_w) / per) - TABLE_CELL_GAP
    cell_h = math.floor((h - TABLE_PAD_TOP - (bands_n - 1) * TABLE_BAND_GAP) / (bands_n * rows_per_band)) - TABLE_ROW_PAD
    cell = max(1, min(TABLE_MAX_CELL, room_w, cell_h))
    need = math.ceil(CHAR_W * GRID_TEXT_PX * max(1, chars)) + CELL_TEXT_PAD   # W16: wide cells for text up to 12 chars
    cell_w = max(cell, min(room_w, need))
    font = max(0, min(GRID_TEXT_PX, math.floor(cell * 0.8), math.floor((cell_w - CELL_TEXT_PAD) / (CHAR_W * max(1, chars)))))
    label_font = font if label_chars == 0 else max(0, min(font, math.floor(label_w / (CHAR_W * label_chars))))
    return {"bands": bands, "perBand": per, "cell": cell, "cellW": cell_w, "rowH": cell + TABLE_ROW_PAD, "font": font,
            "labelW": label_w, "labelFont": label_font, "labelChars": label_chars, "bandGap": TABLE_BAND_GAP,
            "header": header, "fits": font >= MIN_TEXT_PX and label_font >= MIN_TEXT_PX}


def table_layout(n_cols: int, n_rows: int, w: float, h: float, header: bool, chars: int = 1, label_chars: int = 0) -> dict:
    """tableLayout: every band count; keep the largest text, then the larger cell, then fewer bands."""
    n = max(1, n_cols)
    best = None
    for nb in range(1, n + 1):
        if nb > 1 and math.ceil(n / math.ceil(n / nb)) != nb:
            continue
        L = _layout_for(n, nb, n_rows, w, h, header, chars, label_chars)
        if best is None or L["font"] > best["font"] or (L["font"] == best["font"] and L["cell"] > best["cell"]):
            best = L
    return best


def table_chars(panel: dict) -> int:
    return max([1] + [len(str(c)) for c in panel.get("columns") or []]
               + [len(str(c)) for r in panel.get("rows") or [] for c in r.get("cells") or []])


def table_label_chars(panel: dict) -> int:
    return max([0] + [len(str(r.get("label") or "")) for r in panel.get("rows") or []])


def table_columns(panel: dict) -> int:
    return max(1, len(panel.get("columns") or []) or max([0] + [len(r.get("cells") or []) for r in panel.get("rows") or []]))


def panel_table_layout(panel: dict, titled: bool) -> dict:
    w, h = compare_body_size(titled)
    return table_layout(table_columns(panel), len(panel.get("rows") or []), w, h, bool(panel.get("columns")),
                        table_chars(panel), table_label_chars(panel))


def table_problems(panel: dict, titled: bool) -> list[str]:
    """tableLayout.ts tableProblems: rows with a cell count other than the columns (or the first
    row), a row label that would draw under 28 px (stumble 5: the label column grows to 320 px,
    then the label text shrinks), and geometry that cannot keep text at 28 px."""
    out = []
    rows = panel.get("rows") or []
    n = len(panel.get("columns") or []) or (len(rows[0].get("cells") or []) if rows else 0)
    what = f"{n} columns" if panel.get("columns") else f"{n} cells in the first row"
    for r in rows:
        if len(r.get("cells") or []) != n:
            out.append(f"row {r.get('id')} has {len(r.get('cells') or [])} cells for {what}; give every row exactly one cell per column")
    L = panel_table_layout(panel, titled)
    if L["labelFont"] < MIN_TEXT_PX and L["labelChars"] > 0:
        longest = ""
        for r in rows:
            if len(str(r.get("label") or "")) > len(longest):
                longest = str(r.get("label") or "")
        max_chars = math.floor(TABLE_LABEL_MAX / (CHAR_W * MIN_TEXT_PX))
        out.append(f"row label \"{longest}\" ({L['labelChars']} characters) needs {label_width(L['labelChars'], MIN_TEXT_PX)} px at "
                   f"{MIN_TEXT_PX} px text, but the row-label column is at most {TABLE_LABEL_MAX} px, so it would draw at "
                   f"{L['labelFont']} px; shorten it to {max_chars} characters or fewer")
    if L["font"] < MIN_TEXT_PX:
        w, h = compare_body_size(titled)
        chars = table_chars(panel)
        fit_cols = max([k for k in range(1, 41)
                        if table_layout(k, len(rows), w, h, bool(panel.get("columns")), chars, L["labelChars"])["font"] >= MIN_TEXT_PX] + [0])
        out.append(f"{table_columns(panel)} columns x {len(rows)} rows (longest text {chars} characters, row-label column "
                   f"{L['labelW']} px) gives {L['cell']} px cells and {L['font']} px text; text must be at least {MIN_TEXT_PX} px. "
                   + (f"At most {fit_cols} columns fit with these rows; " if fit_cols else f"No column count fits {len(rows)} rows; ")
                   + "cut columns or rows, shorten cell text" + (", or drop the scene title." if titled else "."))
    return out


CHIP_MIN_MS = 700   # overlayState.ts


# matrixLayout.ts (W16, W14b D08): the matrix scene, ported 1:1.
MATRIX_W, MATRIX_H, MATRIX_HEADING_H, MATRIX_NOTE_H, MATRIX_AXIS_H, MATRIX_AXIS_W = 1728, 712, 92, 72, 44, 56
MATRIX_GAP, MATRIX_TEXT_PAD, MATRIX_TEXT_MAX, MATRIX_CELL_MAX_W, MATRIX_CELL_MAX_H = 6, 16, 40, 260, 120


def matrix_cell_chars(p: dict) -> int:
    return max([1] + [len(str(c)) for c in p.get("columns") or []] + [len(str(c)) for r in p.get("cells") or [] for c in r])


def matrix_row_chars(p: dict) -> int:
    return max([1] + [len(str(r)) for r in p.get("rows") or []])


def matrix_body(titled: bool, row_axis: bool, col_axis: bool) -> tuple[int, int]:
    return (MATRIX_W - (MATRIX_AXIS_W if row_axis else 0),
            MATRIX_H - (MATRIX_HEADING_H if titled else 0) - MATRIX_NOTE_H - (MATRIX_AXIS_H if col_axis else 0))


def matrix_layout_for(n_rows: int, n_cols: int, cell_chars: int, row_chars: int, titled: bool,
                      row_axis: bool = False, col_axis: bool = False) -> dict:
    R, C = max(1, n_rows), max(1, n_cols)
    body_w, body_h = matrix_body(titled, row_axis, col_axis)
    fw = (body_w - MATRIX_TEXT_PAD - C * (MATRIX_TEXT_PAD + MATRIX_GAP)) / (CHAR_W * (row_chars + C * cell_chars))
    row_slot = math.floor(body_h / (R + 1)) - MATRIX_GAP
    fh = math.floor(min(MATRIX_CELL_MAX_H, row_slot) * 0.6)
    font = max(0, math.floor(min(MATRIX_TEXT_MAX, fw, fh)))
    header_w = math.ceil(row_chars * CHAR_W * max(font, 1)) + MATRIX_TEXT_PAD
    cell_w = max(1, min(MATRIX_CELL_MAX_W, math.floor((body_w - header_w) / C) - MATRIX_GAP))
    cell_h = max(1, min(MATRIX_CELL_MAX_H, row_slot))
    grid_w = header_w + C * (cell_w + MATRIX_GAP)
    grid_h = (R + 1) * (cell_h + MATRIX_GAP)
    return {"font": font, "headerW": header_w, "cellW": cell_w, "cellH": cell_h, "gridW": grid_w, "gridH": grid_h,
            "left": max(0, math.floor((body_w - grid_w) / 2)), "top": max(0, math.floor((body_h - grid_h) / 2)),
            "bodyW": body_w, "bodyH": body_h, "cellChars": cell_chars, "rowChars": row_chars,
            "fits": font >= MIN_TEXT_PX and cell_w >= math.ceil(cell_chars * CHAR_W * font) + MATRIX_TEXT_PAD / 2}


def matrix_layout(p: dict) -> dict:
    return matrix_layout_for(len(p.get("rows") or []), len(p.get("columns") or []), matrix_cell_chars(p), matrix_row_chars(p),
                             bool(p.get("title")), bool(p.get("rowAxis")), bool(p.get("colAxis")))


def matrix_index(headers: list, ref) -> int:
    """A highlight reference as an index; -1 when it names no header or a repeated one."""
    if ref is None or isinstance(ref, bool):
        return -1
    if isinstance(ref, (int, float)):
        return int(ref) if float(ref).is_integer() and 0 <= ref < len(headers) else -1
    hits = [i for i, h in enumerate(headers) if h == ref]
    return hits[0] if len(hits) == 1 else -1


def matrix_problems(p: dict) -> list[str]:
    """matrixLayout.ts matrixProblems: shapes, highlight references and the 28 px rule."""
    out: list[str] = []
    rows, cols = p.get("rows") or [], p.get("columns") or []
    if not rows or not cols:
        out.append("a matrix needs at least one row header and one column header")
    for name in ("cells", "heat"):
        grid = p.get(name)
        if grid is None:
            continue
        if len(grid) != len(rows):
            out.append(f"{name} has {len(grid)} rows for {len(rows)} row headers; give one row per header")
        for i, r in enumerate(grid):
            if len(r) != len(cols):
                out.append(f"{name} row {i} has {len(r)} entries for {len(cols)} columns; give one per column")
    for v in [v for r in p.get("heat") or [] for v in r]:
        if not _num(v) or not (0 <= v <= 1):
            out.append(f"heat value {_js_str(v)} is outside 0..1")
    for i, s in enumerate(p.get("steps") or []):
        for m in s.get("highlight") or []:
            if m.get("row") is None and m.get("col") is None:
                out.append(f"step {i} highlight names neither row nor col")
            if m.get("row") is not None and matrix_index(rows, m["row"]) < 0:
                out.append(f"step {i} highlight row {json.dumps(m['row'])} is not one row header (use its index when a header repeats)")
            if m.get("col") is not None and matrix_index(cols, m["col"]) < 0:
                out.append(f"step {i} highlight col {json.dumps(m['col'])} is not one column header (use its index when a header repeats)")
    if not rows or not cols:
        return out
    L = matrix_layout(p)
    if not L["fits"]:
        titled, ra, ca = bool(p.get("title")), bool(p.get("rowAxis")), bool(p.get("colAxis"))
        fit = max([k for k in range(1, 41) if matrix_layout_for(len(rows), k, L["cellChars"], L["rowChars"], titled, ra, ca)["fits"]] + [0])
        out.append(f"{len(cols)} columns x {len(rows)} rows (longest cell or column header {L['cellChars']} characters, longest row header "
                   f"{L['rowChars']}) in a {L['bodyW']} x {L['bodyH']} px body gives {L['font']} px text; text must be at least {MIN_TEXT_PX} px. "
                   + (f"At most {fit} columns fit with these rows and texts; " if fit > 0 else f"No column count fits {len(rows)} rows; ")
                   + "cut rows or columns, shorten headers or cells" + (", or drop the title" if titled else "") + ".")
    return out


def matrix_state_at(p: dict, from_frame: int, fps: float, frame: int) -> dict:
    """matrixLayout.ts matrixStateAt: highlighted cells, rows, columns and the note at a local frame."""
    steps = p.get("steps") or []
    at = [cue_frame(s.get("atMs"), _fallback(i), from_frame, fps) for i, s in enumerate(steps)]
    cur = -1
    for i, f in enumerate(at):
        if frame >= f and (cur < 0 or f >= at[cur]):
            cur = i
    st = {"cells": set(), "rows": set(), "cols": set(), "note": None}
    for i, s in enumerate(steps):
        if frame < at[i] or (i != cur and not s.get("persist")):
            continue
        for m in s.get("highlight") or []:
            r, c = matrix_index(p.get("rows") or [], m.get("row")), matrix_index(p.get("columns") or [], m.get("col"))
            if r >= 0 and c >= 0:
                st["cells"].add(f"{r},{c}")
            elif r >= 0:
                st["rows"].add(r)
            elif c >= 0:
                st["cols"].add(c)
    if cur >= 0:
        st["note"] = steps[cur].get("note")
    return st


def matrix_texts_at(p: dict, from_frame: int, fps: float, frame: int) -> list[str]:
    out = [x for x in [p.get("title"), p.get("rowAxis"), p.get("colAxis"), *(p.get("columns") or []), *(p.get("rows") or []),
                       *[c for r in p.get("cells") or [] for c in r]] if x]
    n = matrix_state_at(p, from_frame, fps, frame)["note"]
    if n:
        out.append(n)
    return out


# labels.early (W16, W15 proposal 1): a number on a cued label (chip, panel stat, banner or verdict,
# a step note, a world `set` value or label) shown before the number is first spoken. Example: v6 and
# v7 sc07 showed "moved: 8 of 12" during t63, but "8 of 12" is first spoken in t64.
EARLY_TOLERANCE_MS = 500       # a label in another turn than the one that speaks its number
EARLY_SAME_TURN_MS = 2000      # a label anchored to a phrase start in the turn that speaks it
_LABEL_NUM = re.compile(r"\d+(point\d+)?")


def _label_number(tok: str, spoken: bool = False) -> str | None:
    """A quantity token ("8", "0point81"); ids such as "r1" and ordinals such as "2nd" are not. A
    spoken lone "one" counts as 1; a label's "one" does not (it is a word there)."""
    tok = "1" if spoken and tok == "one" else tok
    return tok if _LABEL_NUM.fullmatch(tok) else None


def _cued_labels(obj, where: str, out: list) -> None:
    if isinstance(obj, list):
        for i, x in enumerate(obj):
            _cued_labels(x, f"{where}[{i}]", out)
        return
    if not isinstance(obj, dict):
        return
    at = obj.get("atMs")
    if _num(at):
        ok = obj.get("earlyOk") if isinstance(obj.get("earlyOk"), str) and obj["earlyOk"].strip() else None
        st = obj.get("stat")
        if isinstance(st, dict):
            st = claim_fill(st.get("text") or "", st.get("claim"))
        banner = "claim" in obj or "winner" in obj or "labels" in obj
        for key, text in (("stat", st), ("note", obj.get("note")), ("text", obj.get("text") if banner else None)):
            if isinstance(text, str) and text:
                out.append((at, f"{where}.{key}", claim_fill(text, obj.get("claim")) if key == "text" else text, ok))
        if banner and isinstance(obj.get("labels"), dict):   # W18: a banner's side pills ("R5 owns 4 of 12")
            for side in ("left", "right"):
                if isinstance(obj["labels"].get(side), str) and obj["labels"][side]:
                    out.append((at, f"{where}.labels.{side}", obj["labels"][side], ok))
        for nid, ch in (obj.get("set") or {}).items() if isinstance(obj.get("set"), dict) else []:
            for k in ("value", "label"):
                if isinstance((ch or {}).get(k), str) and ch[k]:
                    out.append((at, f"{where}.set.{nid}.{k}", ch[k], ok))
    for k, v in obj.items():
        if isinstance(v, (dict, list)) and k != "set":
            _cued_labels(v, f"{where}.{k}", out)


def _label_keys(text: str) -> list[str]:
    """The quantities a label states: "X of Y" as one key ("8 of 12"), else each number."""
    toks = fidelity_tokens(text)
    keys, i = [], 0
    while i < len(toks):
        x = _label_number(toks[i])
        if x and i + 2 < len(toks) and toks[i + 1] == "of" and _label_number(toks[i + 2]):
            keys.append(f"{x} of {_label_number(toks[i + 2])}")
            i += 3
            continue
        if x:
            keys.append(x)
        i += 1
    return list(dict.fromkeys(keys))


def early_label_problems(manifest: dict) -> list[dict]:
    """[{where, text, number, shownMs, turn, spokenMs, spokenTurn, leadMs}] for every quantity on a
    cued label that shows before it is spoken. "X of Y" is one quantity and must be spoken as "X of
    Y". A quantity spoken earlier in the same scene passes (a recap of what was just said); one never
    spoken is not reported. Leads up to EARLY_SAME_TURN_MS inside the turn that speaks it pass.
    W18: a banner's side labels are cued labels too; `earlyOk` is the reason string from the step,
    banner or chip props when the author marked the lead as intended (None otherwise)."""
    turns = sorted(manifest.get("turns") or [], key=lambda t: t.get("startMs", 0))
    seq: list[tuple[str, float, str]] = []  # every spoken quantity token with its word time and turn
    for t in turns:
        for w in t.get("words") or []:
            for x in fidelity_tokens(w.get("text") or ""):
                seq.append((_label_number(x, True) or x, w.get("startMs", t.get("startMs", 0)), t.get("id")))
    said: dict[str, list[tuple[float, str]]] = {}
    for i, (tok, ms, tid) in enumerate(seq):
        if _LABEL_NUM.fullmatch(tok):
            said.setdefault(tok, []).append((ms, tid))
            if i + 2 < len(seq) and seq[i + 1][0] == "of":
                j = i + 3 if seq[i + 2][0] == "the" and i + 3 < len(seq) else i + 2   # "3 of the 12"
                if _LABEL_NUM.fullmatch(seq[j][0]):
                    said.setdefault(f"{tok} of {seq[j][0]}", []).append((ms, tid))
    labels: list = []
    scenes = manifest.get("scenes") or []
    for sc in scenes:
        n0 = len(labels)
        _cued_labels(sc.get("props") or {}, f"scene {sc.get('id')}", labels)
        labels[n0:] = [(at, w, tx, sc.get("startMs", 0), ok) for at, w, tx, ok in labels[n0:]]
    for i, ov in enumerate(manifest.get("overlays") or []):
        pr = ov.get("props") or {}
        if isinstance(pr.get("text"), str) and _num(ov.get("startMs")):
            host = next((sc for sc in scenes if sc.get("startMs", 0) <= ov["startMs"] < sc.get("endMs", 0)), None)
            ok = pr.get("earlyOk") if isinstance(pr.get("earlyOk"), str) and pr["earlyOk"].strip() else None
            labels.append((ov["startMs"], f"overlay {ov.get('id', i)}", claim_fill(pr["text"], pr.get("claim")),
                           (host or {}).get("startMs", ov["startMs"]), ok))

    def turn_at(ms):
        for t in turns:
            if t.get("startMs", 0) <= ms <= t.get("endMs", 0) + int(t.get("holdAfterMs", 0) or 0):
                return t.get("id")
        nxt = next((t for t in turns if t.get("startMs", 0) > ms), None)
        return nxt.get("id") if nxt else None

    out, seen = [], set()
    for at, where, text, scene_start, early_ok in sorted(labels, key=lambda x: x[0]):
        shown_in = turn_at(at)
        for key in _label_keys(text):
            if (text, key) in seen:
                continue  # the same label re-set on later steps: report its first showing only
            seen.add((text, key))
            occ = sorted(said.get(key) or [])
            if not occ or any(scene_start - 1 <= ms <= at + EARLY_TOLERANCE_MS for ms, _ in occ):
                continue
            later = [(ms, tid) for ms, tid in occ if ms > at]
            if not later:
                continue  # spoken only before this scene: a recap
            ms, tid = later[0]
            if tid == shown_in and ms - at <= EARLY_SAME_TURN_MS:
                continue
            out.append({"where": where, "text": text, "number": key, "shownMs": int(at), "turn": shown_in,
                        "spokenMs": int(ms), "spokenTurn": tid, "leadMs": int(ms - at), "earlyOk": early_ok})
    return out


def visual_step_times(manifest: dict) -> list[float]:
    """overlayState.ts visualStepTimes: every scene start and every cued step time."""
    ts = set()
    for sc in manifest.get("scenes", []):
        ts.add(sc.get("startMs", 0))
        p = sc.get("props") or {}
        for st in (p.get("steps") or []) + (p.get("worldSteps") or []) + ((p.get("left") or {}).get("steps") or []) + ((p.get("right") or {}).get("steps") or []):
            if isinstance(st, dict) and _num(st.get("atMs")):
                ts.add(st["atMs"])
    return sorted(ts)


def chip_frames(o: dict, times: list[float], fps: float) -> tuple[int, int, float | None]:
    """overlayState.ts chipFrames: (start, end, expiredBy). A chip ends at the cue of the next visual
    step after its start (never under CHIP_MIN_MS) unless props.persist."""
    start = ms_to_frame(o["startMs"], fps)
    own = ms_to_frame(o["endMs"], fps)
    if (o.get("props") or {}).get("persist"):
        return start, own, None
    nxt = next((t for t in times if t > o["startMs"]), None)
    if nxt is None:
        return start, own, None
    cut = max(ms_to_frame(nxt, fps) - LEAD_FRAMES, ms_to_frame(o["startMs"] + CHIP_MIN_MS, fps))
    return (start, cut, nxt) if cut < own else (start, own, None)


def _fps(manifest: dict) -> float:
    return ((manifest.get("video") or {}).get("fps")) or 30


def scene_texts_at(manifest: dict, scene: dict, now: float, timeline: list[dict] | None = None) -> list:
    """sceneTextsAt: the texts one scene draws at `now` (absolute episode ms)."""
    if timeline is None:
        timeline = world_timeline(manifest)
    fps = _fps(manifest)
    from_frame = ms_to_frame(scene.get("startMs", 0), fps)
    frame = ms_to_frame(now, fps) - from_frame
    p = scene.get("props") or {}
    out: list = []

    def push(*xs):
        out.extend(x for x in xs if x)

    kind = scene.get("type")
    world = manifest.get("world")
    if kind == "title":
        push(p.get("kicker"), p.get("title"), p.get("subtitle"))
        if p.get("question") and frame >= cue_frame(p.get("questionAtMs"), 45, from_frame, fps):
            push(p["question"])
    elif kind == "world":
        if world:
            out += world_texts_at(world, timeline, now, fps)
    elif kind == "recap":
        push(p["title"] if p.get("title") is not None else "Recap")
        for i, pt in enumerate((p.get("points") or [])[:4]):
            if frame >= cue_frame(pt.get("atMs"), 12 + i * 30, from_frame, fps):
                push(pt.get("text"))
    elif kind == "check":
        answered = "answer" in p or "correct" in p
        push("Check yourself" if answered else "Your turn: answer aloud", p.get("question"), *(p.get("options") or []))
        a = answer_frame(p.get("answerAtMs"), from_frame, fps) if answered else None
        if a is not None and frame >= a:
            push(p.get("answer"))
    elif kind == "equation":
        push(p.get("title"))
        for i, ln in enumerate(p.get("lines") or []):
            if frame >= cue_frame(ln.get("atMs"), _fallback(i), from_frame, fps):
                push(ln["tex"] if ln.get("tex") is not None else ln.get("text"), ln.get("note"))
    elif kind == "code":
        push(p.get("title"), p.get("filename"))
        reveal_at: dict[int, int] = {}
        for i, st in enumerate(p.get("steps") or []):
            for ln in parse_lines(st.get("lines")):
                reveal_at.setdefault(ln, cue_frame(st.get("atMs"), _fallback(i), from_frame, fps))
        code = re.sub(r"\n+$", "", str(p.get("code") if p.get("code") is not None else ""))
        for i, line in enumerate(code.split("\n")):
            at = reveal_at.get(i + 1)
            if (at is None or frame >= at) and line.strip():
                push(line)
    elif kind == "diagram":
        push(p.get("title"))
        reveal_at2: dict[str, int] = {}
        hide_at2: dict[str, int] = {}
        for i, st in enumerate(p.get("steps") or []):
            for eid in st.get("reveal") or []:
                reveal_at2.setdefault(eid, cue_frame(st.get("atMs"), _fallback(i), from_frame, fps))
            for eid in st.get("hide") or []:
                hide_at2.setdefault(eid, cue_frame(st.get("atMs"), _fallback(i), from_frame, fps))
        for el in p.get("elements") or []:
            at = reveal_at2.get(el.get("id"))
            off = hide_at2.get(el.get("id"))
            if el.get("text") and (at is None or frame >= at) and (off is None or frame < off):
                push(el["text"])
    elif kind == "compare":
        push(p.get("title"))
        banner = banner_at(p, from_frame, fps, frame)
        if banner:
            push(banner["text"])
        for side in ("left", "right"):
            panel = p.get(side)
            if not panel:
                continue
            st = panel_state_at(panel, from_frame, fps, frame)
            push(st["title"], st["tag"])
            if banner:
                lab = banner["labels"].get(side)
                if lab is None:
                    lab = None if banner["winner"] == "none" else ("right" if banner["winner"] == side else "wrong")
                push(lab)
            if st["stat"]:
                push(st["stat"]["text"])
            pk = panel.get("kind")
            if pk == "table":
                idx = [i for band in panel_table_layout(panel, bool(p.get("title")))["bands"] for i in band]
                cols = panel.get("columns") or []
                out.extend(cols[i] for i in idx if i < len(cols))
                for r in st["rows"]:
                    if r["visible"]:
                        push(r["label"], *[r["cells"][i] if i < len(r["cells"]) else None for i in idx])
            elif pk == "text":
                for ln in st["lines"]:
                    if ln["visible"]:
                        push(ln["text"])
            elif pk == "world":
                shared = panel.get("world") == "shared"
                w = world if shared else panel.get("world")
                if not w or not isinstance(w, dict):
                    continue
                sid = f"{scene.get('id')}-{side}"
                tl = timeline if shared else local_timeline(panel.get("steps") or [], sid, scene.get("startMs", 0))
                bw, bh = compare_body_size(bool(p.get("title")))
                cam = {**fit_camera(w, bw, bh), **(panel.get("camera") or {})}
                out += world_texts_at(w, tl, now, fps, ring_inset_filter(w, view_scale(w, bw, bh, cam)), scene.get("id") if shared else sid)
    elif kind == "matrix":
        out += matrix_texts_at(p, from_frame, fps, frame)
    elif kind == "custom":
        if isinstance(p.get("worldSteps"), list) and world:
            out += world_texts_at(world, timeline, now, fps, ring_inset_filter(world))
        out += _props_texts(p, now)
    return out


def world_label_sources(world: dict, timeline: list[dict], now: float, fps: float, scene_id, only=None, side=None) -> list[dict]:
    """visibleText.ts worldLabelSources (W13b): node labels, sublabels and values a world draws at
    now, each {text, source: node-label | node-sublabel | node-value, sceneId, nodeId, side?, expires}.
    expires is False for a base label and sublabel, True for a `set` label or a value without persist."""
    t = now + (LEAD_FRAMES / fps) * 1000
    vis = world_visibility(world, timeline, t)
    over = node_overrides(timeline, t)
    placed = place_nodes(world)
    out = []
    for n in world.get("nodes") or []:
        v = vis.get(n["id"])
        if not (v and v[0]) or (only and not only(n)):
            continue
        o = over.get(n["id"]) or {}
        label, value = node_text_at(n, v, o, timeline, t)
        base = {"sceneId": scene_id, "nodeId": n["id"], **({"side": side} if side else {})}
        label_persists = not o.get("labelSet") or label == n.get("label")
        out.append({"text": label_with_point(label, n, placed), "source": "node-label", "expires": not label_persists, **base})
        if n.get("sublabel"):
            out.append({"text": n["sublabel"], "source": "node-sublabel", "expires": False, **base})
        if value is not None:
            if o.get("valueSet"):
                lasts = any(st["t"] <= t and ((st.get("set") or {}).get(n["id"]) or {}).get("value") == value
                            and bool(((st.get("set") or {}).get(n["id"]) or {}).get("persist")) for st in timeline)
            else:
                lasts = bool(n.get("persist"))
            out.append({"text": value, "source": "node-value", "expires": not lasts, **base})
    return out


def node_label_sources_at(manifest: dict, now: float) -> list[dict]:
    """The node part of visibleText.ts labelSourcesAt (W13b): world node texts from world scenes and
    compare world panels at now (chips, banners, pills, stats, titles and tags are read by qc.py
    labels.counts from the scene props)."""
    fps = _fps(manifest)
    timeline = world_timeline(manifest)
    out = []
    for sc in manifest.get("scenes", []):
        if not (sc.get("startMs", 0) <= now < sc.get("endMs", 0)):
            continue
        if sc.get("type") == "world" and manifest.get("world"):
            out += world_label_sources(manifest["world"], timeline, now, fps, sc.get("id"))
        if sc.get("type") != "compare":
            continue
        p = sc.get("props") or {}
        for side in ("left", "right"):
            panel = p.get(side)
            if not panel or panel.get("kind") != "world":
                continue
            shared = panel.get("world") == "shared"
            w = manifest.get("world") if shared else panel.get("world")
            if not w or not isinstance(w, dict):
                continue
            tl = timeline if shared else local_timeline(panel.get("steps") or [], f"{sc.get('id')}-{side}", sc.get("startMs", 0), turn_ends(manifest))
            bw, bh = compare_body_size(bool(p.get("title")))
            cam = {**fit_camera(w, bw, bh), **(panel.get("camera") or {})}
            out += world_label_sources(w, tl, now, fps, sc.get("id"), ring_inset_filter(w, view_scale(w, bw, bh, cam)), side)
    return out


def visible_texts_at(manifest: dict, now: float, timeline: list[dict] | None = None) -> list:
    """visibleTextsAt: every text on screen at `now`: the active scene(s) plus keyword chips."""
    if timeline is None:
        timeline = world_timeline(manifest)
    out: list = []
    for sc in manifest.get("scenes", []):
        if sc["startMs"] <= now < sc["endMs"]:
            out += scene_texts_at(manifest, sc, now, timeline)
    fps = _fps(manifest)
    f = ms_to_frame(now, fps)
    times = visual_step_times(manifest)
    for ov in manifest.get("overlays") or []:
        if ov.get("type", "chip") != "chip":
            continue
        a, b, _ = chip_frames(ov, times, fps)
        if a <= f < b:
            pr = ov.get("props") or {}
            out.append(claim_fill(pr.get("text"), pr.get("claim")))
    return out


def _ms_values(obj, out: list) -> None:
    """Every number under a key ending in Ms (atMs, revealAtMs, startMs, questionAtMs, ...)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _num(v) and k.endswith("Ms"):
                out.append(v)
            else:
                _ms_values(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _ms_values(v, out)


def _change_frames(manifest: dict, timeline: list[dict], fps: float) -> set[int]:
    """Frames at or next to which the visible texts can change: every cue (with and without the
    3-frame lead), every world step time, and every fallback frame of every scene."""
    ms: list = []
    _ms_values({k: manifest.get(k) for k in ("scenes", "overlays", "world")}, ms)
    ms += [st["t"] for st in timeline]
    for sc in manifest.get("scenes", []):
        for side in ("left", "right"):
            panel = (sc.get("props") or {}).get(side)
            if isinstance(panel, dict) and panel.get("kind") == "world" and isinstance(panel.get("world"), dict):
                ms += [st["t"] for st in local_timeline(panel.get("steps") or [], "", sc.get("startMs", 0))]
    frames: set[int] = set()
    for v in ms:
        f = ms_to_frame(v, fps)
        frames.update(range(f - LEAD_FRAMES - 1, f + 2))
    for ov in manifest.get("overlays") or []:  # chip expiry: never under CHIP_MIN_MS
        if _num(ov.get("startMs")):
            f = ms_to_frame(ov["startMs"] + CHIP_MIN_MS, fps)
            frames.update(range(f - 1, f + 2))
    for sc in manifest.get("scenes", []):
        f0 = ms_to_frame(sc.get("startMs", 0), fps)
        frames.add(f0 + 45)
        for i in range(64):
            frames.update((f0 + _fallback(i), f0 + 12 + 30 * i))
    return frames


def visible_text(manifest: dict, lo: float, hi: float) -> str:
    """Text on screen at some moment of [lo, hi] (ms): visible_texts_at at lo, at hi and at every
    frame inside the window at which the texts can change (cue frames, step times, fallbacks)."""
    fps = _fps(manifest)
    timeline = world_timeline(manifest)
    frames = _change_frames(manifest, timeline, fps)
    step = 1000 / fps
    times = {lo, hi} | {f * step for f in frames if lo <= f * step <= hi}
    seen: dict[str, None] = {}
    for now in sorted(times):
        for x in visible_texts_at(manifest, now, timeline):
            if x is None or x == "":
                continue
            seen.setdefault(_js_str(x) if _num(x) else str(x), None)
    return " ".join(seen)
