#!/usr/bin/env python3
"""tts.py: script.json -> audio/turn-<id>.wav, audio/episode.wav, timing.json (turn level).

Usage:
  python3 tts.py <episode-dir> [options]

<episode-dir> holds script.json (the `<slug>/` folder of the workspace).

Modes:
  default            one Gemini call per turn (single voice), clips measured from samples
  --mode chunk --experimental
                     EXPERIMENTAL, not for delivery: one two-speaker call per 3 to 8 turns of one
                     segment; turn cuts are guessed from silences and word counts, so a cut can give
                     one host's words to the other. align.mjs and fidelity.py catch a wrong cut, but
                     the per-turn default is the only supported mode.
  --scratch          free macOS `say` voices for a timing draft (timing.json gets scratch:true)
  --dry-run          print turns, characters, estimated duration and cost; no API call
  --audition A,B,C   one sentence per voice into audio/audition/, nothing else changes

Redo:
  --only t03,t04     synthesise only these turns (or their chunks); every other turn must
                     already have a cached take for its current text
  --segment seg02    the same for every turn of a segment
  --retake           force a new take for the selected turns even when the cache matches

Outputs:
  audio/cache/<hash>.wav   raw take as returned by the API (the hash covers text, voice,
                           style, model, mode), so unchanged turns are never billed twice
  audio/turn-<id>.wav      silence-trimmed clip, raw level (no loudness change)
  audio/episode.wav        250 ms lead, then each clip; after a clip comes the turn's holdAfterMs
                           (a pause-and-think hold) when it sets one, then gapMs silence, or tailPadMs
                           after the last turn of a segment; loudness-normalised (two-pass loudnorm,
                           -19 LUFS, true peak -4.5 dBTP: pe_common.MONO_LUFS / MONO_TRUE_PEAK). holdAfterMs is not in the cache hash.
  timing.json              turn-level timing, integer ms from the start of episode.wav; each turn has
                           audioSha (digest of its take) and, with a hold, holdStartMs/holdEndMs
  audio/tts-report.json    calls, latency, tokens, cost, loudness of the last run, and changedTurns
                           (every turn whose take changed: realign exactly these)
  audio/cache/pins.json    turn -> its own take, after a selective --retake of one of several
                           turns with identical text (the others keep the shared take)

audio/, audio/cache/ and every file in them must be real folders and files under the episode
folder; a symbolic link anywhere there is refused (pe_common.safe_path).

The API key comes from env GEMINI_API_KEY, else the single variable GEMINI_API_KEY in
~/.config/podcast-explainer/env. The key is never printed, logged or written to a file: it is checked
for header-safe characters before any request, and every log line, error, report and cache
metadata file passes through pe_common.redact().
"""
from __future__ import annotations

import argparse
import array
import base64
import concurrent.futures as cf
import datetime as dt
import hashlib
import io
import json
import math
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402

SR = 24_000
DEFAULT_MODEL = "gemini-3.8-flash-tts"
FALLBACK_MODEL = "gemini-3.8-flash-lite-tts"
BANNED_MODELS = {"gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"}
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ENV_FILE = pc.ENV_FILE
SECS_PER_WORD = 0.40          # sanity check only (about 150 words per minute)
AUDIO_TOKENS_PER_SEC = 25     # Gemini API pricing page
# USD per 1M tokens (text in, audio out). Source: https://ai.google.dev/gemini-api/docs/pricing (read 2 Nov 2026).
PRICES = {
    "gemini-3.8-flash-tts": {"until-2026-12-31": (0.50, 9.00), "from-2027-01-01": (1.00, 18.00)},
    "gemini-3.8-flash-lite-tts": {"until-2026-12-31": (0.50, 6.00), "from-2027-01-01": (1.00, 12.00)},
}
SCRATCH_VOICES = ["Samantha", "Daniel", "Karen", "Moira"]
# Default Gemini voice per host role (the learner's choice, 2 Nov 2026; references/gemini-tts.md section 4).
# Used only when a speaker in script.json has no "voice"; the run logs the fallback.
DEFAULT_VOICES = {"learner": "Sulafat", "expert": "Iapetus"}
TAG_RE = re.compile(r"<([a-z][a-z \-]*)>")
PIPE_RE = re.compile(r"\|[^|]*\|")
SILENCE_DBFS = -45.0          # trim threshold
SPLIT_DBFS = -40.0            # chunk-mode gap threshold
WIN = SR // 100               # 10 ms analysis window
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}


class TtsError(RuntimeError):
    """A failure that stops the run. The message names the turn or file."""


class FatalHttp(TtsError):
    """A non-retryable API error (bad request, auth)."""


def log(msg: str) -> None:
    print(pc.redact(msg), flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"tts.py: error: {pc.redact(msg)}", file=sys.stderr, flush=True)
    sys.exit(code)


# --------------------------------------------------------------------------- key

def load_api_key() -> str:
    """Env first, then the single variable from the .env file (shared parser in pe_common).
    The key is validated for header-safe characters and registered for redaction. Never printed."""
    try:
        key, _where = pc.load_api_key(ENV_FILE)
    except pc.KeyError_ as e:
        raise TtsError(str(e)) from None
    if not key:
        raise TtsError(f"no API key: set env GEMINI_API_KEY or add GEMINI_API_KEY to {ENV_FILE}")
    return key


# --------------------------------------------------------------------------- script

def load_script(ep: Path) -> dict:
    path = ep / "script.json"
    if not path.is_file():
        raise TtsError(f"{path} not found")
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TtsError(f"{path}: invalid JSON: {e}") from e
    speakers = {sp.get("id"): sp for sp in s.get("speakers", [])}
    if not speakers or None in speakers:
        raise TtsError(f"{path}: speakers[] must be non-empty and each needs an id")
    for sid, sp in speakers.items():
        if not sp.get("voice"):
            role = sp.get("role")
            if role not in DEFAULT_VOICES:
                raise TtsError(f"{path}: speaker '{sid}' has no voice and no role (learner or expert) to pick a default")
            sp["voice"] = DEFAULT_VOICES[role]
            log(f"{path}: speaker '{sid}' has no voice; using the {role} default {sp['voice']}")
    seen: set[str] = set()
    if not s.get("segments"):
        raise TtsError(f"{path}: segments[] is empty")
    for seg in s["segments"]:
        if not seg.get("id") or not seg.get("turns"):
            raise TtsError(f"{path}: segment '{seg.get('id')}' needs an id and at least one turn")
        for t in seg["turns"]:
            tid = t.get("id")
            if not tid or tid in seen:
                raise TtsError(f"{path}: turn id '{tid}' is missing or duplicated")
            try:
                pc.check_id(tid, "turn")  # turn ids become file names: audio/turn-<id>.wav
            except pc.BadId as e:
                raise TtsError(f"{path}: {e}") from None
            seen.add(tid)
            if t.get("speaker") not in speakers:
                raise TtsError(f"{path}: turn {tid}: unknown speaker '{t.get('speaker')}'")
            if not str(t.get("text", "")).strip():
                raise TtsError(f"{path}: turn {tid}: empty text")
    return s


