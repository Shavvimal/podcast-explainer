# Developing

How to work on podcast-explainer, try a change, ship it, and update your own install.
`CONTRIBUTING.md` has the rules; this file has the steps.

## The two ways the plugin runs

| | Marketplace install | Working copy |
| --- | --- | --- |
| How | `/plugin marketplace add Shavvimal/podcast-explainer` then `/plugin install podcast-explainer@podcast-explainer` | `claude --plugin-dir /path/to/podcast-explainer` |
| Runs | The copy made from GitHub `main` when it was installed or last updated | The folder on disk, uncommitted edits included |
| Lasts | Every session (user scope) | That one session only |
| Picks up a change | After `/plugin marketplace update podcast-explainer` and a new session | After `/reload-plugins` |

Keep the marketplace install for daily use: it is what other people run. Use the working copy only
to try a change. Do not also symlink the skill folder into `~/.claude/skills/`: two copies of a skill
with the same name load twice and the agent cannot tell which one it followed.

## Set up

```bash
git clone https://github.com/Shavvimal/podcast-explainer.git
cd podcast-explainer
make check
```

You need Python 3.10 or newer, Node 20 or newer, `uv` (for `uvx ruff`), `ffmpeg`, and Claude Code for
`claude plugin validate`.

The Gemini key: export `GEMINI_API_KEY` in your shell, or write the line `GEMINI_API_KEY=...` to
`~/.config/podcast-explainer/env` (mode 600). To point at a dotenv file you already keep, set
`PODCAST_EXPLAINER_ENV_FILE=/path/to/that/file`; only the `GEMINI_API_KEY` line is read. Never put the
key in the repository, in a sample, or in a chat message. `preflight.py` says only "present" or
"missing".

The renderer tests and the type check need an installed Remotion project. Install the template once,
outside the repository, and name it in `PE_REMOTION_DIR`:

```bash
cp -R skills/podcast-explainer-video/templates/remotion ~/.cache/pe-remotion
(cd ~/.cache/pe-remotion && npm install)
export PE_REMOTION_DIR=~/.cache/pe-remotion
make test typecheck
```

## Try a change in one session

The marketplace copy and your working copy are both named `podcast-explainer`. Turn the installed one
off first, so only your working copy answers:

```bash
claude plugin disable podcast-explainer@podcast-explainer
claude --plugin-dir /path/to/podcast-explainer
```

In that session, ask for a short episode (`quick` depth, `--scratch` voice) and watch each gate. Edits
to `SKILL.md`, `references/` and `scripts/` are live after `/reload-plugins`; a change to
`templates/remotion/` reaches a workspace only when you copy the changed file into
`explainers/remotion/` there, because the template is copied once per workspace.

When you are done, turn the installed copy back on:

```bash
claude plugin enable podcast-explainer@podcast-explainer
```

## Check before you push

```bash
make check
```

| Step | What it runs |
| --- | --- |
| `hygiene` | `scripts/check_hygiene.py`: no home paths, personal emails, key shapes, private addresses or private names in tracked files |
| `lint` | `uvx ruff check` on the scripts and tests, with the rule set in `pyproject.toml` |
| `test` | `python3 -m unittest discover -s tests`: 384 tests, standard library only; renderer tests when `PE_REMOTION_DIR` is set |
| `validate` | `node --check` on `align.mjs`, and `claude plugin validate . --profile directory` |
| `typecheck` | `tsc --noEmit` on a copy of the template linked to `$PE_REMOTION_DIR/node_modules` (not part of `check`; CI runs it) |

A pedagogy or QC change also needs one real episode: run the workflow end to end on a `quick` concept
and read `qc/report.md`. Put the judge scores and the restater's result in the pull request.

## Ship a change

`main` is protected. Every change lands through a pull request, squash-merged, with the `check (3.13)`,
`template` and `version-bump` checks green.

1. Branch: `git switch -c <short-name>`.
2. Make the change, and run `make check`.
3. If you changed anything under `skills/` or `.claude-plugin/`, raise `version` in
   `.claude-plugin/plugin.json` (semver) and add a `## <version> - <date>` section at the top of
   `CHANGELOG.md`. Docs, tests and CI changes need no bump.
4. Push and open a pull request:

   ```bash
   git push -u origin <short-name>
   gh pr create --fill
   ```

5. Wait for the checks (`gh pr checks --watch`), then squash-merge:

   ```bash
   gh pr merge --squash
   ```

   GitHub deletes the branch. Then sync: `git switch main && git pull`.

On the merge, the `release` workflow reads the version. If no release has that tag yet, it tags
`v<version>` and publishes the CHANGELOG section as the release notes. A merge without a version change
publishes nothing.

## Update your install

After a release:

```
/plugin marketplace update podcast-explainer
```

Then start a new session. A workspace's `explainers/remotion/` keeps the template it was copied from, so
after a release that changed `templates/remotion/`, copy the changed files from the plugin's template
into `explainers/remotion/` (keep its `node_modules`) and rerun `npm install` there if `package.json`
changed. The CHANGELOG section says when a release touched the template.

## GitHub settings

`scripts/github-setup.sh` applies the repository description, topics, squash-only merges, labels and the
ruleset on `main`. It is idempotent. Rulesets need a public repository or GitHub Pro; on a private
free-plan repository the script skips that step and says so.
