.PHONY: check hygiene lint format test typecheck validate

SKILL = skills/podcast-explainer-video
PY    = $(SKILL)/scripts tests scripts

# The whole gate. CI runs the same steps; see .github/workflows/ci.yml.
check: hygiene lint test validate

# Public-repository scan: home paths, personal emails, key shapes, and the private terms in
# $XDG_CONFIG_HOME/podcast-explainer/private-terms when that file exists.
hygiene:
	python3 scripts/check_hygiene.py

lint:
	uvx ruff check $(PY)

format:
	uvx ruff check --fix $(PY)

# Standard library only. The renderer tests need PE_REMOTION_DIR=<a Remotion project with node_modules>
# and skip without it. A few tests need ffmpeg and skip without it.
test:
	python3 -m unittest discover -s tests

# Type-check the Remotion template against an installed node_modules (PE_REMOTION_DIR), without touching
# the template folder itself.
typecheck:
	@test -n "$(PE_REMOTION_DIR)" || { echo "set PE_REMOTION_DIR to a Remotion project with node_modules (see CONTRIBUTING.md)" >&2; exit 2; }
	@tmp=$$(mktemp -d) && cp -R $(SKILL)/templates/remotion/. "$$tmp" && ln -s "$(PE_REMOTION_DIR)/node_modules" "$$tmp/node_modules" && (cd "$$tmp" && npx tsc --noEmit) && rm -rf "$$tmp"

validate:
	node --check $(SKILL)/scripts/align.mjs
	claude plugin validate . --profile directory
