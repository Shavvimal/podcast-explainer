# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 - 2026-11-03

First public release of the `podcast-explainer-video` skill as a Claude Code plugin.

### Added
- The skill: `SKILL.md` with the non-negotiables, the depth ladder (`quick`, `standard`, `deep`), the
  15-step checklist, three human gates, the command list, the file map and troubleshooting.
- References: script and pedagogy rules, learning design (rules L1 to L16, moves M1 to M9, judge rubric
  J1 to J11), depth, Gemini TTS, manifest, Remotion, visuals, memory palace, QC, library.
- Scripts: `preflight.py`, `validate_script.py`, `tts.py`, `align.mjs`, `fidelity.py`, `build_manifest.py`,
  `qc.py`, `transcript.py`, `learn.py`, `search.py`, `export_delivery.py`, `write_scores.py` and the shared
  `pe_common.py`. Standard library only on the Python side.
- JSON Schemas for brief, facts, outline, script, scenes, timing, episode, learn, library index and series.
- The Remotion template (Remotion 4.0.540, React 19) with the concept world, compare, matrix, code,
  equation, diagram and card scenes, speaker captions, pause cues, chapter labels and SVG sanitising.
- Three eval scenarios and sample files.
- 384 unit tests. The renderer tests run when `PE_REMOTION_DIR` names an installed Remotion project.
- The Gemini key is read from `GEMINI_API_KEY`, else from `PODCAST_EXPLAINER_ENV_FILE`, else from
  `$XDG_CONFIG_HOME/podcast-explainer/env`.
