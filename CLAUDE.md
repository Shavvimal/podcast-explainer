# podcast-explainer: repository rules

This repository is public. Every file, commit message, PR title and PR body is published the moment it is
pushed, and a force push does not take it back.

## What this is

A Claude Code plugin with one skill, `skills/podcast-explainer-video/`. `SKILL.md` is the entry point and
the workflow; `references/` hold the rules per topic; `scripts/` do the work (Python standard library plus
one Node script); `schemas/` define every file the workflow writes; `templates/remotion/` is the video
project copied into a user's workspace. `.claude-plugin/plugin.json` is the manifest and
`.claude-plugin/marketplace.json` makes the repository installable. `tests/` at the root holds the unit
tests.

## Local-only material

`private/` is gitignored and exists only on the maintainer's machine: the research playbooks and cloned
reference repositories, the review rounds, the example builds and their transcript library, the source
list, and the original unsanitised skill. Read it for background and prior decisions. Nothing moves
from `private/` into a tracked path without `make hygiene` passing afterwards. `scratchpad/` is also
gitignored, for throwaway work.

## Public-repo hygiene

- Never write a personal name, a client or employer name, an absolute home directory path
  (`/Users/<name>/...`, `/home/<name>/...`), a personal email, an API key or a private project name into a
  tracked file, a commit message or a PR.
- `scripts/check_hygiene.py` scans every tracked file for those shapes in CI, and for the terms in the
  untracked file `$XDG_CONFIG_HOME/podcast-explainer/private-terms` locally. Add a private name there,
  never to a tracked file.
- Sample data is invented for this repository: hosts Nia and Theo, sample learner Priya, example paths
  under `/path/to/project/`.
- The Gemini key is never written anywhere. Code reads it through `pe_common.load_api_key` and redacts it
  through `pe_common.redact`. Do not add a second loader or a print of the key.

## Rules the code keeps

Fail loudly, measured audio is the clock, every number sourced, one source of truth per constant, standard
library only in Python. `CONTRIBUTING.md` spells each one out. A change to the renderer's visibility rules
needs the same change in `pe_common.visible_text`, and the parity tests check it.

## Developing

`DEVELOPING.md` has the workflow: the marketplace install for daily use, `--plugin-dir` for one-session
tests with the installed copy disabled, the pull request and release flow, and updating an install. Keep it
accurate when a step changes. Never recommend a symlink into `~/.claude/skills/`: it loads the skill twice.

## Gate

`make check` runs the hygiene scan, `ruff`, the unit tests and `claude plugin validate`. CI runs the same on
every pull request, plus a type check of the Remotion template on Node 22.

- `main` is protected: changes land through a pull request, squash-merged, with the `check`, `template`
  and `version-bump` checks green.
- A change under `skills/` or `.claude-plugin/` raises `version` in `.claude-plugin/plugin.json` and adds a
  `CHANGELOG.md` section; the release workflow then tags and publishes it.
- Commits carry no attribution trailer.
