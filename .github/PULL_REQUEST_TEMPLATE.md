<!-- Keep pull requests focused: one logical change each. -->

## What

<!-- One paragraph: the behaviour before, the behaviour after. -->

## Why

<!-- The learning or production problem this fixes. Link the issue. For a new pedagogy rule, cite the evidence (learning-design.md tags). -->

## Checklist

- [ ] `make check` passes (hygiene, ruff, unit tests, plugin validation).
- [ ] Tests added or changed for the behaviour.
- [ ] `version` in `.claude-plugin/plugin.json` raised and a `CHANGELOG.md` section added, if anything under `skills/` or `.claude-plugin/` changed.
- [ ] Renderer and `pe_common.visible_text` still agree, if either changed (`tests/test_renderer_*.py` with `PE_REMOTION_DIR`).
- [ ] No personal name, home path, email, API key or private project in the diff.
- [ ] Tested against a real episode if TTS, timing, rendering or QC changed (Gemini model: , Remotion: ).
