# Contributing

Thanks for helping. podcast-explainer is one Claude Code plugin with one skill, `podcast-explainer-video`,
a set of standard-library Python scripts, one Node script and a Remotion template.

[DEVELOPING.md](DEVELOPING.md) has the steps: set up, try a change in one session with `--plugin-dir`, ship it
through a pull request, and update your install. This file has the rules.

## Set up

```sh
git clone https://github.com/Shavvimal/podcast-explainer.git && cd podcast-explainer
make check            # hygiene scan, ruff, unit tests, plugin validation
```

You need Python 3.10 or newer (CI runs 3.10 to 3.13), Node 20 or newer, `uv` (for `uvx ruff`) and
[Claude Code](https://code.claude.com/) for `claude plugin validate`. `ffmpeg` is needed by a handful of
tests that assemble a tiny episode; without it those tests skip.

The renderer tests need a Remotion project with `node_modules`. Install the template once outside the
repository and point the tests at it:

```sh
cp -R skills/podcast-explainer-video/templates/remotion /tmp/pe-remotion && (cd /tmp/pe-remotion && npm install)
PE_REMOTION_DIR=/tmp/pe-remotion make test
```

Without `PE_REMOTION_DIR` the renderer tests skip and say so. `make typecheck` type-checks the template with
the same `node_modules` (`PE_REMOTION_DIR` again).

## Where things live

| Change | Where | Read first |
|---|---|---|
| A pedagogy rule, a persona line, a prompt | `references/script.md`, `references/learning-design.md` | the evidence tags in learning-design.md |
| A validator check (E or W code) | `scripts/validate_script.py` | `references/script.md` section 10 (the code table) |
| A QC check or the judge rubric | `scripts/qc.py`, `references/qc.md` | `references/learning-design.md` section on J1 to J11 |
| TTS, holds, loudness, retries | `scripts/tts.py`, `references/gemini-tts.md` | the limits table in gemini-tts.md |
| Word timing | `scripts/align.mjs`, `scripts/fidelity.py` | `references/manifest.md` |
| A scene type or the concept world | `templates/remotion/src/scenes/`, `references/visuals.md`, `schemas/scenes.schema.json` | visuals.md |
| Transcript, captions, library, `learn/` | `scripts/transcript.py`, `scripts/learn.py`, `scripts/search.py`, `references/library.md` | library.md |
| Shared helpers (key loading, redaction, ids, visible text, digests) | `scripts/pe_common.py` | its module docstring |
| Skill text | `SKILL.md` | the file map table at its end |

All paths above are under `skills/podcast-explainer-video/`. The renderer and `pe_common.visible_text` must
agree on what is on screen at a given time; `tests/test_renderer_*.py` check that parity, so a change to one
side needs the other.

## Rules the code keeps

- **The key never shows.** Anything that can carry the Gemini key goes through `pe_common.redact`. No
  script prints, logs or writes the key, its prefix or its length. A test fails if a new log line leaks it.
- **Fail loudly.** A failed TTS turn stops the run with the turn id. No silence, no skipped turn, no guessed
  duration ships. A script that exits non-zero stops the workflow.
- **Measured audio is the clock.** No typed duration, frame count or millisecond anywhere outside
  `timing.json`.
- **Every number sourced.** The validator's E08 stays. Do not weaken it to make a sample pass.
- **One source of truth per constant.** Loudness targets live in `pe_common.py`; the docs quote them and a
  test checks that they agree. Follow the pattern for any new constant.
- **Standard library only** in the Python scripts, so the skill runs anywhere Python 3.10 is. Node code
  stays inside `align.mjs` and the Remotion template.

## Pull requests

- One topic per PR, squash-merged. Add or change a test for every behaviour change.
- Raise `version` in `.claude-plugin/plugin.json` when anything under `skills/` or `.claude-plugin/`
  changes (CI's `version-bump` check requires it), and add a section to `CHANGELOG.md` for that version.
  Docs, tests and CI do not need a bump.
- Run `make check` locally with the private-terms file in place (below) before every push.
- Say which Gemini model and which Remotion version you tested against if you changed TTS or rendering, and
  attach `qc/report.md` from a real episode when a change affects the picture or the sound.

## Public-repository hygiene

Everything here is published the moment it is pushed. Never write a personal name, an employer or client
name, an absolute home directory path (`/Users/<name>/...`, `/home/<name>/...`), a personal email, an API
key or a private project name into a tracked file, a commit message or a PR.

`scripts/check_hygiene.py` scans every tracked file for those shapes in CI. Locally it also reads the
untracked file `$XDG_CONFIG_HOME/podcast-explainer/private-terms` (default
`~/.config/podcast-explainer/private-terms`), one term per line, matched as a whole word without case, and
reports a hit by line number only, so the log never publishes the term. Put the names that must never
appear in that file, never in a tracked one. CI has no such file, so the local run is the one that checks
names.

Sample data must be made for this repository. A sample episode, script or transcript names no real person;
the hosts are Nia and Theo and the sample learner is Priya.

## Reporting a bug

Open an issue with the step that failed (the 15-step checklist number), the command, its full output with
the key redacted (the scripts redact it for you), your Python and Node versions, and the Gemini model and
Remotion version from `preflight.py`. For a security problem, use the private advisory form in
[SECURITY.md](SECURITY.md) instead.

By contributing, you agree that your contribution is licensed under the MIT licence in [LICENSE](LICENSE)
and that you follow the [Code of Conduct](CODE_OF_CONDUCT.md).
