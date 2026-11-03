#!/usr/bin/env python3
"""Assemble qc/scores.json from the two stored reviewer replies.

usage: write_scores.py --workspace explainers --slug <slug>

Reads qc/replies/judge.md and qc/replies/restate.md (stored by `qc.py save-reply`), takes the last
```json block of each, and writes qc/scores.json: the judge's fields, the judge's reply as stored with its
sha256, and `restate` with the restater's fields and its reply as stored with its sha256.
It never edits a reply. It cannot prove the replies are byte for byte what the models produced.
"""
import argparse, hashlib, json, re, sys
from pathlib import Path


def last_json(text, name):
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not blocks:
        sys.exit(f"write_scores: no ```json block in the {name} reply; ask the agent for its JSON block")
    try:
        return json.loads(blocks[-1])
    except json.JSONDecodeError as e:
        sys.exit(f"write_scores: the last ```json block of the {name} reply is not valid JSON: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="explainers")
    ap.add_argument("--slug", required=True)
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", a.slug):
        sys.exit("write_scores: slug must be lowercase letters, digits and hyphens")
    qc = (Path(a.workspace) / a.slug / "qc").resolve()
    jp, rp = qc / "replies" / "judge.md", qc / "replies" / "restate.md"
    for p in (jp, rp):
        if not p.is_file():
            sys.exit(f"write_scores: missing {p}; run qc.py save-reply --kind judge|restate first")
    jt, rt = jp.read_text(encoding="utf-8"), rp.read_text(encoding="utf-8")
    sha = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()
    out = dict(last_json(jt, "judge"))
    out["judgeReply"], out["judgeReplySha256"] = jt, sha(jt)
    r = dict(last_json(rt, "restate"))
    r["reply"], r["replySha256"] = rt, sha(rt)
    out["restate"] = r
    (qc / "scores.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {qc / 'scores.json'} (build {out.get('build')}, round {out.get('round')})")


if __name__ == "__main__":
    main()
