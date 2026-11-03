#!/usr/bin/env python3
"""Pre-flight checks for podcast-explainer-video. Run before any paid call.

Usage:
  python3 scripts/preflight.py                         # workspace ./explainers
  python3 scripts/preflight.py --workspace ./explainers --json
  python3 scripts/preflight.py --scratch               # key and network become optional (macOS say draft)
  python3 scripts/preflight.py --offline               # skip the network call
  python3 scripts/preflight.py --warm-whisper          # also build whisper.cpp and download its model now

Checks: python, node >= 20, npx, ffmpeg, ffprobe, Gemini key presence, Gemini API reachable and
the TTS model listed, Remotion workspace installed, whisper.cpp built and its model downloaded
(the cache align.mjs uses), macOS `say` for --scratch. --warm-whisper runs `node align.mjs --warm`
from the workspace Remotion project, so the first align.mjs run never stalls on a build or a
download after the paid TTS step.

The key is read from env GEMINI_API_KEY, else from the single variable GEMINI_API_KEY in
~/.config/podcast-explainer/env, parsed here in code. The key value, prefix and length are never
printed, logged or written. Any error text is scrubbed of the key before it is shown.
Exit codes: 0 = every required check passed, 1 = at least one required check failed.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = pc.ENV_FILE
MODEL = "gemini-3.8-flash-tts"
FALLBACK_MODEL = "gemini-3.8-flash-lite-tts"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
NODE_MIN_MAJOR = 20          # Remotion 4 needs Node 18+; the skill's scripts use Node 20 APIs.
PY_MIN = (3, 10)             # match statements and `X | None` types in the scripts.
HTTP_TIMEOUT_S = 15          # the models list returns in under 1 s on a normal link
MAX_PAGES = 10               # models list pagination guard (about 50 models per page)
WHISPER_VERSION = "1.5.5"    # align.mjs defaults (--whisper-version, --model)
WHISPER_MODEL = "small.en"
WARM_TIMEOUT_S = 900         # build (about 30 s) plus a 466 MB model download on a slow link


def load_key() -> tuple[str | None, str, str | None]:
    """Returns (key, where, problem). `where` and `problem` are safe to print; the key is not.
    One parser for env and the env file (pe_common), shared with tts.py."""
    try:
        key, where = pc.load_api_key(ENV_FILE)
        return key, where, None
    except pc.KeyError_ as e:
        return None, "malformed", str(e)


def scrub(text: str, key: str | None = None) -> str:
    pc.register_secret(key)
    return pc.redact(text)


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


class Table:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, name: str, status: str, detail: str, fix: str = "", required: bool = True, note: str = ""):
        """`fix` is a shell command that runs as printed (or empty); explanation and alternatives go
        in `note`, printed on its own line after '#' (Q09: prose in a command is executed by the shell)."""
        self.rows.append({"check": name, "status": status, "detail": detail, "fix": fix, "required": required, "note": note})

    @property
    def failed(self) -> bool:
        return any(r["status"] == "FAIL" and r["required"] for r in self.rows)


def check_tools(t: Table):
    py = sys.version_info
    t.add("python", "PASS" if py[:2] >= PY_MIN else "FAIL", f"{py.major}.{py.minor}.{py.micro} at {sys.executable}",
          "" if py[:2] >= PY_MIN else "brew install python@3.13", note="" if py[:2] >= PY_MIN else "or: uv python install 3.13")

    code, out = run(["node", "--version"])
    m = re.match(r"v(\d+)", out or "")
    if code == 0 and m and int(m.group(1)) >= NODE_MIN_MAJOR:
        t.add("node", "PASS", out)
    else:
        t.add("node", "FAIL", out or "not found", "nvm install 24 && nvm use 24", note=f"need Node >= {NODE_MIN_MAJOR}")

    t.add("npx", "PASS" if shutil.which("npx") else "FAIL", shutil.which("npx") or "not found",
          "" if shutil.which("npx") else "nvm install 24", note="" if shutil.which("npx") else "npx ships with Node")

    for tool in ("ffmpeg", "ffprobe"):
        code, out = run([tool, "-version"])
        first = out.splitlines()[0] if out else "not found"
        ver = re.search(r"version (\S+)", first)
        t.add(tool, "PASS" if code == 0 else "FAIL", ver.group(1) if ver else first,
              "" if code == 0 else "brew install ffmpeg")

    say = shutil.which("say")
    t.add("say (scratch voice)", "PASS" if say else "WARN", say or "not found (macOS only)",
          required=False, note="" if say else "scratch mode needs macOS; use Gemini audio instead")


def check_gemini(t: Table, key: str | None, where: str, offline: bool, scratch: bool, problem: str | None = None):
    required = not scratch
    if key:
        t.add("gemini key", "PASS", f"present ({where})", required=required)
    elif problem:
        t.add("gemini key", "FAIL" if required else "WARN", "present but malformed", required=required, note=problem)
    else:
        t.add("gemini key", "FAIL" if required else "WARN", "missing", required=required,
              note="set GEMINI_API_KEY in your own shell (do not paste it into chat), or add GEMINI_API_KEY to ~/.config/podcast-explainer/env")
    if offline:
        t.add("gemini api", "WARN", "skipped (--offline)", required=False, note="rerun without --offline before TTS")
        return
    if not key:
        t.add("gemini api", "FAIL" if required else "WARN", "skipped: no key", required=required, note="fix the key first")
        return
    names: list[str] = []
    token = ""
    try:
        for _ in range(MAX_PAGES):
            url = f"{API_BASE}?pageSize=1000" + (f"&pageToken={token}" if token else "")
            req = urllib.request.Request(url, headers={"x-goog-api-key": pc.validate_key(key)})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                body = json.loads(r.read().decode())
            names += [m.get("name", "").removeprefix("models/") for m in body.get("models", [])]
            token = body.get("nextPageToken", "")
            if not token:
                break
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            err = json.loads(raw).get("error", {})
            reasons = [d.get("reason") for d in err.get("details", []) if isinstance(d, dict) and d.get("reason")]
            detail = scrub(f"{err.get('message', '')} {' '.join(reasons)}".strip(), key)
        except (json.JSONDecodeError, AttributeError):
            detail = scrub(raw[:300], key)
        if "API_KEY_INVALID" in detail:
            e.code = 401  # Google returns 400 for an invalid key; give the invalid-key fix
        fix = {400: "the key is malformed or unrestricted keys are rejected: restrict it to the Gemini API in AI Studio",
               401: "the key is invalid: make a new one at https://aistudio.google.com/apikey",
               403: "the key lacks Gemini API access or is restricted elsewhere: check API restrictions in AI Studio",
               429: "rate limited: wait one minute and rerun"}.get(e.code, "check https://aistudio.google.com/apikey")
        detail = re.sub(r"\s+", " ", detail)
        t.add("gemini api", "FAIL" if required else "WARN", f"HTTP {e.code}: {detail}", required=required, note=fix)
        return
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        t.add("gemini api", "FAIL" if required else "WARN", scrub(f"unreachable: {e}", key),
              "curl -sI https://generativelanguage.googleapis.com", required=required, note="check the network")
        return
    except (ValueError, pc.KeyError_) as e:  # e.g. a header the HTTP library refuses
        t.add("gemini api", "FAIL" if required else "WARN", scrub(f"request not sent: {type(e).__name__}: {e}", key),
              required=required, note="re-export GEMINI_API_KEY as one line with no spaces or quotes")
        return
    tts = sorted(n for n in names if "tts" in n)
    t.add("gemini api", "PASS", f"reachable, {len(names)} models listed", required=required)
    if MODEL in names:
        t.add(f"model {MODEL}", "PASS", "listed", required=required)
    else:
        alt = FALLBACK_MODEL if FALLBACK_MODEL in names else None
        t.add(f"model {MODEL}", "FAIL" if required else "WARN", f"not listed; TTS models seen: {', '.join(tts) or 'none'}",
              required=required, note=f"use --model {alt} in tts.py" if alt else "check https://ai.google.dev/gemini-api/docs/models")
    t.add(f"model {FALLBACK_MODEL}", "PASS" if FALLBACK_MODEL in names else "WARN",
          "listed" if FALLBACK_MODEL in names else "not listed (fallback unavailable)", required=False)


def check_workspace(t: Table, ws: Path):
    # R06: every printed path is absolute and shell-quoted, so the fix runs as printed from any
    # folder, also when a path has spaces ("/tmp/My Lessons/explainers").
    ws = ws.resolve()
    rem = ws / "remotion"
    pkg = rem / "node_modules" / "remotion" / "package.json"
    template = shlex.quote((SKILL_DIR / "templates" / "remotion").resolve().as_posix())
    q_ws, q_rem = shlex.quote(ws.as_posix()), shlex.quote(rem.as_posix())
    if pkg.is_file():
        try:
            ver = json.loads(pkg.read_text()).get("version", "?")
        except (OSError, json.JSONDecodeError):
            ver = "?"
        t.add("remotion workspace", "PASS", f"{rem.as_posix()} (remotion {ver})")
    elif (rem / "package.json").is_file():
        t.add("remotion workspace", "FAIL", f"{rem.as_posix()} copied but not installed", f"(cd {q_rem} && npm install)")
    else:
        t.add("remotion workspace", "FAIL", f"{rem.as_posix()} missing",
              f"mkdir -p {q_ws} && cp -R {template} {q_rem} && (cd {q_rem} && npm install)")
    if pkg.is_file():  # W16 (W14b D01): npm may skip esbuild's postinstall; render needs its platform binary
        plat = {"darwin": "darwin", "linux": "linux", "windows": "win32"}.get(platform.system().lower(), platform.system().lower())
        arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
        binary = rem / "node_modules" / "@esbuild" / f"{plat}-{arch}" / "bin" / "esbuild"
        ok = binary.is_file() or (rem / "node_modules" / "@esbuild" / f"{plat}-{arch}" / "esbuild.exe").is_file()
        t.add("esbuild binary", "PASS" if ok else "FAIL",
              f"@esbuild/{plat}-{arch} present" if ok else f"@esbuild/{plat}-{arch} missing: the bundler cannot start (a skipped postinstall does not matter when this is present)",
              "" if ok else f"(cd {q_rem} && npm rebuild esbuild)")
    # Optional: the built-in schema subset validator runs without jsonschema; jsonschema checks every keyword.
    try:
        import jsonschema  # noqa: F401
        t.add("jsonschema (optional)", "PASS", "importable: validators use full JSON Schema", required=False)
    except ImportError:
        t.add("jsonschema (optional)", "WARN", "not importable: validators use the built-in subset (validate_script.py skips anyOf, oneOf and format)",
              f"{shlex.quote(sys.executable)} -m pip install --user jsonschema", required=False)
    whisper = rem / "node_modules" / "@remotion" / "install-whisper-cpp" / "package.json"
    # Required: align.mjs stops without it, and estimated timing (--estimate-only) is a draft that
    # qc.py refuses to deliver.
    t.add("@remotion/install-whisper-cpp", "PASS" if whisper.is_file() else "FAIL",
          "installed" if whisper.is_file() else "not installed: align.mjs cannot measure word times (only --estimate-only drafts)",
          "" if whisper.is_file() else f"(cd {q_rem} && npm install)")


def whisper_cache() -> Path:
    """The folder align.mjs installs whisper.cpp into (same rule: PODCAST_EXPLAINER_CACHE, else ~/.cache)."""
    import os
    base = os.environ.get("PODCAST_EXPLAINER_CACHE") or str(Path.home() / ".cache" / "podcast-explainer")
    return Path(base).expanduser().resolve() / f"whisper.cpp-{WHISPER_VERSION}"


def check_whisper(t: Table, ws: Path, warm: bool, cache_dir: Path | None = None):
    """whisper.cpp binary and model in align.mjs's cache. Missing is a WARN (align.mjs builds it on
    first use), unless --warm-whisper was asked for and failed (FAIL)."""
    ws = ws.resolve()
    rem = ws / "remotion"
    wp = (cache_dir.expanduser().resolve() / f"whisper.cpp-{WHISPER_VERSION}") if cache_dir else whisper_cache()
    align = (SKILL_DIR / "scripts" / "align.mjs").resolve()
    extra = f" --cache-dir {shlex.quote(cache_dir.expanduser().resolve().as_posix())}" if cache_dir else ""
    fix = f"cd {shlex.quote(rem.as_posix())} && node {shlex.quote(align.as_posix())} --warm --workspace ..{extra}"
    # Q09 (codex round 4): the alternative is a note, printed after '#', never part of the command.
    alt = (f"or: python3 {shlex.quote((SKILL_DIR / 'scripts' / 'preflight.py').resolve().as_posix())} --warm-whisper "
           f"--workspace {shlex.quote(ws.as_posix())}")
    if warm:
        if not (rem / "node_modules" / "@remotion" / "install-whisper-cpp" / "package.json").is_file():
            t.add("whisper ready", "FAIL", "cannot warm: @remotion/install-whisper-cpp is not installed",
                  f"(cd {shlex.quote(rem.as_posix())} && npm install)")
            return
        cmd = ["node", align.as_posix(), "--warm", "--workspace", ws.as_posix()]
        if cache_dir:
            cmd += ["--cache-dir", cache_dir.expanduser().resolve().as_posix()]
        try:
            p = subprocess.run(cmd, cwd=rem, capture_output=True, text=True, timeout=WARM_TIMEOUT_S)
            out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
            code = p.returncode
        except subprocess.TimeoutExpired:
            out, code = [f"timed out after {WARM_TIMEOUT_S} s"], 1
        except OSError as e:
            out, code = [str(e)], 1
        last = out[-1] if out else ""
        t.add("whisper ready", "PASS" if code == 0 else "FAIL", last[:200], "" if code == 0 else fix)
        return
    exe, model = wp / "main", wp / f"ggml-{WHISPER_MODEL}.bin"
    missing = [n for n, f in (("whisper.cpp build", exe), (f"model {WHISPER_MODEL}", model)) if not f.is_file()]
    if missing:
        t.add("whisper ready", "WARN", f"not ready in {wp.as_posix()}: missing {', '.join(missing)}; "
              "the first align.mjs run would build or download it after TTS money is spent", fix, required=False, note=alt)
    else:
        t.add("whisper ready", "PASS", f"whisper.cpp {WHISPER_VERSION} and {WHISPER_MODEL} in {wp.as_posix()}", required=False)


def print_table(t: Table):
    w1 = max(len(r["check"]) for r in t.rows)
    w3 = min(70, max(len(r["detail"]) for r in t.rows))
    print(f"{'check':<{w1}}  status  {'detail':<{w3}}")
    print(f"{'-' * w1}  ------  {'-' * w3}")
    for r in t.rows:
        status = r["status"] if r["required"] or r["status"] == "PASS" else r["status"] + "*"
        print(f"{r['check']:<{w1}}  {status:<6}  {r['detail']}")
    fixes = [r for r in t.rows if (r["fix"] or r.get("note")) and r["status"] != "PASS"]
    if fixes:
        print("\nFixes (each command line runs as printed; '#' lines are notes):")
        for i, r in enumerate(fixes, 1):
            print(f"{i}. {r['check']}:")
            if r["fix"]:
                print(f"   {r['fix']}")
            if r.get("note"):
                print(f"   # {r['note']}")
    print("\n* optional check")
    print("PREFLIGHT: " + ("FAIL" if t.failed else "PASS"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pre-flight checks for podcast-explainer-video. Never prints the key.")
    ap.add_argument("--workspace", type=Path, default=Path("explainers"), help="workspace folder (default ./explainers)")
    ap.add_argument("--scratch", action="store_true", help="scratch-voice run: key and network are optional")
    ap.add_argument("--offline", action="store_true", help="skip the Gemini network check")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    ap.add_argument("--warm-whisper", action="store_true",
                    help="build whisper.cpp and download its model now (node align.mjs --warm); run before paid TTS")
    ap.add_argument("--whisper-cache-dir", type=Path, default=None,
                    help="whisper cache folder (default $PODCAST_EXPLAINER_CACHE or ~/.cache/podcast-explainer), as align.mjs --cache-dir")
    args = ap.parse_args(argv)

    t = Table()
    check_tools(t)
    key, where, problem = load_key()
    check_gemini(t, key, where, args.offline, args.scratch, problem)
    check_workspace(t, args.workspace.expanduser())
    check_whisper(t, args.workspace.expanduser(), args.warm_whisper, args.whisper_cache_dir)
    del key
    t.rows = pc.redact_obj(t.rows)
    if args.json:
        print(json.dumps({"ok": not t.failed, "checks": t.rows}, indent=2))
    else:
        print_table(t)
    return 1 if t.failed else 0


if __name__ == "__main__":
    sys.exit(main())
