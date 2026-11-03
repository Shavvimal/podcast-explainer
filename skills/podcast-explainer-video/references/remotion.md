# Remotion: project, preview, stills, render

Contents
- [1. Versions](#1-versions)
- [2. Project layout](#2-project-layout)
- [3. Setup](#3-setup)
- [4. How the composition works](#4-how-the-composition-works)
- [5. Captions and the speaker rail](#5-captions-and-the-speaker-rail)
- [6. Theme, safe areas, text size](#6-theme-safe-areas-text-size)
- [7. Preview and stills](#7-preview-and-stills)
- [8. Render](#8-render)
- [9. Licence](#9-licence)
- [10. Official Remotion skills](#10-official-remotion-skills)
- [11. Pitfalls](#11-pitfalls)

## 1. Versions

Pinned in `templates/remotion/package.json` on 2 Nov 2026. All `@remotion/*` packages must carry the same exact version, with no `^`.

| Package | Version |
| --- | --- |
| `remotion`, `@remotion/cli`, `@remotion/media`, `@remotion/captions`, `@remotion/google-fonts`, `@remotion/paths`, `@remotion/media-utils`, `@remotion/install-whisper-cpp` | 4.0.540 (latest stable on npm, released 2 Nov 2026) |
| `react`, `react-dom` | 19.3.1 |
| `prism-react-renderer` (code highlighting, synchronous, works headless) | 2.4.1 |
| `katex` (equations, bundled from npm, CSS fonts awaited before capture) | 0.19.1 |
| `typescript` (type check only; Remotion bundles with esbuild) | 5.9.3 |
| whisper.cpp (built by `align.mjs`) | 1.5.5 |

To upgrade, follow the official `remotion-upgrade` skill, then rerun the tests in section 8.

## 2. Project layout

```
explainers/remotion/                 copy of templates/remotion/, npm install once
  package.json  tsconfig.json  remotion.config.ts (jpeg frames, h264, CRF 18, entry src/index.ts)
  sample-inputs/                     script.json, scenes.json, timing.json of the built-in sample;
                                     ring/ = script.json, scenes.json of the ring sample (episode sample-ring)
  public/episodes/<slug>/            episode.json, episode.wav, diagrams/, img/ (synced by build_manifest.py);
                                     sample (hash map, with audio) and sample-ring (silent, placeholder timing)
  src/
    index.ts  Root.tsx               composition "Episode", calculateMetadata reads the manifest
    Episode.tsx                      master <Audio>, one <Sequence> per scene, overlays
    types.ts  time.ts  theme.ts  context.ts  svgSanitize.ts (allowlist check for diagram SVG files)
    motionConstants.ts  frames.ts    pure timing: LEAD_FRAMES, ENTRANCE_MS, MIN_TEXT_PX; msToFrame, cueFrame, answerFrame, entranceFrames
    overlayState.ts                  pure: chip expiry (visualStepTimes, chipFrames)
    visibleText.ts                   pure: texts a scene draws at a time, labelSourcesAt (QC mirrors it, visuals.md section 11)
    components/                      SpeakerCaptions, captionPages, SpeakerRail, KeywordChips, ChapterLabel, PauseCue
    scenes/                          TitleScene, world/WorldScene (WorldScene, WorldCanvas, useSharedWorld),
                                     world/worldState (timeline, ring layout and checks, node sizes, fitCamera,
                                     visibility, ownership, label expiry, walk plans,
                                     mark expiry and persist, focusProblems, virtual node points),
                                     DiagramScene, CodeScene, EquationScene, RecapCard, CheckYourselfCard,
                                     CompareScene + compareState (pure banner, panel and table state, count claims,
                                     claimText placeholders and claimTextProblems),
                                     tableLayout (pure table geometry, row-label column, tableProblems),
                                     common (Stage), index (registry)
    scenes/custom/                   bespoke scenes + CUSTOM_SCENES registry (examples: BucketFill, RingLoad)
```

## 3. Setup

```bash
mkdir -p explainers
cp -R <skill>/templates/remotion explainers/remotion
cd explainers/remotion
npm install                       # about 11 s on 2 Nov 2026; Remotion downloads its headless Chrome on first render
npx tsc --noEmit                  # optional type check
npx remotion render Episode out/sample.mp4   # renders the built-in 30 s sample out of the box
```

npm 11 prints `install-scripts ... esbuild@0.28.1 (postinstall)` as a warning. Ignore it: the platform binary (`@esbuild/darwin-arm64`) installs as an optional dependency and bundling works without the postinstall step (tested 2 Nov 2026).

Do not install anything globally. `align.mjs` must run from this folder, because it loads `@remotion/install-whisper-cpp` from its `node_modules`.

## 4. How the composition works

- `src/Root.tsx` registers one composition, `Episode`, with `defaultProps {slug: "sample"}`. `calculateMetadata` fetches `public/episodes/<slug>/episode.json` and returns `durationInFrames = ceil((audio.durationMs + video.tailMs) / 1000 * 30)`, the fps, the size and the manifest as a prop. No duration is ever typed by hand. Pick another episode with `--props='{"slug":"hash-maps"}'`.
- `src/Episode.tsx` plays one master `<Audio>` from `@remotion/media` for the whole episode. Each scene is a `<Sequence from durationInFrames premountFor={fps}>` at its manifest times. Scenes never use `TransitionSeries`: a transition overlaps two scenes and shortens the timeline, and the audio clock must not move. Each scene animates its own entrance (7-frame fade and rise, `ENTRANCE_MS` 233 ms in `src/motionConstants.ts`); world-to-world cuts skip the fade so the persistent world does not blink.
- Overlays (pause cue, chapter label, keyword chips, speaker rail, captions) sit above the scene track and read absolute time.
- `PauseCue` reads `episode.json` `holds[]`. During a hold whose turn set `pause: {kind, prompt}` in `script.json`, it dims the stage to 38 % and shows a 1240 x 380 px card centred in the stage: the label "Pause and think" with the kind (Predict, Recall, Explain it back), the prompt at 52 px, and a countdown ring with the whole seconds left. It fades in and out over 8 frames. It never shows the answer; the answer is the next spoken turn. No one speaks during a hold, so captions never collide with the card. Captions never show the answer either: the page builder gets `holds[]` and never starts a page inside a hold that ends before its first word, and `SpeakerCaptions` skips such a page while a hold is running (N05, W8b). A hold without a `pause` shows nothing (`build_manifest.py` warns).
- Every animation derives from `useCurrentFrame()` with `interpolate()` or `spring()`. State changes fire 3 frames before their word (`cueFrame`, `motion.leadFrames`). Anything that gives a result fires on its word with zero lead (`answerFrame`): a check-card answer, a compare verdict, a panel stat, a table row or fill.
- The persistent world has one global timeline (`world/worldState.ts buildTimeline`): world scenes' `steps`, custom scenes' `worldSteps` and compare panels with `world: "shared"`. Each step carries `turnEndMs` (its anchor turn's end plus hold) so a walk arrow can end with its turn. Marks (spotlight, arcs, change band, tint, walk) end at the next step unless the step persists them (`resolveSteps`, `changeVisible`; `visuals.md` section 13). `WorldCanvas` draws a world at a time inside any box, so a compare panel or a custom scene continues the same world (`visuals.md` section 6).
- A09, in frames (W11b): `Episode.tsx` takes each entrance length from `entranceFrames(startMs, enterMs, turns, fps)` in `src/frames.ts`. With `from = msToFrame(startMs)`, the fade of `n` frames is complete on frame `from + n`, which must satisfy `from + n <= floor(S * fps / 1000)` for the next speech start `S` (the turn start or its first word, whichever is earlier). `n` is at most `ENTRANCE_FRAMES` and at most `round(enterMs * fps / 1000)`; a scene that starts inside a turn's speech, or has under 2 frames of room, cuts (`n = 0`). Codex's round-3 case (start 3,017 ms, speech 3,250 ms) now fades over 6 frames, complete at 3,233 ms. `build_manifest.py` writes `enterMs` with the same maths; the renderer clamps again, so a rounding difference can only shorten a fade.
- `build_manifest.py` may start a fading scene up to `ENTER_MS` early (`scenes[].enterLeadMs`) so the entrance ends before the words. `ENTER_MS` must equal `ENTRANCE_MS` (233 ms, 7 frames) in `src/motionConstants.ts`, the one place the entrance length lives. When the silence is shorter still, `build_manifest.py` writes `scenes[].enterMs` (a shorter fade, 0 = cut); `Episode.tsx` passes it to the scene through `EnterFramesContext`, and `Stage`, `WorldScene` and `CompareScene` (and every custom scene that uses `Stage`) fade over that many frames. It stays at or below the default 250 ms gap between turns, so the fade fits in the silence before a turn and never overlaps speech (A09). Change both together.
- `src/time.ts` holds the only ms-to-frame conversion (`msToFrame`).

## 5. Captions and the speaker rail

`SpeakerCaptions` builds pages per turn (a page never spans two speakers) from `turns[].words[]`:

- `karaoke` (default): 3 to 7 words per page, one line up to 46 characters. Spoken words turn white, the current word takes the speaker colour, unspoken words are grey (`colors.dim`, 6.4:1).
- `pop`: 1 to 3 words per page; each word springs in on its start frame. Unspoken words keep their space at opacity 0 so the line does not jump.
- `off`: no captions. A scene can also set `"captions": "off"` for its duration.

Page rules: break at sentence ends, at commas (karaoke: from 4 words), at pauses over 600 ms, and at the word or character cap. A sentence that ends within two words may run two words over the cap, so no page starts with the stranded end of a sentence. Readability: a page must stay on screen at least `max(minPageMs, chars / maxCharsPerSecond)`, defaults 700 ms and 17 characters per second. A page that speech would flash past merges with its neighbour in the same turn, up to two lines (88 characters). A word lights on the frame its `startMs` maps to, never earlier.

Three passes then cap the reading rate and remove flicker (`captionPages.ts`, ported line for line in `qc.py caption_pages`):

1. Rebalance: a page above 19 characters per second (`TARGET_CPS`) moves its boundary with a neighbour in the same turn by up to 4 words (each side keeps 2) when that lowers the faster page of the pair. This fixes a short fast question after a long sentence ("...on the ring. Do they have a name?").
2. Early start: a page still above 19 may appear up to 500 ms before its first word, into silence only (after the previous page's last word, and never pushing the previous page above 19). Its words stay grey until spoken.
3. Hold: a blank of 1 to 166 ms between two pages (under 5 frames) is closed by holding the earlier page until the next starts, also at a speaker change.

The early start never reaches into a pause-and-think hold (`buildCaptionPages(turns, mode, cps, minPageMs, holds)`): a page whose first word comes after a hold starts at the hold's end at the earliest. Before W8b, an answer spoken 250 ms after a 7 s retrieval hold appeared in grey 500 ms early, inside the hold.

Measured on 2 Nov 2026 (consistent-hashing, 10:48, 260 pages): blank flickers 49 before, 0 after; peak 23.0 characters per second before, 20.1 after, 0 pages above 21.

Measured on 2 Nov 2026: Gemini audio (66 s, 6 turns) gave 26 karaoke pages, none under 0.7 s, highest rate 19.2 characters per second. The fast `say` sample (230 words per minute) peaks at 22.3. Pop mode cannot meet the 0.7 s floor on fast speech (8 to 10 short pages per 30 to 60 s); use it only for slow, punchy turns.

Reading-rate rule: 17 characters per second (`maxCharsPerSecond`) is what the merge step aims for; 19 is the cap the rebalance and early-start passes work to; `qc.py captions` warns above 21 (see `qc.md` section 2). Do not slow the voice to fix a warning: split the turn, or set `captions.maxCharsPerSecond` lower so more pages merge.

`SpeakerRail` shows two badges in the bottom band, left and right of the captions, from `speakers[].side`. A badge is the avatar (`speakers[].avatar`, an image under `img/`) or the initials in the speaker colour. The active speaker comes from turn times: it springs to full opacity and a thicker ring at the turn start and fades over 6 frames after the turn end. `rail.waveform: true` adds a 7-bar level meter next to the active badge (`useWindowedAudioData`, 30 s windows, so long WAV files load in pieces). The level is of the mixed track, gated by the active speaker.

`KeywordChips` shows up to three chips in one row at the top right, at 36 px; each ends at the next visual step after it unless `persist: true` (`src/overlayState.ts`, `visuals.md` section 12). `ChapterLabel` shows `NN Segment title` at 36 px at the top left, except on title, recap and check cards.

## 6. Theme, safe areas, text size

`src/theme.ts` holds every token. Fonts load through `@remotion/google-fonts` (Inter 400/600/700/800, JetBrains Mono 400/700), which blocks rendering until they load. Contrast on `bg #0E1117` (WCAG formula): text 17.2:1, muted 8.8:1, dim 6.4:1, accent 10.1:1, good 10.4:1, warn 10.3:1, default speaker colours 5.9:1 and 10.3:1. All code-highlight colours are at least 6.7:1 on the code panel.

Regions at 1920x1080:

| Region | Box | Use |
| --- | --- | --- |
| Action-safe | 96 px left and right, 54 px top and bottom | nothing outside it |
| Top row | y 54 to about 110 | chapter label (left), keyword chips (right) |
| Stage | x 96, y 124, 1728 x 712 | every scene; the pause cue card (x 340 to 1580, y 290 to 670) during holds |
| Band | y 852 to 1026 | captions (x 300 to 1620) and speaker badges |

Type scale: minimum 28 px anywhere, labels 30, body 36, captions 46, headings 56, title 96, code 30, equations 60. World node labels are 34 px at zoom 1; `build_manifest.py` warns below zoom 0.9. Chrome text that every frame shows is at 36 px, the phone size `qc.py text.phone` checks (R01, W11b): the chapter label, keyword chips, the speaker name under each badge, the pause-cue kind line and the compare tag and verdict pills. Compare table text is 28 to 36 px (it shrinks to fit its cells, and a table that would go under 28 px does not render); a row label is 28 to 36 px in a 180 to 320 px column; ring numerals in a compare panel are 32 px or more; a virtual node's point subscript is 0.7 of its label and never under 28 px.

## 7. Preview and stills

```bash
npx remotion studio                          # opens the browser; choose the slug in the props panel
npx remotion still Episode out/s.png --props='{"slug":"hash-maps"}' --frame=450
npx remotion render Episode out/stills --props='{"slug":"hash-maps"}' --frames=20,130,240,480 --image-format=png
```

The last form renders several frames in one bundle (15 frames in 9 s on 2 Nov 2026); the files are named `element-<frame>.png`, and a relative output path is resolved from the Remotion folder. Frame N shows time N/30 s.

For QC, `qc.py stills` extracts frames from the delivered mp4 by default (what the learner will see), including one still at the middle of every turn in mechanism, example, misconception, compare, scale and transfer segments. `--from-remotion` renders them from source instead, for a preview before the mp4 exists. To find the frame of a word: `round(word.startMs * 30 / 1000)`. For hero stills before any audio (gate 2), build with `build_manifest.py --placeholder-timing`; stills render without sound and with estimated word times. Read each still as an image and look for: text under 28 px, text clipped by the stage edge, a caption over a diagram label, a node off-screen after a camera move, the answer shown before its cue, and two highlighted things competing.

## 8. Render

Benchmark once per machine, then render with the best concurrency:

```bash
npx remotion benchmark Episode --concurrencies=4,8,12,16 --runs=2
npx remotion render Episode out/episode.mp4 --props='{"slug":"<slug>"}' \
  --codec=h264 --crf=18 --image-format=jpeg --concurrency=16
```

Measured on 2 Nov 2026, Apple M5 Max (18 cores, 128 GB), Remotion 4.0.540:

| Run | Result |
| --- | --- |
| Benchmark, 30 s sample (899 frames) | concurrency 4: 12.6 s; 8: 7.0 s; 12: 5.7 s; 16: 5.3 s |
| Render 30 s sample, default concurrency | 9.8 s wall |
| Render 66.6 s Gemini episode (1998 frames), concurrency 16 | 11.7 s wall |
| Fresh copy: npm install, then render 30 s sample | 11 s + 14.5 s |

Rule of thumb: on this machine a 10-minute episode renders in about 2 minutes at concurrency 16 (extrapolated from the runs above, not measured). On another machine, rerun the benchmark; more tabs stop helping past the core count.

Loudness: `tts.py` sets the mono wav to -19 LUFS with a true-peak ceiling of -4.5 dBTP; Remotion's stereo AAC measures about 3 LU louder and raises the true peak by 1.6 to 2.5 dB. On 2 Nov 2026 (consistent-hashing) the -4.5 ceiling gave an mp4 at -16.1 LUFS and -2.0 dBTP; `qc.py probe` needs below -1 dBTP. Do not quote the wav ceiling as the mp4 value.

Check after every render (see `qc.md` for the full QC pass):

```bash
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,nb_frames,duration -of csv=p=0 out/episode.mp4
```

Expect `h264,1920,1080,30/1,<frames>` and an `aac` stream (48 kHz stereo), with frames equal to `ceil((durationMs + tailMs) * 30 / 1000)` (the sample: 899 frames for 29 934 ms; video 29.967 s, audio 29.973 s). Remotion's default `--gl` and bundled Chrome are correct; do not set `--browser-executable`. `--hardware-acceleration=if-possible` cannot be combined with `--crf`; keep software x264 at CRF 18.

## 9. Licence

Remotion is source-available under its own licence, not open source. The Free License covers an individual, for personal or commercial use, and an organisation with a total headcount of 3 or fewer; automation is allowed under it (https://www.remotion.dev/docs/license/faq, read 2 Nov 2026). Personal use by an individual qualifies. Use inside a company needs a check first: if the company's total headcount is over 3, a Company License is needed even when only one person uses Remotion ("Remotion for Creators", $25 per seat per month, or "Remotion for Automators" for automations; https://remotion.pro/license). Ask before rendering for a company.

## 10. Official Remotion skills

The Remotion team maintains agent skills at https://github.com/remotion-dev/skills (install: `npx skills add remotion-dev/skills`). Load them for anything this file does not cover: `remotion-best-practices` (router), `remotion-markup` (sequencing, timing, fonts, measuring text, transitions), `remotion-captions`, `remotion-render`, `remotion-upgrade`. Two deliberate differences: this skill uses Gemini TTS, not the ElevenLabs default in the official `voiceover` rule; and captions come from the manifest, not inlined caption arrays, because an agent pipeline regenerates them.

## 11. Pitfalls

1. CSS `transition`, `animation`, `@keyframes`, Tailwind animation classes, `setTimeout`, `requestAnimationFrame`, `useState` for motion, Framer Motion: none follow the frame clock. Use `useCurrentFrame()`.
2. `Math.random()` flickers between frames. Use `random("seed")` from `remotion`.
3. Per-scene audio or `TransitionSeries`: voices overlap and the timeline shrinks. One master `<Audio>`, scenes as `<Sequence>`.
4. A raw `<audio>` tag does not render. Use `<Audio>` from `@remotion/media`.
5. Fonts from a CDN or CSS without waiting: frames capture in a fallback font. Use `@remotion/google-fonts`; KaTeX fonts are awaited with `useDelayRender` in `EquationScene`.
6. Mixed `@remotion/*` versions break at runtime. Add packages with `npx remotion add <pkg>` so the version matches.
7. Caption tokens: a page must not span two speakers; words keep script spelling.
8. Times stored as frames break when fps changes. Store ms; convert in `time.ts` only.
9. Text under 28 px at 1080p is unreadable on a laptop, and the judge treats it as a bug. World scenes, compare panels and data diagrams raise their fonts to `28 / scale` units on their own; a custom component or an `svg` diagram must be checked in a still.
10. A scene that ends after the next one starts fails the build; a cue outside its scene never fires visibly (warning).
11. `align.mjs` run from the wrong folder stops with "not installed"; it never silently estimates for that reason.
12. whisper.cpp 1.7.4 or later needs `cmake`; keep 1.5.5 unless cmake is installed.
13. `npx remotion render` without `--props` renders the sample, not your episode.
14. External SVG diagrams (`props.svg`) need stable element ids for reveal steps; reveals and highlights act by id. The render stops with "Diagram ... is not safe to insert" when the file has a script, HTML, an event attribute or an external reference (`src/svgSanitize.ts`); fix the file, do not bypass the check.
15. Rendering by default: the official skills preview in Studio first. In this pipeline, render only at the render step or when asked.
16. Template tests: `PE_REMOTION_DIR=explainers/remotion python3 -m unittest discover -s tests` (from the repository root) also type-checks the template and renders one still per scene type, including a failing unsafe SVG, a plain compare table, banners and tints, and the three CSS-escape payloads; `tests/test_renderer_compare.py` also runs `visibleText.ts` (bundled with esbuild) and the caption hold rule. `tests/test_renderer_w11b.py` covers chip, banner, stat and node-value expiry with `persist`, the true-circle ring (node angles checked to 1e-6), walk arrows that end at the successor (a wrong `to` fails the render), a 14-column table that is rejected with the numbers or drawn at 28 px or more, a row of the wrong length, entrance frames before speech (403 cases), count claims and label sources, and stills of every scene type (22 renderer tests in 55 s on 3 Nov 2026). `tests/test_renderer_w13b.py` covers spotlight, arc and tint expiry, `persist` (true and a list), the change band with `persist: ["change"]`, walk arrows that end at their turn's end or the next step (and stay with `persist`), the `speaksOf` warning (the v6 t23 case) and name matching, two points per server with virtual nodes, a "Before change" row label that sizes its column (291 px) and a 22-character label that is refused, count-claim placeholders and a contradicting stat that stops the render, base labels as label sources that never expire, a five-line equation still, and stills of every scene type (12 tests in about 25 s on 3 Nov 2026). Set `PE_STILLS_DIR` to keep the stills. Without `PE_REMOTION_DIR` those tests are skipped.
17. A render that stops with "Compare table ...", "ring ... ringOffset", "walk of ... successor is ...", "row label ..." or "... but its claim says ..." is a content error found by the renderer's own checks (`tableProblems`, `ringProblems`, `walkProblems`, `claimTextProblems`); `build_manifest.py` reports the same problems before render. Fix scenes.json; do not bypass the check.
18. A spotlight, arc or change band that used to stay across steps and now vanishes at the next step is the W13b rule, not a bug: add `persist` with that kind to the step that set it (`visuals.md` section 13). `focusProblems` warnings (a focus that dims the node the words name) never stop the render; fix them with a step on the word.
