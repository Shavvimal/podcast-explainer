# Manifest: timing.json, scenes.json, episode.json

Contents
- [1. The three files and who writes them](#1-the-three-files-and-who-writes-them)
- [2. timing.json](#2-timingjson)
- [3. scenes.json](#3-scenesjson)
- [4. Anchor resolution rules](#4-anchor-resolution-rules)
- [5. episode.json](#5-episodejson)
- [6. build_manifest.py checks](#6-build_manifestpy-checks)
- [7. Worked example](#7-worked-example)
- [8. Redo one segment](#8-redo-one-segment)

All times are integer milliseconds from the first sample of `audio/episode.wav`. Frames exist only inside Remotion (`src/time.ts`, `msToFrame`). The schemas are `schemas/timing.schema.json`, `schemas/scenes.schema.json` and `schemas/episode.schema.json`.

## 1. The three files and who writes them

| File | Written by | Read by | Holds |
| --- | --- | --- | --- |
| `<slug>/timing.json` | `tts.py` (turn level), then `align.mjs` (adds `words[]`) | `build_manifest.py` | When each turn and word is spoken |
| `<slug>/scenes.json` | The agent, after the script passes validation | `build_manifest.py` | What the screen shows, anchored to turns and words, never to times |
| `<slug>/episode.json` | `build_manifest.py` | Remotion (`calculateMetadata` in `src/Root.tsx`) | Everything resolved to ms; the only input of the composition |

Rule: never type a time into scenes.json. Anchor to a turn or a word. A new take of the audio then re-times every visual when you rerun `align.mjs` and `build_manifest.py`.

## 2. timing.json

`tts.py` writes the turn level. `align.mjs` adds `words[]`, `matchRate` per turn and the `alignment` block.

```json
{ "version": 1, "model": "gemini-3.8-flash-tts", "mode": "per-turn", "scratch": false,
  "sampleRate": 24000, "gapMs": 250, "tailPadMs": 600, "leadMs": 250, "durationMs": 65580,
  "alignment": { "engine": "whisper.cpp", "whisperCpp": "1.5.5", "model": "small.en", "matchRate": 0.994, "alignedAt": "2026-11-02T19:24:02Z" },
  "turns": [
    { "id": "t01", "speaker": "host", "segment": "seg01", "file": "audio/turn-t01.wav",
      "startMs": 250, "endMs": 13050, "timingSource": "clip", "hash": "c959437261c3ffa16eb7", "matchRate": 1,
      "words": [ { "text": "Here's", "startMs": 250, "endMs": 470, "source": "asr" } ] } ] }
```

- `turns[].file` is one clip per turn in both TTS modes. The clip starts exactly at `startMs` in `episode.wav`, so `align.mjs` adds `startMs` to every clip-relative word time.
- `words[].text` is the script spelling, never the ASR spelling. Gemini `<tags>` and `|backchannels|` are not words.
- `words[].source`: `asr` (time measured by whisper.cpp), `interpolated` (script word the recogniser missed, spread between matched neighbours), `estimated` (no recogniser; spread over the clip by letter count).
- `matchRate` = share of the turn's words with `source: asr`. `align.mjs` warns under 0.90: a TTS skip or ad-lib, or an aligner miss. `matchRate` measures script words only, so it can be 1.0 on wrong audio; the fidelity check below decides. `node align.mjs <slug> --show-asr t07` prints what was heard.
- `asr[]` (from `align.mjs`): the raw ASR words as heard, ASR spelling, on the episode clock. `fidelity.py` compares them with the script in both directions (substitutions, deletions, insertions; a changed number or negation is critical) and writes `qc/fidelity.json`; `align.mjs` exits 1 on an unresolved fail. Rules and the `fidelity-accept.json` escape hatch: [qc.md](qc.md) section 2a.
- `audioSha` (from `tts.py`) is the digest of the take; `alignedAudioSha` (from `align.mjs`) is the take the words were aligned to. `tts.py` keeps old `words[]` and `asr[]` only when both match, so a `--retake` of unchanged text drops them. `build_manifest.py` refuses words whose `alignedAudioSha` differs from `audioSha`. Rerun `align.mjs --only <ids>` for changed and retaken turns.
- `holdAfterMs`, `holdStartMs`, `holdEndMs` (optional, from `script.json` via `tts.py`): the hold silence starts when the turn's speech ends (`holdStartMs` = `endMs`, `holdEndMs` = `holdStartMs + holdAfterMs`); the normal `gapMs` or `tailPadMs` follows it, then the next turn. The hold is not in the cache hash, so adding or changing a hold re-times the episode without a new Gemini call.
- `alignment.draft`: true when any word is `estimated`. A draft never ships (`qc.py` `audio.fidelity` fails). Top-level `experimental: true` marks the experimental chunk mode.

`align.mjs` usage, from the workspace Remotion folder:

```bash
cd explainers/remotion
node <skill>/scripts/align.mjs hash-maps                 # all turns
node <skill>/scripts/align.mjs hash-maps --only t03,t04  # after a redo
node <skill>/scripts/align.mjs hash-maps --estimate-only # DRAFT: no recogniser, letter-count timing, never ships
node <skill>/scripts/align.mjs hash-maps --show-asr t07   # print what was heard, change nothing
node <skill>/scripts/align.mjs hash-maps --model medium.en
```

whisper.cpp 1.5.5 and the model download once into `~/.cache/podcast-explainer/whisper.cpp-1.5.5/` (override with `--cache-dir` or `PODCAST_EXPLAINER_CACHE`). Version 1.5.5 builds with plain `make`; versions from 1.7.4 need `cmake`, which this machine does not have. Measured on 2 Nov 2026 (Apple M5 Max): build 21 s, `small.en` download 7 s, alignment of 6 Gemini turns (66 s of speech) 5.2 s at 99.4 % match.

How a word gets its time: whisper.cpp runs on a 16 kHz mono copy of the clip, padded with 0.6 s of trailing silence (without it whisper dropped the timestamps of clip-final words: 7 of 72 turns under 90 % on 2 Nov 2026, 2 of 72 with the pad) with `tokenLevelTimestamps` (DTW) and `splitOnWord`. A word starts at the earlier of its item offset and its first token's DTW time, because the offset alone runs late after a pause (measured: about 160 ms late on "A" after a 190 ms pause). An edit-distance alignment then maps ASR words onto script words. It accepts small spelling differences on words of 5+ letters, one script word against two ASR words ("KV-cache" vs "KV cache") and two script words against one ASR word ("hash map" vs "hashmap"). ASR items such as "100-200" or "5-10%" are split into "100 to 200" and "5 to 10 percent" before matching. Unmatched script words are interpolated.

If whisper.cpp cannot install or fails on a clip, those turns fall back to `estimated`, `alignment.draft` becomes true and the run prints DRAFT. If `@remotion/install-whisper-cpp` is missing (wrong folder), the run stops with exit 1 instead.

## 3. scenes.json

```json
{ "version": 1,
  "conceptAngle": "A hash map is an address calculator: the key computes its own bucket.",
  "video": { "tailMs": 1000 },
  "captions": { "mode": "karaoke", "maxCharsPerSecond": 17, "minPageMs": 700 },
  "rail": { "waveform": false },
  "world": { "nodes": [ ... ], "edges": [ ... ] },
  "scenes": [ { "id": "s02", "type": "world", "captions": "on",
      "anchor": { "from": { "turn": "t02" }, "to": { "turn": "t03", "edge": "end" } },
      "props": { "steps": [ { "at": { "turn": "t02", "word": "hash function" }, "reveal": ["hashfn", "e1"], "focus": ["hashfn"] } ] } } ],
  "overlays": [ { "id": "c1", "type": "chip", "anchor": { "from": { "turn": "t02", "word": "hash function" } }, "props": { "text": "hash function" } } ] }
```

- `scenes[]` share one main visual track. They must not overlap. Types: `title`, `world`, `diagram`, `code`, `equation`, `recap`, `check`, `custom`. Props per type are in `visuals.md` and in the schema (closed objects, so a typo such as `linez` fails).
- `world` is the one persistent concept diagram. It sits at the top level because several `world` scenes share it.
- `overlays[]` hold keyword chips. They may overlap each other; at most three show at once.
- `captions.mode`: `karaoke` (default), `pop` or `off`. A scene can set `"captions": "off"` to hide captions while it is on screen.
- `video.tailMs`: hold after the audio ends. `build_manifest.py` clamps it to 500..3000 (default 1000).

## 4. Anchor resolution rules

An anchor point is one of:

| Form | Resolves to |
| --- | --- |
| `{"turn": "t03"}` | turn start |
| `{"turn": "t03", "edge": "end"}` | turn end |
| `{"turn": "t03", "word": "bucket"}` | start of the first word "bucket" in t03 |
| `{"turn": "t03", "word": "bucket", "occurrence": 2}` | start of the second "bucket" in t03 |
| `{"turn": "t03", "word": "hash function"}` | start of the phrase (consecutive words) |
| `{"turn": "t03", "word": "hash function", "edge": "end"}` | end of the phrase's last word |
| `{..., "offsetMs": -200}` | any of the above plus an offset (-5000..5000) |
| `{"ms": 12000}` | absolute time; an escape hatch, it does not move with a new take |

Matching ignores case and punctuation: `"bucket"` matches `bucket?` and `Bucket,`. The word must appear verbatim in the turn's spoken text. A missing word is an error that quotes the turn text. A word with no letters or digits (`"?"`, `"--"`) is an error, because it would match anywhere. `"word": null` is the same as no word.

Where anchors appear:

1. `scenes[].anchor.from` (required) and `.to` (optional). Without `to`, a scene runs until the next scene starts.
2. `overlays[].anchor.from` and `.to`. Without `to`, a chip runs to the end of the turn it starts in, at least 2.5 s.
3. Inside `props`, every key named `at` or ending in `At` whose value is an anchor gains a sibling `<key>Ms`: `at` gives `atMs`, `questionAt` gives `questionAtMs`, `answerAt` gives `answerAtMs`. This is generic, so a custom scene can use any `fooAt` key.
4. World nodes and edges may carry `revealAt`. Without it, a node appears at the first world step that names it in `reveal`, `focus`, `focusEdges` or `flow`; if no step names it, at the start of the first world scene. An edge without `revealAt` appears at the first step that names it, else when its later end node appears.

Scene layout after resolution: scenes are sorted by start. A scene that fades in (every change except world to world) starts up to 233 ms (the template's 7-frame entrance, `ENTRANCE_MS` in `src/motionConstants.ts`, which `build_manifest.py` reads from the Remotion project it syncs to) before its anchor when the audio is silent there, so the fade ends before the words; the manifest records the lead as `enterLeadMs`. The entrance length is `enterMs`: 233 ms when the silence allows, else shortened to the silence before the next speech, and 0 (a cut) below 100 ms. The first scene gets `enterMs` too, fitted to the silence before the first word. The template (`Episode.tsx`) fades over `round(enterMs * fps / 1000)` frames when present, else `ENTRANCE_FRAMES`. `build_manifest.py` checks the RENDERED interval with the same maths (A09, 3 Nov 2026): the fade starts at frame `msToFrame(startMs)`, ends at `(from + frames) * 1000 / fps` ms, and that end must be at or before the next speech start; frame rounding can cost a frame, so `enterMs` is whole frames (`round(frames * 1000 / fps)`, for example 200 ms for 6 frames) and the start may move back up to 3 frames into the silence. A scene anchored on a word inside a turn keeps its start and cuts in (`enterMs` 0), so speech never overlaps an entrance, without exceptions; a remaining overlap is a build error. The first scene starts at 0 even if its anchor is later (the screen is never empty). A gap between two scenes is closed by holding the earlier scene (warning when the gap is over 2 s). The last scene runs to `audio.durationMs + video.tailMs`. A cue that fires outside its scene window is a warning.

Components fire a cue `motion.leadFrames` (3 frames, 100 ms) before `atMs`, so a change lands on or just before the word. The manifest stores the true word time.

## 5. episode.json

The composition reads only this file, from `public/episodes/<slug>/episode.json`. Top-level fields:

| Field | Content |
| --- | --- |
| `version`, `id`, `title`, `conceptAngle`, `builtAt` | identity |
| `timingSource` | `whisper.cpp`, `estimated`, `mixed` or `placeholder` |
| `video` | `{fps: 30, width: 1920, height: 1080, tailMs}` |
| `audio` | `{src: "episode.wav" or null, durationMs, sampleRate, scratch}`; `src` is relative to the episode folder; `null` in placeholder mode |
| `speakers[]` | from script.json: `id, name, voice, color, side, role`, optional `avatar` (path under `img/`) |
| `segments[]` | `id, role, title?, startMs, endMs`; the chapter label shows `title` |
| `turns[]` | `id, speaker, segment, text, startMs, endMs, onScreen, holdAfterMs?, words[]` (text without tags and backchannels) |
| `holds[]` | one per turn with `holdAfterMs`: `turn, segment, holdMs, startMs` (`timing.json` `holdStartMs`, the end of speech), `endMs` (`holdEndMs`, capped at the next turn start), `kind` and `prompt` from the turn's `pause` (null when the turn has no pause). `PauseCue` shows the card when both are set |
| `scenes[]` | `id, type, startMs, endMs, enterLeadMs?, enterMs?, captions?, anchor, props` with every cue resolved (`atMs` and so on) |
| `overlays[]` | `id, type: "chip", startMs, endMs, props: {text, color?}`, `auto: true` when added by `--auto-chips` |
| `world` | nodes and edges with `revealAtMs`. A partial `world.camera` (for example only `zoom`) keeps the defaults for the missing fields in `qc.py`; the renderer fix is handed to W7 |
| `captions` | `{mode, maxCharsPerSecond, minPageMs}` |
| `rail` | `{waveform}` |

Composition length: `durationInFrames = ceil((audio.durationMs + video.tailMs) / 1000 * fps)`, computed in `calculateMetadata`. Nothing else sets the length.

## 6. build_manifest.py checks

```bash
python3 <skill>/scripts/build_manifest.py --workspace explainers --slug hash-maps
python3 <skill>/scripts/build_manifest.py --workspace explainers --slug hash-maps --placeholder-timing   # gate 2 stills, no audio yet
python3 <skill>/scripts/build_manifest.py --workspace explainers --slug hash-maps --auto-chips
```

Flags: `--remotion-dir` (default `<workspace>/remotion`), `--tail-ms`, `--no-sync`. It validates with `jsonschema` when it is importable, otherwise with a built-in subset validator. It never downloads or re-executes itself, so `--help` and builds work offline. The slug is validated and must resolve inside the workspace.

Errors (exit 1, all listed, nothing written: every check, including avatars, runs before the first write, and outputs are written atomically with the Remotion `episode.json` last): schema violations; words aligned to another take; an anchor word with no letters or digits; a check scene with an `answer` but no `answerAt`; an SVG diagram or `anchorImage` that holds a `<script>`, an event-handler attribute, a `<foreignObject>`, an external `href`/`src`/`url()`, a `javascript:` URL or a DOCTYPE or ENTITY; for an SVG diagram (inserted as markup) also every refusal of the renderer's `src/svgSanitize.ts` (N07, mirrored in `svg_problems()`): an element outside the SVG allowlist (for example `<image>`, `<a>`), any CSS escape (`\72`) in an attribute or `<style>`, any `url(`, `image-set(` or `src(` left after removing `url(#id)`, `@import`, `expression()`, `-moz-binding` or `behavior:`, an at-rule in `<style>`, `<style>` text that is not plain `selectors { declarations }` rules, a malformed declaration, or a selector outside element / `#id` / `.class` / `[attr]` / `:pseudo` / combinators or naming a non-SVG element (`div`, `body`). A Mermaid-style `<style>` with `#id .class` rules passes; a turn in script.json missing from timing.json; a turn whose `holdAfterMs` differs between script.json and timing.json (rerun tts.py, which costs nothing for a hold change); overlapping turns; an anchor turn or word that does not exist; overlapping scenes; a world step naming an unknown node or edge; an edge whose end is not a node; a `world` scene with no top-level `world`; a missing diagram file or avatar; the last turn ending after the audio.

Warnings (exit 0): a hold without a `pause` cue; a hold cut short by the next turn; a turn without `words[]` (estimated); `episode.wav` length differs from `durationMs` by more than 40 ms (the file wins); a cue outside its scene; a scene gap over 2 s; camera zoom under 0.9; code over 24 lines; a clamped tail; a diagram step that reveals an element an earlier step hid (`hide` is for good); an equation or all-text compare scene that shows only its title for more than 2 s before its first line (W16); a fade that overlaps speech by more than 150 ms; an `onScreen` term not visible within 1.5 s of its turn. Visible means on screen at some frame of that window, replayed with the renderer's own rules (`pe_common.visible_text`, a port of `src/visibleText.ts`; the rules are in `visuals.md` section 11): world nodes after `revealAtMs` and until a `hide`, labels and values after `set`, compare cells after their `fill`, the latest banner and panel stat, diagram elements after their reveal step, answers after `answerAtMs`, chips while they show. With `--auto-chips`, each such term gets a chip at the term's first word.

Sync: writes `<slug>/episode.json`, then copies `audio/episode.wav` (as `episode.wav`), `diagrams/`, `img/` and `icons/` into `remotion/public/episodes/<slug>/`, and writes `episode.json` there last. A placeholder build deletes a stale `episode.wav` there.

## 7. Worked example

The template ships this example: `templates/remotion/sample-inputs/{script,scenes,timing}.json` and the built `public/episodes/sample/`. Turn t02 of the sample is "It never searches. A hash function turns the key into a number." Its aligned words include:

```json
{ "text": "hash", "startMs": 4946, "endMs": 5126, "source": "asr" },
{ "text": "function", "startMs": 5126, "endMs": 5496, "source": "asr" },
{ "text": "number.", "startMs": 6276, "endMs": 6643, "source": "asr" }
```

In scenes.json, scene s02 has this step:

```json
{ "at": { "turn": "t02", "word": "hash function" }, "reveal": ["hashfn", "e1"], "focus": ["hashfn"], "focusEdges": ["e1"], "flow": ["e1"] }
```

`build_manifest.py` matches the phrase `hash function` to the words at 4946 and 5126 and writes `"atMs": 4946` beside `at`. Node `hashfn` has no `revealAt`, so its `revealAtMs` becomes 4946 (first step that names it). In Remotion, `msToFrame(4946) = 148`; the step fires at frame 145 (3 frames lead), the node fades and scales in over 14 frames, the focus ring blends in over 300 ms, and dots start to flow along edge `e1`. The chip overlay `c2`, anchored to the same phrase, springs in at frame 148. The caption page holding "hash" lights that word at frame 148.

Scene s02 is anchored `from {turn: t02}` to `{turn: t03, edge: end}`, so it runs 3596..8373 ms, and scene s03 starts at t04's start (8373 ms). Had s02 ended at t04's end, the build would fail with "scene s02 (3596..11117 ms) overlaps scene s03 (starts 8373 ms)".

## 8. Redo one segment

1. Edit the segment's turns in script.json (keep the turn ids).
2. `python3 <skill>/scripts/tts.py explainers/<slug> --only t07,t08` or `--segment seg03` (new takes only for those turns; every other turn keeps its clip and its words).
3. `node align.mjs <slug> --only t07,t08` from `explainers/remotion` (also for a `--retake` of unchanged text). Fix any fidelity fail it reports.
4. `python3 build_manifest.py --workspace explainers --slug <slug>`. Every anchor re-resolves, so later scenes move with the new take.
5. Render stills of the changed span, then the video.

Build checks the renderer also enforces (W11b, 3 Nov 2026; `build_manifest.py` runs them first so a render never starts): every `role: owner` ring node shares one `ringOffset` and every `role: item` shares one (`pe_common.ring_problems`); a `walk` entry (an item id or `{item, to?, overshoot?}`) ends at the item's successor, the first visible owner clockwise at the step time, unless `to` names another owner with `overshoot: true` (`pe_common.walk_problems`); a compare table has exactly one cell per column in every row and geometry that keeps its text at 28 px or more (`pe_common.table_problems`, a port of `tableLayout.ts`, with the largest column count that fits). W16: a `matrix` scene whose shapes, highlight references or 28 px text rule fail (`pe_common.matrix_problems`, a port of `matrixLayout.ts`, with the largest column count that fits). W13a additions: a row label that would draw under 28 px (the label column grows from 180 to 320 px, then the label text shrinks; at most 18 characters); a count `claim` whose displayed text contradicts it (`pe_common.claim_text_problem`; `{value}`, `{of}` and `{to}` placeholders are filled from the claim first, and a placeholder without a claim is an error). Warnings only (`pe_common.focus_problems`, a port of `worldState.ts` focusProblems): a walk item or target dimmed by the current focus, a `speaksOf` node that is not visible, a turn that names a visible node while the focus dims it.