def hold_ms(t: dict) -> int:
    """Extra silence after a turn (script.json holdAfterMs, default 0)."""
    v = t.get("holdAfterMs", 0) or 0
    if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 15000:
        raise TtsError(f"turn {t.get('id')}: holdAfterMs must be an integer 0..15000, got {v!r}")
    return v


def flat_turns(script: dict) -> list[dict]:
    out = []
    for seg in script["segments"]:
        for i, t in enumerate(seg["turns"]):
            hold_ms(t)
            out.append({**t, "segment": seg["id"], "lastInSegment": i == len(seg["turns"]) - 1})
    return out


def spoken_words(text: str) -> list[str]:
    plain = PIPE_RE.sub(" ", TAG_RE.sub(" ", text))
    return [w for w in re.split(r"\s+", plain) if re.search(r"[A-Za-z0-9]", w)]


def expected_secs(text: str) -> float:
    secs = len(spoken_words(text)) * SECS_PER_WORD
    for tag in TAG_RE.findall(text):
        secs += 2.3 if tag == "long pause" else 0.5 if tag == "short pause" else 0.4
    secs += 0.4 * len(PIPE_RE.findall(text))
    return max(secs, 0.4)


def text_for_api(text: str, mode: str) -> str:
    """Per-turn mode is single voice: a |backchannel| would be spoken by the same host."""
    if mode == "per-turn":
        text = re.sub(r"\s{2,}", " ", PIPE_RE.sub(" ", text)).strip()
    return text.strip()


def turn_style(script: dict, t: dict) -> str:
    sp = next(s for s in script["speakers"] if s["id"] == t["speaker"])
    return (t.get("style") or sp.get("style") or "").strip()


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


# --------------------------------------------------------------------------- audio helpers

