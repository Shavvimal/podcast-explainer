#!/usr/bin/env bash
# One-time GitHub setup for this repository: description, topics, merge settings and the branch
# ruleset on main. Idempotent: run it again after changing a value. Needs `gh` logged in as the owner.
#
#   scripts/github-setup.sh            # apply to Shavvimal/podcast-explainer
#   REPO=someone/fork scripts/github-setup.sh
#
# The ruleset mirrors the maintainer's other plugin repositories: pull requests only, squash merges,
# linear history, conversation resolution, and the CI checks `check (3.13)`, `template` and
# `version-bump` required. Branch protection is applied to the repository, so it needs a pushed main.
set -euo pipefail

REPO="${REPO:-Shavvimal/podcast-explainer}"
DESCRIPTION="Claude Code plugin: two-host podcast-style explainer videos (Gemini TTS + Remotion) with a sourced script, QC judge, and a searchable transcript library with flashcards and a self-test."
TOPICS=(claude-code claude-code-plugin explainer-video podcast remotion gemini-tts text-to-speech learning-science education agent-skills)

echo "repository settings for $REPO"
gh repo edit "$REPO" \
  --description "$DESCRIPTION" \
  --homepage "https://github.com/$REPO#readme" \
  --enable-issues --enable-wiki=false --enable-projects=false --enable-discussions=false \
  --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false \
  --delete-branch-on-merge --allow-update-branch

echo "topics"
args=()
for t in "${TOPICS[@]}"; do args+=(--add-topic "$t"); done
gh repo edit "$REPO" "${args[@]}"

echo "security: private vulnerability reporting, dependabot alerts"
gh api -X PUT "repos/$REPO/private-vulnerability-reporting" >/dev/null || echo "  (private vulnerability reporting: not available on this plan or already on)"
gh api -X PUT "repos/$REPO/vulnerability-alerts" >/dev/null || echo "  (dependabot alerts: already on)"

echo "ruleset on main"
ruleset=$(cat <<'JSON'
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["squash"] } },
    { "type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": true,
        "required_status_checks": [
          { "context": "check (3.13)" },
          { "context": "template" },
          { "context": "version-bump" } ] } }
  ],
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
  ]
}
JSON
)
# Rulesets need a public repository or GitHub Pro. On a private free-plan repository the API answers 403;
# rerun this script after the repository goes public.
if listing=$(gh api "repos/$REPO/rulesets" 2>/dev/null); then
  existing=$(printf '%s' "$listing" | python3 -c 'import json,sys; print(next((r["id"] for r in json.load(sys.stdin) if r["name"]=="main"), ""))')
  if [ -n "$existing" ]; then
    echo "$ruleset" | gh api -X PUT "repos/$REPO/rulesets/$existing" --input - >/dev/null
    echo "  updated ruleset $existing"
  else
    echo "$ruleset" | gh api -X POST "repos/$REPO/rulesets" --input - >/dev/null
    echo "  created ruleset"
  fi
else
  echo "  SKIPPED: rulesets are not available on this repository yet (private repository on a free plan)."
  echo "  Make it public (gh repo edit $REPO --visibility public --accept-visibility-change-consequences) and rerun."
fi

echo "labels"
export GH_REPO="$REPO"
gh label create bug --color d73a4a --description "Something is wrong" --force >/dev/null
gh label create enhancement --color a2eeef --description "A new feature or an improvement" --force >/dev/null
gh label create pedagogy --color 0e8a16 --description "Script, learning-design or judge rules" --force >/dev/null
gh label create renderer --color 5319e7 --description "Remotion template, scenes, captions" --force >/dev/null
gh label create tts --color fbca04 --description "Gemini TTS, voices, timing, loudness" --force >/dev/null
gh label create qc --color 1d76db --description "qc.py checks, judge and restate protocol" --force >/dev/null
gh label create library --color c5def5 --description "Transcript, captions, library, learn/ and search" --force >/dev/null

echo "done: https://github.com/$REPO"
