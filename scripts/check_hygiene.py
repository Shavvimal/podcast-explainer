#!/usr/bin/env python3
"""Public-repository hygiene scan. Standard library only.

This repository is public: no tracked file may name a person's machine, a personal email address, an API
key or a private project. The generic shapes are below. The names that must never appear are not listed
here, because listing them would publish them: they live in the untracked file
$XDG_CONFIG_HOME/podcast-explainer/private-terms (default ~/.config/podcast-explainer/private-terms),
one per line, matched as a whole word without case. CI checks the generic shapes; `make check` also
checks the private terms before a push, and reports a hit by line number only.

Exit 0 when every tracked file is clean, 1 otherwise, 2 when git is not available.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".wav", ".mp3", ".mp4", ".pdf"}
# A placeholder user (`/Users/x/`, `/home/alice/`) is documentation, not a person.
PLACEHOLDER_USERS = ("x", "alice", "bob", "me", "you", "user", "name", "example", "<name>", "<user>", "you")

PATTERNS: dict[str, re.Pattern[str]] = {
    "a home directory path": re.compile(
        r"(?<![\w/])/(?:Users|home)/(?!(?:" + "|".join(re.escape(u) for u in PLACEHOLDER_USERS) + r")/)[A-Za-z0-9_.<>-]+/"
    ),
    "a personal email address": re.compile(r"[\w.+-]+@(?:gmail|googlemail|outlook|hotmail|icloud|proton|protonmail|yahoo)\.", re.I),
    "a Google API key": re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
    "an Anthropic or OpenAI key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}\b"),
    "a private IPv4 address": re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    "a Claude Code scratch path": re.compile(r"/private/tmp/claude-\d+/"),
}
# Test data is allowed to carry a fake key that is shaped like a real one, when it says so.
FAKE_KEY_MARKERS = ("DUMMY", "dummy", "fake", "FAKE", "example", "EXAMPLE")


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"check_hygiene: cannot list files: {e}", file=sys.stderr)
        sys.exit(2)
    files = []
    for name in out.split("\0"):
        if not name:
            continue
        p = Path(name)
        if p.suffix.lower() in BINARY or not p.is_file():
            continue
        files.append(p)
    return files


def private_terms() -> list[re.Pattern[str]]:
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip() or str(Path.home() / ".config")
    path = Path(config_home).expanduser() / "podcast-explainer" / "private-terms"
    if not path.is_file():
        return []
    terms = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if term and not term.startswith("#"):
            terms.append(re.compile(r"\b" + re.escape(term) + r"\b", re.I))
    return terms


def main() -> int:
    files = tracked_files()
    terms = private_terms()
    hits: list[str] = []
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(lines, 1):
            for label, rx in PATTERNS.items():
                if rx.search(line):
                    if label.endswith("key") and any(m in line for m in FAKE_KEY_MARKERS):
                        continue
                    hits.append(f"{f}:{i}: {label}")
            for n, rx in enumerate(terms, 1):
                # A private term's hit is reported by its line number in the terms file, so the log never publishes it.
                if rx.search(line):
                    hits.append(f"{f}:{i}: private term {n}")
    if hits:
        print(f"Public hygiene: {len(hits)} problem(s)", file=sys.stderr)
        print("\n".join(hits), file=sys.stderr)
        return 1
    checked = "generic shapes and private terms" if terms else "generic shapes"
    print(f"Public hygiene: {len(files)} files clean ({checked}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