def decode_audio(data: bytes, mime: str = "") -> array.array:
    """Return 16-bit mono 24 kHz samples. 3.8 unary returns WAV; older models raw L16."""
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data)) as w:
            fmt = (w.getframerate(), w.getnchannels(), w.getsampwidth())
            frames = w.readframes(w.getnframes())
        if fmt != (SR, 1, 2):
            frames = ffmpeg_to_pcm(data)
    else:
        if "rate=" in mime and f"rate={SR}" not in mime:
            raise TtsError(f"unexpected audio format {mime}")
        frames = data
    a = array.array("h")
    a.frombytes(frames[: len(frames) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    return a


def ffmpeg_to_pcm(data: bytes) -> bytes:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1"],
                       input=data, capture_output=True)
    if r.returncode != 0:
        raise TtsError(f"ffmpeg could not decode audio: {r.stderr.decode(errors='replace')[:300]}")
    return r.stdout


def read_wav(path: Path) -> array.array:
    return decode_audio(path.read_bytes())


def write_wav(path: Path, samples: array.array) -> None:
    """Mono 16-bit wav, written through an exclusive temporary file (C02)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        b = samples
        if sys.byteorder == "big":
            b = array.array("h", samples)
            b.byteswap()
        w.writeframes(b.tobytes())
    try:
        pc.atomic_write(path, buf.getvalue())
    except pc.BadId as e:
        raise TtsError(str(e)) from None


def window_peaks(a: array.array) -> list[int]:
    peaks = []
    for i in range(0, len(a), WIN):
        seg = a[i:i + WIN]
        peaks.append(max(max(seg), -min(seg)) if seg else 0)
    return peaks


def thr(dbfs: float) -> int:
    return int(32768 * 10 ** (dbfs / 20))


def speech_bounds(a: array.array, pre_ms: int = 30, post_ms: int = 60) -> tuple[int, int]:
    """Sample range that holds the speech, with a short margin. (0, 0) when silent."""
    peaks = window_peaks(a)
    t = thr(SILENCE_DBFS)
    loud = [i for i, p in enumerate(peaks) if p > t]
    if not loud:
        return 0, 0
    s = max(0, loud[0] * WIN - pre_ms * SR // 1000)
    e = min(len(a), (loud[-1] + 1) * WIN + post_ms * SR // 1000)
    return s, e


def trim(a: array.array) -> array.array:
    s, e = speech_bounds(a)
    return a[s:e]


def silences(a: array.array, lo: int, hi: int, min_ms: int = 120) -> list[tuple[int, int]]:
    """Quiet runs (sample ranges) inside [lo, hi) at least min_ms long."""
    peaks = window_peaks(a)
    t = thr(SPLIT_DBFS)
    out, run = [], None
    for i, p in enumerate(peaks):
        quiet = p <= t and lo <= i * WIN < hi
        if quiet and run is None:
            run = i
        elif not quiet and run is not None:
            if (i - run) * 10 >= min_ms:
                out.append((run * WIN, i * WIN))
            run = None
    return out


def peak_dbfs(a: array.array) -> float:
    if not a:
        return -120.0
    p = max(max(a), -min(a))
    return 20 * math.log10(max(p, 1) / 32768)


# --------------------------------------------------------------------------- units of synthesis

def build_units(script: dict, turns: list[dict], mode: str, model: str, scratch: bool,
                max_chunk_turns: int, max_chunk_chars: int) -> list[dict]:
    """A unit is one API call: one turn (per-turn, scratch) or 1 to 8 turns of one segment (chunk)."""
    voices = {sp["id"]: sp["voice"] for sp in script["speakers"]}
    units = []
    if scratch or mode == "per-turn":
        order = [sp["id"] for sp in script["speakers"]]
        for t in turns:
            text = text_for_api(t["text"], "per-turn")
            style = "" if scratch else turn_style(script, t)
            voice = SCRATCH_VOICES[order.index(t["speaker"]) % len(SCRATCH_VOICES)] if scratch else voices[t["speaker"]]
            eng = "macos-say" if scratch else model
            units.append({"id": t["id"], "turns": [t], "texts": [text], "styles": [style], "voice": voice,
                          "engine": eng, "hash": sha({"e": eng, "v": voice, "s": style, "t": text, "m": "per-turn"})})
        return units
    if len(script["speakers"]) != 2:
        raise TtsError("--mode chunk needs exactly two speakers in script.json")
    names = speaker_names(script)
    for seg in script["segments"]:
        st = [t for t in turns if t["segment"] == seg["id"]]
        n_chunks = math.ceil(len(st) / max_chunk_turns)
        size = math.ceil(len(st) / n_chunks)
        groups = [st[i:i + size] for i in range(0, len(st), size)]
        final = []
        for g in groups:  # split again by characters, at turn boundaries only
            cur, chars = [], 0
            for t in g:
                if cur and chars + len(t["text"]) > max_chunk_chars:
                    final.append(cur)
                    cur, chars = [], 0
                cur.append(t)
                chars += len(t["text"])
            final.append(cur)
        for k, g in enumerate(final, 1):
            texts = [text_for_api(t["text"], "chunk") for t in g]
            styles = [turn_style(script, t) for t in g]
            spk = [names[t["speaker"]] for t in g]
            cfg = sorted((names[s], v) for s, v in voices.items())
            uid = f"{seg['id']}-c{k:02d}"
            units.append({"id": uid, "turns": g, "texts": texts, "styles": styles, "voice": cfg, "engine": model,
                          "hash": sha({"e": model, "v": cfg, "s": styles, "t": texts, "sp": spk, "m": "chunk"})})
    return units


def speaker_names(script: dict) -> dict:
    names = {}
    for sp in script["speakers"]:
        name = (sp.get("name") or sp["id"]).strip()
        names[sp["id"]] = name
    if len(set(names.values())) != len(names):
        names = {sp["id"]: sp["id"] for sp in script["speakers"]}
    return names


def unit_expected(unit: dict) -> float:
    return sum(expected_secs(t) for t in unit["texts"])


def request_body(script: dict, unit: dict) -> dict:
    gen = {"responseModalities": ["AUDIO"]}
    if len(unit["turns"]) == 1 and not isinstance(unit["voice"], list):
        part = {"text": unit["texts"][0]}
        if unit["styles"][0]:
            part["speech_metadata"] = {"style": unit["styles"][0]}
        gen["speechConfig"] = {"voiceConfig": {"voice": unit["voice"]}}
        return {"contents": [{"role": "user", "parts": [part]}], "generationConfig": gen}
    names = speaker_names(script)
    parts = []
    for t, text, style in zip(unit["turns"], unit["texts"], unit["styles"]):
        md = {"speaker": names[t["speaker"]]}
        if style:
            md["style"] = style
        parts.append({"text": text, "speech_metadata": md})
    gen["speechConfig"] = {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
        {"speaker": name, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}} for name, voice in unit["voice"]]}}
    return {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}


# --------------------------------------------------------------------------- API call

def post_json(key: str, model: str, body: dict, timeout: float) -> dict:
    pc.validate_key(key)  # before the header exists, so a bad key never reaches an exception text
    req = urllib.request.Request(ENDPOINT.format(model=model), data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_error_detail(e: urllib.error.HTTPError) -> tuple[str, float]:
    """Return (message, retry-after seconds). External error text is untrusted: an API or proxy
    can reflect the request, so the message is redacted before anything else sees it."""
    retry_after = 0.0
    msg = f"HTTP {e.code}"
    err: dict = {}
    try:
        raw = e.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    try:
        body = json.loads(raw)
        err = body.get("error", {}) if isinstance(body, dict) else {}
        msg = f"HTTP {e.code} {err.get('status', '')}: {err.get('message', '')}".strip()
    except json.JSONDecodeError:
        if raw.strip():
            flat = re.sub(r"\s+", " ", raw)[:300]
            msg = f"HTTP {e.code}: {flat}"
    try:
        for d in err.get("details", []):
            if str(d.get("@type", "")).endswith("RetryInfo"):
                m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
                if m:
                    retry_after = float(m.group(1))
    except Exception:
        pass
    ra = e.headers.get("Retry-After") if e.headers else None
    if ra and str(ra).isdigit():
        retry_after = max(retry_after, float(ra))
    return pc.redact(msg)[:500], retry_after


def synth_api(key: str, script: dict, unit: dict, tries: int, timeout: float, min_ratio: float,
              max_ratio: float) -> tuple[bytes, dict]:
    """One unit through the API with retries. Returns (raw audio bytes, meta)."""
    body = request_body(script, unit)
    expected = unit_expected(unit)
    n_words = sum(len(spoken_words(t)) for t in unit["texts"])
    last = "no attempt"
    calls = []
    for attempt in range(1, tries + 1):
        t0 = time.monotonic()
        retry_after = 0.0
        try:
            resp = post_json(key, unit["engine"], body, timeout)
            latency = time.monotonic() - t0
            usage = resp.get("usageMetadata", {})
            calls.append({"latencyS": round(latency, 2), "usage": usage})
            fb = resp.get("promptFeedback", {})
            if fb.get("blockReason"):
                raise FatalHttp(f"prompt blocked: {fb.get('blockReason')}")
            cands = resp.get("candidates") or []
            if not cands:
                raise ValueError("response has no candidates")
            cand = cands[0]
            finish = cand.get("finishReason", "?")
            data, mime = b"", ""
            for p in (cand.get("content") or {}).get("parts", []):
                inl = p.get("inlineData") or p.get("inline_data")
                if inl and inl.get("data"):
                    data += base64.b64decode(inl["data"])
                    mime = inl.get("mimeType", "")
            if not data:
                raise ValueError(f"empty audio (finishReason {finish})")
            pcm = decode_audio(data, mime)
            s, e = speech_bounds(pcm)
            secs = (e - s) / SR
            ratio = secs / expected
            if finish != "STOP":
                raise ValueError(f"finishReason {finish} ({secs:.1f} s of audio, expected about {expected:.1f} s)")
            if secs < 0.15:
                raise ValueError("audio is silent")
            if n_words >= 4 and ratio < min_ratio:
                raise ValueError(f"possible truncation: {secs:.1f} s, expected about {expected:.1f} s")
            if ratio > max_ratio and secs - expected > 2.0:
                raise ValueError(f"possible hallucination: {secs:.1f} s, expected about {expected:.1f} s")
            return data, {"finishReason": finish, "speechS": round(secs, 3), "expectedS": round(expected, 2),
                          "attempts": attempt, "calls": calls, "mime": mime}
        except urllib.error.HTTPError as e:
            msg, retry_after = http_error_detail(e)
            calls.append({"latencyS": round(time.monotonic() - t0, 2), "error": msg})
            if e.code not in RETRYABLE_HTTP:
                raise FatalHttp(f"{unit['id']}: {msg}") from None
            last = msg
        except FatalHttp as e:
            raise FatalHttp(pc.redact(f"{unit['id']}: {e}")) from None
        except pc.KeyError_ as e:
            raise FatalHttp(f"{unit['id']}: {e}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, TtsError) as e:
            last = pc.redact(str(getattr(e, "reason", e)))
        if attempt < tries:
            wait = max(retry_after, 2 ** attempt) + random.uniform(0, 1)
            log(f"  {unit['id']}: take {attempt} failed ({last}); retry in {wait:.0f} s")
            time.sleep(wait)
    err = TtsError(f"{unit['id']}: failed after {tries} tries: {last}")
    err.calls = calls  # type: ignore[attr-defined]
    raise err


def synth_scratch(unit: dict) -> tuple[bytes, dict]:
    if not shutil.which("say"):
        raise TtsError("--scratch needs macOS `say`")
    text = PIPE_RE.sub(" ", TAG_RE.sub(" ", unit["texts"][0])).strip()
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "s.wav"
        r = subprocess.run(["say", "-v", unit["voice"], "-o", str(out), "--file-format=WAVE",
                            f"--data-format=LEI16@{SR}", text], capture_output=True)
        if r.returncode != 0 or not out.is_file():
            raise TtsError(f"{unit['id']}: say failed: {r.stderr.decode(errors='replace')[:200]}")
        data = out.read_bytes()
    s, e = speech_bounds(decode_audio(data))
    return data, {"finishReason": "SCRATCH", "attempts": 1, "calls": [], "speechS": round((e - s) / SR, 3)}


# --------------------------------------------------------------------------- chunk splitting

def split_chunk(pcm: array.array, unit: dict) -> list[dict]:
    """Cut a two-speaker take into turn pieces. Returns [{start, end, source}] in samples."""
    s0, s1 = speech_bounds(pcm)
    n = len(unit["turns"])
    if n == 1:
        return [{"start": s0, "end": s1, "source": "clip"}]
    weights = [max(expected_secs(t), 0.3) for t in unit["texts"]]
    total = sum(weights)
    span = s1 - s0
    expect = []
    acc = 0.0
    for w in weights[:-1]:
        acc += w
        expect.append(s0 + span * acc / total)
    gaps = silences(pcm, s0, s1)
    avg = span / n
    tol = max(0.6 * SR, 0.4 * avg)
    cuts, sources, prev = [], [], s0
    for k, x in enumerate(expect):
        best, best_score = None, None
        for g in gaps:
            mid = (g[0] + g[1]) / 2
            if mid <= prev + 0.2 * SR or abs(mid - x) > tol:
                continue
            length = (g[1] - g[0]) / SR
            score = abs(mid - x) / tol - 0.5 * min(length / 0.6, 1.0)
            if best_score is None or score < best_score:
                best, best_score = g, score
        if best is not None:
            cut = int((best[0] + best[1]) / 2)
            sources.append("silence")
        else:
            cut = int(max(x, prev + 0.2 * SR))
            sources.append("proportional")
        cuts.append(cut)
        prev = cut
    bounds = [s0] + cuts + [s1]
    out = []
    for i in range(n):
        a, b = bounds[i], bounds[i + 1]
        ps, pe = speech_bounds(pcm[a:b])
        if pe <= ps:
            ps, pe = 0, b - a
        left = sources[i - 1] if i > 0 else "silence"
        right = sources[i] if i < n - 1 else "silence"
        src = "silence" if left == right == "silence" else "proportional"
        out.append({"start": a + ps, "end": a + pe, "source": src})
    return out


# --------------------------------------------------------------------------- loudness

# episode.wav is mono. Remotion plays it as dual-mono stereo in the AAC track, which measures about
# 3 LU louder (measured 2 Nov 2026: wav -16.1 LUFS gave an mp4 at -13.2 LUFS, +0.8 dBTP). So the
# mono target is -19 LUFS, which lands near -16 LUFS in the mp4 that qc.py probe measures.
# Remotion's AAC encode also raises the true peak, by 1.6 to 2.3 dB. History (2 Nov 2026,
# consistent-hashing): wav -1.5 dBTP -> mp4 +0.1; ceiling -3.0 (measured -2.8) -> mp4 -0.7, a fail;
# ceiling -4.0 (measured -3.8) -> mp4 -1.5 dBTP, a pass with 0.5 dB margin. The default since then is
# the ONE constant pc.MONO_TRUE_PEAK (-4.5) for more margin; the e2e-v3 render measured -2.0 dBTP.
MONO_LUFS = pc.MONO_LUFS
MONO_TRUE_PEAK = pc.MONO_TRUE_PEAK


def loudnorm(src: Path, dst: Path, target: float = MONO_LUFS, tp: float = MONO_TRUE_PEAK, lra: float = 11.0) -> dict:
    base = f"loudnorm=I={target}:TP={tp}:LRA={lra}"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", f"{base}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    if r.returncode != 0 or not m:
        raise TtsError(f"loudnorm pass 1 failed on {src}: {r.stderr[-300:]}")
    p1 = json.loads(m.group(0))
    if p1["input_i"] in ("-inf", "inf"):
        raise TtsError(f"{src} is silent; loudnorm cannot measure it")
    flt = (f"{base}:measured_I={p1['input_i']}:measured_TP={p1['input_tp']}:measured_LRA={p1['input_lra']}"
           f":measured_thresh={p1['input_thresh']}:offset={p1['target_offset']}:linear=true:print_format=json")
    try:  # C02: ffmpeg writes into a new exclusive file, never a guessable '.norm.wav' that could be a link
        tmp = pc.exclusive_temp(dst.parent, dst.stem + ".norm", ".wav")
    except pc.BadId as e:
        raise TtsError(str(e)) from None
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(src), "-af", flt, "-ar", str(SR),
                        "-ac", "1", "-c:a", "pcm_s16le", str(tmp)], capture_output=True, text=True)
    m2 = re.search(r"\{[^{}]*\"output_i\"[^{}]*\}", r.stderr)
    if r.returncode != 0 or not m2:
        tmp.unlink(missing_ok=True)
        raise TtsError(f"loudnorm pass 2 failed on {src}: {r.stderr[-300:]}")
    p2 = json.loads(m2.group(0))
    # keep the sample count identical to the unnormalised join, so timing.json stays exact
    want = len(read_wav(src))
    got = read_wav(tmp)
    if len(got) != want:
        got = got[:want] if len(got) > want else got + array.array("h", [0]) * (want - len(got))
    write_wav(dst, got)
    tmp.unlink(missing_ok=True)
    return {"inputLUFS": float(p1["input_i"]), "outputLUFS": float(p2["output_i"]),
            "outputTruePeakDb": float(p2["output_tp"]), "normalizationType": p2.get("normalization_type"),
            "peakDbfs": round(peak_dbfs(got), 2)}


# --------------------------------------------------------------------------- cost

def price(model: str) -> tuple[float, float]:
    p = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return p["until-2026-12-31"] if dt.date.today() <= dt.date(2026, 12, 31) else p["from-2027-01-01"]


def cost_usd(model: str, in_tokens: float, out_tokens: float) -> float:
    pin, pout = price(model)
    return in_tokens * pin / 1e6 + out_tokens * pout / 1e6


def usage_tokens(meta: dict, unit: dict) -> tuple[int, int, bool]:
    """(input, output, measured?) summed over every call of the unit, failed takes included."""
    tin = tout = 0
    measured = False
    for c in meta.get("calls", []):
        u = c.get("usage") or {}
        if u:
            measured = True
            tin += int(u.get("promptTokenCount", 0))
            tout += int(u.get("candidatesTokenCount", 0))
    if not measured:
        tin = sum(len(t) for t in unit["texts"]) // 4 + 10
        tout = int(meta.get("speechS", unit_expected(unit)) * AUDIO_TOKENS_PER_SEC)
    return tin, tout, measured


# --------------------------------------------------------------------------- main flow

PIN_FILE = "pins.json"


def cache_file(cache: Path, key: str, suffix: str) -> Path:
    """A file in audio/cache/; refuses a symbolic link there (C02)."""
    if not re.fullmatch(r"[0-9a-f]{8,64}", key or ""):
        raise TtsError(f"bad cache key {key!r}")
    p = cache / f"{key}{suffix}"
    if p.is_symlink():
        raise TtsError(f"{p} is a symbolic link; refusing to follow it. Delete it and rerun.")
    return p


def load_pins(cache: Path) -> dict:
    """audio/cache/pins.json: {turnId: {hash, take}}. A pin gives one turn its own take while
    another turn has the same request hash (a selective retake of one of two identical turns)."""
    p = cache / PIN_FILE
    if not p.is_file() or p.is_symlink():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("hash") and v.get("take")}


def save_pins(cache: Path, pins: dict, units: list[dict]) -> None:
    live = {u["id"]: pins[u["id"]] for u in units if u["id"] in pins and pins[u["id"]]["hash"] == u["hash"]}
    p = cache / PIN_FILE
    if p.is_symlink():
        raise TtsError(f"{p} is a symbolic link; refusing to follow it")
    if live:  # C02: exclusive temporary file, never a guessable '.part' name
        try:
            pc.atomic_write(p, json.dumps(live, indent=1, sort_keys=True) + "\n")
        except pc.BadId as e:
            raise TtsError(str(e)) from None
    elif p.exists():
        p.unlink()


def take_key(u: dict, pins: dict, cache: Path) -> str:
    """The cache key of the take this unit plays: its pinned take while the text is unchanged
    and the take exists, else the request hash."""
    pin = pins.get(u["id"])
    if pin and pin.get("hash") == u["hash"] and re.fullmatch(r"[0-9a-f]{8,64}", pin.get("take", "")) \
            and (cache / f"{pin['take']}.wav").is_file():
        return pin["take"]
    return u["hash"]


def select_turns(turns: list[dict], only: str | None, segment: str | None) -> set[str] | None:
    if not only and not segment:
        return None
    ids = {t["id"] for t in turns}
    sel: set[str] = set()
    if only:
        want = {x.strip() for x in only.split(",") if x.strip()}
        missing = want - ids
        if missing:
            raise TtsError(f"--only: unknown turn id(s) {', '.join(sorted(missing))}")
        sel |= want
    if segment:
        segs = {x.strip() for x in segment.split(",") if x.strip()}
        found = {t["segment"] for t in turns}
        if segs - found:
            raise TtsError(f"--segment: unknown segment id(s) {', '.join(sorted(segs - found))}")
        sel |= {t["id"] for t in turns if t["segment"] in segs}
    return sel


def dry_run(script: dict, turns: list[dict], units: list[dict], model: str, cache: Path, mode: str,
            gap_ms: int = pc.DEFAULT_GAP_MS, tail_pad_ms: int = pc.DEFAULT_TAIL_PAD_MS, lead_ms: int = pc.DEFAULT_LEAD_MS) -> dict:
    chars = sum(len(t["text"]) for t in turns)
    words = sum(len(spoken_words(t["text"])) for t in turns)
    est = sum(expected_secs(t["text"]) for t in turns)
    holds = sum(hold_ms(t) for t in turns) / 1000
    cached = sum(1 for u in units if cache_file(cache, u["key"], ".wav").is_file())
    to_bill = [u for u in units if not cache_file(cache, u["key"], ".wav").is_file()]
    bill_s = sum(unit_expected(u) for u in to_bill)
    tin = sum(len(t) for u in to_bill for t in u["texts"]) // 4 + 10 * len(to_bill)
    c = cost_usd(model, tin, bill_s * AUDIO_TOKENS_PER_SEC)
    full = cost_usd(model, chars // 4 + 10 * len(units), est * AUDIO_TOKENS_PER_SEC)
    log(f"dry run: {len(turns)} turns in {len(script['segments'])} segments, {chars} characters, {words} words")
    log(f"  mode {mode}, model {model}, {len(units)} API calls ({cached} cached, {len(to_bill)} to bill)")
    log(f"  estimated speech {est:.0f} s ({est / 60:.1f} min) at {SECS_PER_WORD} s per word"
        f" (measured Gemini pace is about 0.357 s per word, so expect about 11% less)")
    if holds:
        log(f"  plus {holds:.0f} s of pause holds ({sum(1 for t in turns if hold_ms(t))} turns with holdAfterMs), not billed")
    # The same gate validate_script.py runs (E39/W39, series cap): pe_common.length_check.
    chk = pc.length_check(script, None, gap_ms, tail_pad_ms, lead_ms)
    pred = chk["pred"]
    log(f"  predicted final length {pred['totalSec']:.0f} s ({pred['totalSec'] / 60:.2f} min): speech {pred['speechSec']:.0f} s, "
        f"holds {pred['holdSec']:.0f} s, gaps {pred['gapSec']:.0f} s, segment tails {pred['tailSec']:.0f} s, lead {pred['leadSec']:.2f} s")
    for level, code, msg in chk["problems"]:
        log(f"  {'ERROR' if level == 'error' else 'warning'} {code}: {msg}")
    log(f"  estimated cost now ${c:.4f} (full episode without cache ${full:.4f}; retries add up to 3x)")
    for seg in script["segments"]:
        st = [t for t in turns if t["segment"] == seg["id"]]
        log(f"  {seg['id']}: {len(st)} turns, {sum(len(t['text']) for t in st)} chars, "
            f"about {sum(expected_secs(t['text']) for t in st):.0f} s")
    long_turns = [t["id"] for t in turns if len(t["text"]) > 500]
    if long_turns:
        log(f"  warning: turns over 500 characters (split them): {', '.join(long_turns)}")
    return {"predicted": pred, "lengthVerdict": chk["verdict"], "problems": chk["problems"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Gemini TTS for a two-host explainer: script.json -> audio + timing.json")
    ap.add_argument("episode", type=Path, help="episode folder that holds script.json")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--mode", choices=["per-turn", "chunk"], default="per-turn")
    ap.add_argument("--scratch", action="store_true", help="macOS say voices, free timing draft")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="comma-separated turn ids to synthesise")
    ap.add_argument("--segment", help="comma-separated segment ids to synthesise")
    ap.add_argument("--retake", action="store_true", help="new takes for the selected turns even if cached")
    ap.add_argument("--audition", help="comma-separated voice names: one sentence each into audio/audition/")
    ap.add_argument("--audition-text", help="sentence for --audition (default: first sentence of the script)")
    ap.add_argument("--gap-ms", type=int, default=250)
    ap.add_argument("--tail-pad-ms", type=int, default=600)
    ap.add_argument("--lead-ms", type=int, default=250)
    ap.add_argument("--lufs", type=float, default=MONO_LUFS,
                    help=f"integrated loudness of the mono episode.wav (default {MONO_LUFS}; the stereo mp4 then measures about -16)")
    ap.add_argument("--true-peak", type=float, default=MONO_TRUE_PEAK,
                    help=f"true-peak ceiling of episode.wav in dBTP (default {MONO_TRUE_PEAK}; Remotion adds about 1.6 dB, "
                         f"qc.py needs the mp4 below -1)")
    ap.add_argument("--experimental", action="store_true",
                    help="required with --mode chunk: chunk turn cuts are guessed and not supported for delivery")
    ap.add_argument("--no-normalize", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--min-ratio", type=float, default=0.5, help="shortest accepted speech / expected (truncation)")
    ap.add_argument("--max-ratio", type=float, default=2.5, help="longest accepted speech / expected")
    ap.add_argument("--chunk-turns", type=int, default=8)
    ap.add_argument("--chunk-chars", type=int, default=1800)
    ap.add_argument("--allow-over-length", metavar="REASON",
                    help="pay for audio although pe_common.length_check reports an error (over 15%% above the target, or a "
                         "series part predicted over 684 s); the reason is recorded in timing.json lengthOverride")
    args = ap.parse_args()

    if args.model in BANNED_MODELS:
        die(f"{args.model} is deprecated (shutdown 17 Nov 2026). Use {DEFAULT_MODEL} or {FALLBACK_MODEL}.")
    if args.mode == "chunk" and not args.scratch:
        if not args.experimental:
            die("--mode chunk is EXPERIMENTAL: turn cuts inside a chunk are guessed from silences and word counts and can "
                "give one host's words to the other. Use the default per-turn mode. To try it anyway, add --experimental.", 2)
        log("WARNING: EXPERIMENTAL chunk mode. Turn cuts are guesses; run align.mjs and fix every fidelity failure "
            "before you trust the result. Not for delivery without a full listen.")
    ep = args.episode.resolve()
    try:
        script = load_script(ep)
        if args.audition:
            return audition(ep, script, args)
        return run(ep, script, args)
    except TtsError as e:
        die(str(e))
    except KeyboardInterrupt:
        die("interrupted", 130)
    return 1


def audition(ep: Path, script: dict, args) -> int:
    voices = [v.strip() for v in args.audition.split(",") if v.strip()]
    for v in voices:  # voice names become file names: audio/audition/<voice>.wav
        try:
            pc.check_id(v, "voice")
        except pc.BadId as e:
            raise TtsError(f"--audition: {e}") from None
    text = args.audition_text
    if not text:
        first = flat_turns(script)[0]["text"]
        text = re.split(r"(?<=[.!?])\s+", PIPE_RE.sub(" ", first).strip())[0]
    out_dir = ep / "audio" / "audition"
    out_dir.mkdir(parents=True, exist_ok=True)
    unit_base = {"turns": [{"id": "audition"}], "texts": [text], "styles": [""], "engine": args.model}
    if args.dry_run:
        est = expected_secs(text) * len(voices)
        log(f"dry run: audition {len(voices)} voices, about {est:.0f} s, about ${cost_usd(args.model, 0, est * 25):.4f}")
        return 0
    key = load_api_key()
    total = 0.0
    log(f"audition text: \"{text}\"")
    for v in voices:
        unit = {**unit_base, "id": f"audition-{v}", "voice": v}
        data, meta = synth_api(key, script, unit, args.tries, args.timeout, args.min_ratio, args.max_ratio)
        clip = trim(decode_audio(data, meta.get("mime", "")))
        path = pc.inside(out_dir, out_dir / f"{v}.wav", "audition file")
        write_wav(path, clip)
        tin, tout, _ = usage_tokens(meta, unit)
        total += cost_usd(args.model, tin, tout)
        log(f"  {v}: {len(clip) / SR:.2f} s -> {path}  (afplay '{path}')")
    log(f"audition cost ${total:.4f}. Pick one voice per host and set speakers[].voice in script.json.")
    return 0


def run(ep: Path, script: dict, args) -> int:
    turns = flat_turns(script)
    mode = "per-turn" if args.scratch else args.mode
    model = "macos-say" if args.scratch else args.model
    units = build_units(script, turns, mode, args.model, args.scratch, args.chunk_turns, args.chunk_chars)
    try:  # C02: audio/ and audio/cache/ are real folders under the episode, never symbolic links
        audio = pc.safe_path(ep, ep / "audio", "audio folder")
        cache = pc.safe_path(ep, audio / "cache", "audio cache folder")
    except pc.BadId as e:
        raise TtsError(str(e)) from None
    pins = load_pins(cache)
    for u in units:
        u["key"] = take_key(u, pins, cache)
    if args.dry_run:
        res = dry_run(script, turns, units, args.model, cache, mode, args.gap_ms, args.tail_pad_ms, args.lead_ms)
        if res["lengthVerdict"] == "error":  # Q08: a length error is a failed dry run
            log("dry run FAILED: the script is over length (see ERROR above); the paid run refuses it without --allow-over-length")
            return 1
        return 0
    # Q08: the paid path runs the same length gate with the actual gap, tail and lead settings and
    # refuses to start on an error unless --allow-over-length REASON is given; the override is
    # recorded in timing.json lengthOverride. The free --scratch voice is never blocked.
    length_override = None
    if not args.scratch:
        chk = pc.length_check(script, None, args.gap_ms, args.tail_pad_ms, args.lead_ms)
        errs = [m for lv, _, m in chk["problems"] if lv == "error"]
        reason = getattr(args, "allow_over_length", None)
        if errs and not (isinstance(reason, str) and reason.strip()):
            raise TtsError("refusing paid synthesis: " + " | ".join(errs)
                           + ". Cut words first, or pass --allow-over-length \"<reason>\" to override (recorded in timing.json)")
        if errs:
            length_override = {"reason": args.allow_over_length, "predictedSec": round(chk["pred"]["totalSec"], 1),
                               "problems": errs}
            log(f"WARNING: --allow-over-length given ({args.allow_over_length!r}); predicted {chk['pred']['totalSec']:.0f} s; "
                "the override is recorded in timing.json lengthOverride")
    audio.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    pc.safe_path(ep, cache, "audio cache folder")
    sel = select_turns(turns, args.only, args.segment)

    todo, reuse = [], []
    hit_of = {u["id"]: cache_file(cache, u["key"], ".wav").is_file() for u in units}
    picked = {u["id"]: sel is None or any(t["id"] in sel for t in u["turns"]) for u in units}
    if args.retake and sel is not None:
        # N08: a selective retake of a turn whose take is shared with an unselected turn gets its
        # own take (a pin), so the other turn keeps its audio and its alignment.
        new_keys: dict[str, str] = {}  # one new take per shared old take, for all selected turns on it
        for u in units:
            if not picked[u["id"]]:
                continue
            old_key = u["key"]
            others = [x["id"] for x in units if x["key"] == old_key and not picked[x["id"]]]
            if others:
                if old_key not in new_keys:
                    new_keys[old_key] = pc.bytes_sha(f"{u['hash']}:{u['id']}:{time.time_ns()}".encode())
                    mine = [x["id"] for x in units if x["key"] == old_key and picked[x["id"]]]
                    log(f"  {', '.join(mine)}: share a take with {', '.join(others)}; the retake is pinned to "
                        f"{', '.join(mine)} only, {', '.join(others)} keep their audio and alignment")
                pins[u["id"]] = {"hash": u["hash"], "take": new_keys[old_key]}
                u["key"] = new_keys[old_key]
                hit_of[u["id"]] = False
    elif args.retake:
        for u in units:  # a full retake drops pins: identical turns share one new take again
            if picked[u["id"]] and u["id"] in pins:
                pins.pop(u["id"])
                u["key"] = u["hash"]
    todo_keys = {u["key"] for u in units if picked[u["id"]] and (not hit_of[u["id"]] or args.retake)}
    for u in units:
        hit = hit_of[u["id"]]
        if picked[u["id"]] and (not hit or args.retake):
            todo.append(u)
        elif hit or u["key"] in todo_keys:
            reuse.append(u)
        else:
            where = u["id"] if len(u["turns"]) == 1 else f"{u['turns'][0]['id']} (chunk {u['id']})"
            raise TtsError(f"turn {where} has no cached take for its current text; "
                           f"add it to --only/--segment or run without them")
    for t in turns:
        if mode == "per-turn" and not args.scratch and PIPE_RE.search(t["text"]):
            log(f"  warning: {t['id']}: |backchannels| need --mode chunk; removed for this per-turn take")

    # One job per take key: turns with identical voice, style and text share one take (and one
    # bill) unless a pin separates them, and two workers never write the same cache file.
    jobs: dict[str, dict] = {}
    for u in todo:
        jobs.setdefault(u["key"], u)
    shared = {h: [x["id"] for x in units if x["key"] == h] for h in jobs}
    dupes = {h: ids for h, ids in shared.items() if len(ids) > 1}
    for h, ids in dupes.items():
        log(f"  {', '.join(ids)}: identical text, voice and style; one take serves all of them")
    log(f"tts: {len(turns)} turns, {len(units)} units: {len(jobs)} to synthesise, {len(units) - len(todo)} from cache"
        + (f", {len(todo) - len(jobs)} sharing a take" if len(todo) > len(jobs) else "") + f" (mode {mode}, model {model})")
    key = None if args.scratch or not todo else load_api_key()
    report_units: dict[str, dict] = {}
    lock = threading.Lock()
    run_t0 = time.monotonic()

    def work(u: dict) -> tuple[dict, dict]:
        if args.scratch:
            data, meta = synth_scratch(u)
        else:
            data, meta = synth_api(key, script, u, args.tries, args.timeout, args.min_ratio, args.max_ratio)
        # C02: exclusive temporary files under the checked cache folder, then rename.
        try:
            pc.atomic_write(cache_file(cache, u["key"], ".wav"), data)
            info = pc.redact_obj({"unit": u["id"], "requestHash": u["hash"], "sharedBy": shared.get(u["key"], [u["id"]]),
                                  "engine": u["engine"], **meta, "created": dt.datetime.now().isoformat(timespec="seconds")})
            pc.atomic_write(cache_file(cache, u["key"], ".json"), json.dumps(info, indent=1))
        except pc.BadId as e:
            raise TtsError(str(e)) from None
        return u, meta

    failure = None
    workers = 1 if args.scratch else max(1, args.workers)
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(work, u): u for u in jobs.values()}
        for f in cf.as_completed(futs):
            u = futs[f]
            if f.cancelled():
                report_units[u["id"]] = {"error": "not started: the run stopped after an earlier failure", "calls": []}
                continue
            try:
                u, meta = f.result()
            except cf.CancelledError:
                report_units[u["id"]] = {"error": "not started: the run stopped after an earlier failure", "calls": []}
                continue
            except (TtsError, pc.KeyError_, OSError) as e:
                with lock:
                    if failure is None:
                        failure = e
                        for other in futs:
                            other.cancel()
                    report_units[u["id"]] = {"error": pc.redact(str(e)), "calls": getattr(e, "calls", [])}
                continue
            with lock:
                report_units[u["id"]] = meta
            lat = ", ".join(f"{c['latencyS']}s" for c in meta.get("calls", []) if "latencyS" in c)
            log(f"  {u['id']}: ok, {meta.get('speechS', 0):.2f} s speech, take {meta['attempts']}"
                + (f", latency {lat}" if lat else ""))
    billed_in = billed_out = 0
    measured_all = True
    for u in jobs.values():
        meta = report_units.get(u["id"])
        if not meta or args.scratch:
            continue
        tin, tout, measured = usage_tokens(meta, u) if "error" not in meta else (0, 0, True)
        if "error" in meta:  # failed takes were still billed when audio came back
            for c in meta.get("calls", []):
                us = c.get("usage") or {}
                tin += int(us.get("promptTokenCount", 0))
                tout += int(us.get("candidatesTokenCount", 0))
        billed_in += tin
        billed_out += tout
        measured_all &= measured
    run_cost = 0.0 if args.scratch else cost_usd(args.model, billed_in, billed_out)
    if failure is not None:
        log(f"cost of this run before the failure: ${run_cost:.4f}")
        raise TtsError(f"stopped, nothing assembled: {failure}. Fix the turn text or retry: "
                       f"python3 tts.py {shlex.quote(str(ep))} --only <turn id>")

    # ---- assemble
    lead = args.lead_ms * SR // 1000
    gap = args.gap_ms * SR // 1000
    tail = args.tail_pad_ms * SR // 1000
    episode = array.array("h", [0]) * lead
    cursor = lead
    timing_turns = []
    old = {}
    old_alignment = None
    save_pins(cache, pins, units)
    tpath = pc.safe_path(ep, ep / "timing.json", "timing.json")
    if tpath.is_file():
        try:
            old_doc = json.loads(tpath.read_text())
            old = {t["id"]: t for t in old_doc.get("turns", [])}
            old_alignment = old_doc.get("alignment")
        except Exception:
            old = {}
    for u in units:
        take = cache_file(cache, u["key"], ".wav").read_bytes()
        take_sha = pc.bytes_sha(take)
        pcm = decode_audio(take)
        if mode == "per-turn":
            pieces = [{"start": a, "end": b, "source": "clip"} for a, b in [speech_bounds(pcm)]]
            if pieces[0]["end"] <= pieces[0]["start"]:
                raise TtsError(f"turn {u['id']}: cached take is silent; rerun with --only {u['id']} --retake")
            span = (pieces[0]["start"], pieces[0]["end"])
        else:
            pieces = split_chunk(pcm, u)
            span = (pieces[0]["start"], pieces[-1]["end"])
        # Copy the take piece by piece so a hold after a turn inside a chunk becomes inserted
        # silence at that turn's end. The chunk's hash does not change.
        base = cursor - span[0]
        pos = span[0]
        for k, (t, p) in enumerate(zip(u["turns"], pieces)):
            last_in_unit = k == len(pieces) - 1
            stop = span[1] if last_in_unit else p["end"]
            episode.extend(pcm[pos:stop])
            pos = stop
            clip = pcm[p["start"]:p["end"]]
            rel = f"audio/turn-{t['id']}.wav"
            write_wav(pc.safe_path(ep, ep / rel, f"turn {t['id']} clip"), clip)
            start_ms = round((base + p["start"]) * 1000 / SR)
            end_ms = round((base + p["end"]) * 1000 / SR)
            th = u["hash"] if mode == "per-turn" else sha({"u": u["hash"], "t": t["id"]})
            # audioSha identifies the take, not the request: a --retake of unchanged text gets a new
            # audioSha, so words aligned to the old take are dropped instead of carried over.
            asha = take_sha if mode == "per-turn" else pc.bytes_sha(f"{take_sha}:{t['id']}".encode())
            entry = {"id": t["id"], "speaker": t["speaker"], "segment": t["segment"], "file": rel,
                     "startMs": start_ms, "endMs": end_ms, "timingSource": p["source"], "hash": th, "audioSha": asha}
            if mode == "chunk":
                entry["chunk"] = u["id"]
            prev = old.get(t["id"])
            if hold_ms(t):
                # The hold starts when the speech ends; the normal gap or tail pad follows it.
                entry["holdAfterMs"] = hold_ms(t)
                entry["holdStartMs"] = end_ms
                entry["holdEndMs"] = end_ms + hold_ms(t)
            if (prev and prev.get("audioSha") == asha and prev.get("alignedAudioSha") == asha
                    and prev.get("words") and prev.get("hash") == th):
                d = start_ms - prev["startMs"]
                shift = lambda ws: [{**w, "startMs": w["startMs"] + d, "endMs": w["endMs"] + d} for w in ws]
                entry["words"] = shift(prev["words"])
                if isinstance(prev.get("asr"), list):
                    entry["asr"] = shift(prev["asr"])
                if "matchRate" in prev:
                    entry["matchRate"] = prev["matchRate"]
                entry["alignedAudioSha"] = asha
            timing_turns.append(entry)
            if hold_ms(t) and not last_in_unit:
                episode.extend(array.array("h", [0]) * (hold_ms(t) * SR // 1000))
                base += hold_ms(t) * SR // 1000
        cursor = base + span[1]
        last_turn = u["turns"][-1]
        pad = (tail if last_turn["lastInSegment"] else gap) + hold_ms(last_turn) * SR // 1000
        episode.extend(array.array("h", [0]) * pad)
        cursor += pad

    raw_path = pc.safe_path(ep, audio / "episode.raw.wav", "episode.raw.wav")
    write_wav(raw_path, episode)
    out_path = pc.safe_path(ep, audio / "episode.wav", "episode.wav")
    loud = None
    if args.no_normalize:
        raw_path.replace(out_path)
    else:
        loud = loudnorm(raw_path, out_path, target=args.lufs, tp=args.true_peak)
        raw_path.unlink(missing_ok=True)
    duration_ms = round(len(episode) * 1000 / SR)
    timing = {"version": 1, "model": model, "mode": mode, "scratch": bool(args.scratch), "sampleRate": SR,
              "gapMs": args.gap_ms, "tailPadMs": args.tail_pad_ms, "leadMs": args.lead_ms,
              "durationMs": duration_ms, "turns": timing_turns}
    if mode == "chunk":
        timing["experimental"] = True
    if length_override:
        timing["lengthOverride"] = length_override
    if old_alignment and not args.scratch:
        # Carried words keep their engine. A turn without words (a new take) shows up as
        # 'missing' in fidelity.py, so the episode is a draft until align.mjs runs on it.
        al = dict(old_alignment)
        al["draft"] = bool(al.get("draft")) or any("words" not in t for t in timing_turns)
        timing["alignment"] = al
    try:  # C02: exclusive temporary file under the checked episode folder, then rename
        pc.atomic_write(tpath, json.dumps(timing, indent=2, ensure_ascii=False) + "\n", base=ep)
    except pc.BadId as e:
        raise TtsError(str(e)) from None

    # N08: name every turn whose audio changed in this run, so the realignment covers all of them.
    changed = [t["id"] for t in timing_turns if (old.get(t["id"]) or {}).get("audioSha") != t["audioSha"]]
    wall = time.monotonic() - run_t0
    report = {"created": dt.datetime.now().isoformat(timespec="seconds"), "model": model, "mode": mode,
              "synthesised": [u["id"] for u in jobs.values()], "sharedTakes": dupes and {h: ids for h, ids in dupes.items()},
              "reused": [u["id"] for u in reuse], "units": report_units,
              "billedInputTokens": billed_in, "billedOutputTokens": billed_out, "tokensMeasured": measured_all,
              "costUSD": round(run_cost, 5), "wallS": round(wall, 1), "durationMs": duration_ms, "loudness": loud}
    report["changedTurns"] = changed
    pc.safe_path(ep, audio / "tts-report.json", "tts-report.json").write_text(json.dumps(pc.redact_obj(report), indent=1) + "\n")

    sources = {}
    for t in timing_turns:
        sources[t["timingSource"]] = sources.get(t["timingSource"], 0) + 1
    log(f"wrote {out_path.relative_to(ep)} ({duration_ms / 1000:.2f} s) and timing.json "
        f"({len(timing_turns)} turns; timing sources {sources})")
    if loud:
        log(f"  loudness {loud['inputLUFS']:.1f} -> {loud['outputLUFS']:.1f} LUFS, true peak "
            f"{loud['outputTruePeakDb']:.1f} dBTP, sample peak {loud['peakDbfs']:.1f} dBFS ({loud['normalizationType']})")
    if changed and old:
        log(f"  audio changed for {len(changed)} turn(s): {', '.join(changed)}; realign exactly these: "
            f"node align.mjs {ep.name} --only {','.join(changed)}")
    if args.scratch:
        log("  scratch voices: timing draft only, never ship this audio")
    else:
        log(f"  billed {len(jobs)} calls, {billed_out} audio tokens, {billed_in} input tokens"
            f"{'' if measured_all else ' (partly estimated)'}: ${run_cost:.4f}; reused {len(reuse)} from cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
