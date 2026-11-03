#!/usr/bin/env python3
"""fidelity.py: does the audio say what the script says? Raw ASR vs script, both directions.

Usage:
  python3 fidelity.py --workspace explainers --slug <slug> [--json]

Reads <slug>/script.json, <slug>/timing.json (turns[].asr from align.mjs) and the optional
<slug>/fidelity-accept.json. Writes <slug>/qc/fidelity.json and prints every turn that is not ok.

Per turn it counts substitutions, deletions (script words nobody said) and insertions (spoken
words that are not in the script), and flags any number or negation that differs as critical.
Status: ok, warn (small non-critical differences, such as an ASR spelling), fail (a number, a
sign or a negation differs, a direction word is swapped (increase/decrease, true/false,
more/less, before/after), dropped or added, two words differ by a negating prefix (valid/invalid,
authenticated/unauthenticated), or 3 or more differences and a word error rate over 20%), stale
(words aligned to an older take), missing (no raw ASR: estimated alignment, a draft).

Names: brief.json `lexicon` ({"Priya": ["pria", "prayer"]}) lists what ASR writes for a name or
term; a heard alias counts as the term, so a misheard name is not a warning. An alias can never
stand for a number, sign, negation or direction word (validate_script.py E40).

Delivery mode: scratch, chunk, experimental, draft or estimated timing is never deliverable; the
report says DRAFT and lists why (pe_common.production_problems).

A fail is resolved by a new take (tts.py --only <id> --retake, then align.mjs --only <id>), or,
after a person listened and the audio is right (an ASR mishearing), by an entry in
<slug>/fidelity-accept.json: {"accept": [{"turn": "t07", "audioSha": "<from this report>",
"text": "<the expected text this report prints>", "reason": "listened: says 'mod 4'; ASR wrote
'mod for'"}]}. The entry binds to the take (audioSha) AND to the canonical expected text, and
needs a reason: a new take or a changed turn needs a new listen. For every fail this script
prints the entry to paste, with the reason left for you to write.

Headless runs (no person can listen): retake a failing turn once (--retake); if it fails again,
rewrite the turn so ASR can hear it plainly, revalidate and retake it. Never write an accept
entry without a listen. Name-only warnings (a capitalised name heard as another spelling) print
a ready brief.json `lexicon` suggestion (W16, W14b D22); they do not lower the audio score.

Exit codes: 0 = no blocking problem (a draft prints DRAFT and still exits 0), 1 = a fail or a
stale turn (delivery is blocked), 2 = bad command line or missing files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_common as pc  # noqa: E402


def compute(ep: Path) -> dict:
    script = json.loads((ep / "script.json").read_text(encoding="utf-8"))
    timing = json.loads((ep / "timing.json").read_text(encoding="utf-8"))
    return pc.episode_fidelity(script, timing, pc.load_accept(ep), pc.load_lexicon(ep))  # brief.json lexicon: name aliases


def name_suggestions(script: dict, rep: dict) -> dict[str, list[str]]:
    """{Name: [heard spellings]} for substitutions whose script word is a capitalised name
    (mid-sentence in the script, or a speaker name). A ready brief.json `lexicon` suggestion;
    aliases E40 refuses (numbers, negations, direction words) are left out."""
    names: dict[str, str] = {}
    for sp in script.get("speakers") or []:
        if isinstance(sp, dict) and sp.get("name"):
            names[str(sp["name"]).lower()] = str(sp["name"])
    for seg in script.get("segments") or []:
        for t in seg.get("turns") or []:
            for m in pc.re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]+)\b", t.get("text") or ""):
                names.setdefault(m.group(1).lower(), m.group(1))
    out: dict[str, list[str]] = {}
    for t in rep.get("turns") or []:
        for d in t.get("diff") or []:
            s, h = d.get("script"), d.get("heard")
            if d.get("op") == "sub" and s in names and h and not pc.lexicon_problems({names[s]: [h]}):
                lst = out.setdefault(names[s], [])
                if h not in lst:
                    lst.append(h)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare raw ASR (timing.json turns[].asr) with script.json, both directions.")
    ap.add_argument("--workspace", default="explainers")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        ep = pc.episode_dir(args.workspace, args.slug)
        for name in ("script.json", "timing.json"):
            if not (ep / name).is_file():
                print(f"fidelity.py: error: missing {ep / name}", file=sys.stderr)
                return 2
        rep = compute(ep)
    except (pc.BadId, ValueError, json.JSONDecodeError) as e:
        print(f"fidelity.py: error: {e}", file=sys.stderr)
        return 2
    (ep / "qc").mkdir(exist_ok=True)
    (ep / "qc" / "fidelity.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    else:
        c = rep["counts"]
        print(f"fidelity: {len(rep['turns'])} turns: {c['ok']} ok, {c['warn']} warn, {c['fail']} fail, "
              f"{c['accepted']} accepted, {c['stale']} stale, {c['missing']} without raw ASR (engine {rep['engine']})")
        for t in rep["turns"]:
            if t["status"] in ("ok",):
                continue
            if t["status"] in ("missing", "stale"):
                print(f"  {t['status'].upper():<8} {t['turn']}: {t['detail']}")
                continue
            d = "; ".join(f"{x['op']} {x['script'] or ''}->{x['heard'] or ''}" for x in t["diff"][:6])
            crit = f" CRITICAL: {', '.join(t['critical'])}." if t.get("critical") else ""
            print(f"  {t['status'].upper():<8} {t['turn']}: S{t['substitutions']} D{t['deletions']} I{t['insertions']} "
                  f"WER {t['wer']:.0%}.{crit} {d} (audioSha {t['audioSha']})")
            for why in t.get("acceptProblems") or []:
                print(f"           fidelity-accept.json entry not used: {why}")
            if t["status"] == "fail":
                entry = {"turn": t["turn"], "audioSha": t["audioSha"], "text": t.get("expected", ""), "reason": "listened: <what you heard>"}
                print(f"           after a listen, if the audio is right: {json.dumps(entry, ensure_ascii=False)}")
        sug = name_suggestions(json.loads((ep / "script.json").read_text(encoding="utf-8")), rep)
        if sug:
            print(f"  name-only warns: add to brief.json lexicon: {json.dumps(sug, ensure_ascii=False)}")
        if rep["blocking"]:
            print("  headless (nobody can listen): retake once with --retake; if it fails again, rewrite the turn plainly and retake")
            print(f"FIDELITY: FAIL ({rep['blocking']} blocking turn(s)). Retake the turn (tts.py --only <id> --retake, then "
                  f"align.mjs --only <id>), or listen and add it to {ep / 'fidelity-accept.json'} with its audioSha.")
        elif rep["draft"]:
            why = "; ".join(rep.get("rejected") or []) or "estimated or missing alignment"
            print(f"FIDELITY: DRAFT, not deliverable ({why}). Make per-turn Gemini takes (tts.py without --scratch or "
                  f"--mode chunk) and run align.mjs with whisper.cpp before delivery.")
        else:
            print("FIDELITY: PASS")
    return 1 if rep["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
