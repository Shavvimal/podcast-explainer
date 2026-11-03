# QC: checks, scored rubric, independent judge, redo loop

Load this file for SKILL.md workflow steps 11 (diagnostic QC), 13 (evidence, judge and restate), 14 (final QC and gate 3) and 15 (redo). The checks and the stills use the final encoded `out/episode.mp4`, never the Studio preview, because "preview fine, final file wrong" is a documented failure (hbg-douyin QA table in `../../../research/playbooks/prior-art-agent-video-skills.md`).

## Contents

1. Order of work
2. Automated checks (`qc.py`)
3. Stills Claude reads
4. Scored rubric
5. Independent judge protocol
6. Gate 3: what the learner sees
7. Redo one segment
8. Learning log
9. What QC cannot prove

## 1. Order of work

The judge scores the finished deliverable, so everything that goes into it is made first (N01).

1. Diagnostic pass (step 11). After the render, run `python3 SKILL/scripts/qc.py all --workspace explainers --slug <slug>`. It runs every automated check and extracts the stills from the mp4. Exit 1 means at least one check failed. Fix every `fail`, read `qc/report.md`, the stills and both contact sheets yourself, fix obvious defects. Do not judge yet.
2. Finish the deliverable (step 12). Write `learn.json` with exactly ONE transfer or apply self-test question marked `"heldOut": true`, about a case the video never shows or answers (the restater's held-out case), run `learn.py`, then `transcript.py --embed-chapters` (it also writes `delivery.json`, the sha256 of every transcript, caption, library and sidecar file). The mp4 now has its chapters and does not change again unless a fix needs a new render.
3. Evidence (step 13). Run `qc.py all` again on that final mp4. It writes the stills, `qc/report.json` with the build identity, `qc/report.md`, `qc/judge-brief.md` and `qc/restate-brief.md` (with the held-out question from `learn.json`; `brief.heldout` warns if none is designated and fails when the video already asks or answers it).
4. Start the blind restate agent FIRST with `qc/restate-brief.md` (section 5). Store its reply with `qc.py save-reply --kind restate`. Then start the judge agent with `qc/judge-brief.md`; it reads the stored restater reply (`qc/replies/restate.md`) and scores rubric line 2 from it. Neither is the agent that built the video, and the restater never sees the judge brief. Neither writes a file: each ends its reply with one JSON block. Store the judge's reply with `qc.py save-reply --kind judge`.
5. The parent agent writes `qc/scores.json`: the judge's JSON fields, the judge's reply VERBATIM as received with its sha256, and `restate` with the restater's fields and its reply as received with its sha256 (section 4). Fix the 3 worst problems, rerun what the fix touches through step 12, then `qc.py all`, then re-judge (a new build needs new scores). Stop when every score passes, or after 3 rounds.
6. Final verification (step 14). Run `qc.py all --final`. It never changes the reviewed deliverable (mp4, transcript, captions, library copy, `learn/` files, `qc/scores.json`); it refreshes the QC outputs (`report.json`, `report.md`, both briefs, stills re-extracted from the same mp4) and checks the judged build. Its verdict is "READY FOR APPROVAL" only when every check passes; otherwise gate 3 shows a "FAILED DRAFT (diagnosis only)".
7. Gate 3: the learner watches and listens; their listen note goes into `qc/listen.json` (section 6).

Build identity, stated once here and once in SKILL.md: `build.id` is a digest over `script.json`, `scenes.json`, `timing.json`, `episode.json`, `audio/episode.wav`, `facts.json`, `outline.json`, `learn.json`, the generated `learn/` files (`selftest.md`, `teachback.md`, `cards.csv`, `cards.md`, `summary.md`; not `gaplog.md`, which the learner edits), `transcript.json`, `delivery.json`, the resolved glossary, a canonical digest of the review fields of `brief.json` (viewing, depth, minutes, targetMinutes, learnerLevel, lexicon, learnerOutcome, coreMessage) together with the designated held-out item (R04: a change of viewing changes the readability reference, so it is a new build), and the final mp4 (chapters included). A change to any of them is a new build, and scores for another build do not count.

## 2. Automated checks (`qc.py`)

Commands (all take `--workspace DIR --slug SLUG`, plus `--mp4 PATH` to check another file, `--remotion-dir DIR`, `--json`). The slug is validated and must resolve inside the workspace.

| Command | What it does | Writes |
|---|---|---|
| `qc.py probe` | ffprobe spec, duration against the manifest, loudness, true peak, chapters, series part cap, black frames, dead air | `qc/probe.json` |
| `qc.py stills` | From the delivered mp4 with ffmpeg: entry (segment start + 300 ms), middle and exit (segment end - 300 ms) still per segment, one still at the middle of each pause hold, and one at the middle of every turn in a causal segment (mechanism, example, misconception, compare, scale, transfer). Old stills are deleted first. `--from-remotion` renders them from the source with `npx remotion still` instead: a preview for diagnosis, never for the judge. Then a contact sheet (480 px tiles, 6 columns), a phone-width sheet (360 px tiles, 4 columns) and, when `brief.json` `viewing` is `desktop` (the default), the 720p reference sheets: every still at 1280 px wide (a 720p player), 2 columns by up to 3 rows per page (`stills.contact-sheet-720`). With `viewing: phone` the phone sheet is the readability reference and no 720p sheet is written | `qc/stills/*.png`, `qc/stills/index.json` (with the mp4 sha256), `qc/contact-sheet.png`, `qc/contact-sheet-phone.png`, `qc/contact-sheet-720-NN.png` (desktop) |
| `qc.py audio` | Fidelity (raw ASR vs script, both directions, same code as `fidelity.py`) and per-turn level jumps | `qc/audio.json`, `qc/fidelity.json` |
| `qc.py captions` | Rebuilds the caption pages the template draws (same rules as `captionPages.ts`) and checks reading rate, on-screen time, flicker, holds and geometry | `qc/captions.json` |
| `qc.py coverage` | Every `onScreen` term and every spoken number has a visible event; every scene anchor names a real turn; every pause has a hold and a prompt; text size and contrast (`text.minsize`, `text.phone`); count labels true of their compare table (`labels.counts`) | `qc/coverage.json` |
| `qc.py save-reply --slug <slug> --kind judge\|restate` | Stores a reviewer's reply as received (stdin or `--file`) and records its sha256 at storage time; exit 1 when the reply holds no JSON block | `qc/replies/<kind>.md`, `qc/replies/<kind>.json` |
| `qc.py all` | All of the above plus `build.fresh` and `brief.heldout` (`--skip-stills` to skip stills), the build identity, the reports and both briefs. `--final` adds the delivery checks (`final.artefacts`, `judge.scores`, `audio.listen`) and makes `probe.chapters` and `brief.heldout` fails | `qc/report.json`, `qc/report.md`, `qc/judge-brief.md`, `qc/restate-brief.md`, `qc/restate/spoken.md` |

Each check has a status `pass`, `warn`, `fail` or `skip` and an exact fix hint in `report.md`.

| Check id | Pass rule | Fail or warn |
|---|---|---|
| `probe.spec` | 1920x1080, 30 fps, H.264 video, exactly one audio stream, AAC | fail |
| `probe.duration` | Video within 1 frame (33.3 ms) of `audio.durationMs + video.tailMs` from `episode.json` | fail |
| `probe.loudness` | Integrated -16 LUFS within 1 LU (ffmpeg `loudnorm` measure) | warn at 1 to 2 LU off, fail beyond 2 |
| `probe.truepeak` | True peak below -1.0 dBTP | fail; fix: rerun `tts.py` with a lower `--true-peak` than the default -4.5 (`pe_common.MONO_TRUE_PEAK`); the hint names a value |
| `probe.chapters` | One chapter marker per segment in the mp4 | warn; fail with `--final` |
| `probe.partcap` | A series part's measured audio is at most 12 minutes | fail |
| `build.fresh` | The mp4 is newer than `episode.json`, and Remotion's copy of `episode.json` is the same file | fail |
| `audio.fidelity` | Every turn's raw ASR matches the script (section 2a); per-turn Gemini takes with measured alignment | fail on a fail or stale turn, or a draft (scratch, chunk, experimental, `alignment.draft`, estimated words); warn on warn turns |
| `audio.levels` | Every turn clip's mean volume within 6 dB of the median turn | warn |
| `probe.black` | No black run of 0.2 s or more (`pix_th` 0.03, so the dark template background does not count as black) | fail |
| `probe.deadair` | No silence of 1.5 s or more, except pause holds (`episode.json` `holds[]`), `<long pause>` turns and the final tail | warn |
| `stills.render` | Every planned still rendered | fail |
| `captions.rate` | Every caption page at or below 21 characters per second | warn above 21 |
| `captions.minTime` | Every page on screen at least `captions.minPageMs` (default 700 ms) | warn |
| `captions.flash` | No blank gap of 1 to 120 ms between two pages (a flicker) | warn |
| `captions.hold` | No caption page starts inside a pause hold (`[startMs, endMs)` of `holds[]`) when its first word comes at or after the hold's end (N05: `caption_pages` takes `holds` like `buildCaptionPages`, so the answer to a predict prompt never shows while the learner thinks) | fail |
| `captions.geometry` | The caption box (x 300 to 1620, y 852 to 1026) does not overlap the stage, the speaker badges, or a world node's screen box while captions are on | fail on overlap, warn on clipping |
| `coverage.onScreen` | Each `onScreen` term is visible within 1.5 s of its turn. Visibility is replayed with the renderer's rules (`pe_common.visible_text`, the one Python copy, a line-for-line port of `src/visibleText.ts` shared with `build_manifest.py --auto-chips`; rules in `visuals.md` section 11): world nodes from `revealAtMs`, then `hide` and `reveal` steps; labels and values after `set`; only the current step's note; state changes from 3 frames (100 ms) before their cue, results from the cue; compare-table cells named in a `fill` show `?` until that step's answer time; `verdict` and `banners[]` as one list, only the latest whose `atMs` has passed (`text: ""` shows nothing) with its labels; panel `title`, `tag` and `stat` as inherited at that time; diagram elements from their first reveal step; uncued steps at the renderer's fallback frames; answers after `answerAtMs`; numeric props of custom components as drawn. A window counts a text if it is on screen at any frame inside it. `tests/test_w9.py` runs both on shared fixtures | warn |
| `coverage.numbers` | Each digit number spoken is visible within 1.5 s of its turn, same rule | warn |
| `text.minsize` | No text under 28 px (`MIN_TEXT_PX`) and no text fill under 4.5:1 (WCAG) on the background #0E1117. Never skipped: with nothing to compute it passes and names the scenes it read; a file it cannot read is a warn with the reason. Reads (1) custom components (the `.tsx` file `src/scenes/custom/index.ts` imports for each `component` in `episode.json`): every `fontSize` (style key or JSX prop) that is a number, a `type.*` size from `theme.ts` or arithmetic on them; (2) SVG diagram files: every `font-size` attribute, `style` value, `<style>` rule and `font:` shorthand, times the stage scale `DiagramScene` applies (the file's viewBox fitted into 1728 x 712, or 1728 x 620 under a title, `meet`; no viewBox is 1:1; `pt` is 4/3 px); (3) compare `kind: "table"` panels with a port of `tableLayout.ts` (`qc.table_layout`: more than 8 columns wrap into equal bands, cell, header and label text at `type.grid` 36 px), or the legacy one-row layout (`type.label` 30 px, every column in one row) when the Remotion project's `CompareScene.tsx` has no `tableLayout.ts` beside it; cell text (`colors.bg`) on each `valueColors` fill; (4) diagram inline `elements` of kind `text`: size `max(28, 28 / scale, fontSize or 30) x scale`, `fill` contrast, and the dimmed contrast of text that is not in the last step's `highlight` at the end of the scene (`DiagramScene` dims it to opacity 1 - `DIAGRAM_DIM`, 0.65) | fail on a size under 28 px (file and line, or scene and element) or a fill under 4.5:1; warn when the size is computed (`fontSize: s * 2`), relative (`em`, `rem`, `%`), the 16-unit default (no `font-size` at all), under a `transform` scale, inside a custom `<svg viewBox>` that is not 1:1, a colour that is not hex, a table cell smaller than its text plus 8 px, or text dimmed under 4.5:1 at the end of a scene. `Math.max(type.min, ...)` counts as clamped. Runs with `qc.py coverage` |
| `text.phone` | The same sources against the phone threshold: no text under 36 px at 1080p (about 7 px at 360 px wide) and no grid band with more than 8 cells per row. It also reads the `fontSize` values of the built-in components the episode draws (SpeakerRail and ChapterLabel always, KeywordChips with chips, PauseCue with holds, CompareScene with a compare scene; the project's copy, else the template), so a pill or rail name under 36 px is found (R01). Known exceptions under 36 px by design (W11b, 3 Nov 2026), not scanned: world sublabels and edge labels (28 px floor), the world note (32 px), ring labels in compare panels (32 px floor), code (30 px). The detail names `brief.json` `viewing` | fail when `viewing` is `phone`; warn when it is `desktop` or missing (the judge then scores readability on `contact-sheet-720-NN.png`) |
| `labels.counts` | J11, the part a machine can compute: on a compare panel of `kind: "table"` with two rows, every stat, panel title and tag (static and per step), banner pill label, banner text and chip that shows while the table is on screen is true of the table state at that frame (rows, `fill`, inherited stat, latest banner; sampled at every cue). "X of Y" with a move word (move, moved, moves, miss, change, stay, stays, keep) must equal the number of differing columns (equal columns for stay and keep) between the two rows, of Y = the column count. A server count "P to Q" or "P → Q" (with a move or server word) or "mod P" must match the row moduli (`k mod 3`, `k mod 4`) unless the text marks the general case ("in general", "general", "any N", "e.g."). "fixed fleet" or "N fixed" must not show over a table whose rows have two moduli, unless the same text names the changing fleet. "X of Y move to V" counts the columns that change TO value V (before [A,B,C,A], after [D,D,B,A]: "2 of 4 move to D" is true). A chip or banner may carry a structured `claim` `{kind: "count", of, scope: "columns-changed" | "cells-changed-to", value, to, side}` (when the scenes schema allows it), which is checked exactly whatever the wording. A banner clause that names only the other panel (its title or tag word, for example "Ring:") is not checked against the table. Each finding gives mm:ss, scene, side, turn, the text and the computed value; the detail and the judge brief list the VERIFIED labels and, apart, the UNCHECKED ones (ambiguous wording such as "miss", or a partly filled table) | fail on an X-of-Y count in unambiguous wording (move, change, stay, keep, "move to V") that differs from a fully filled table and is the panel's own stat, title, tag or pill label, or a banner clause that names the panel, and on a false structured claim; warn on the rest (ambiguous verbs, partly filled table, unattributed banner clause, server counts, fleet condition). Labels on world panels and verdict words stay on the judge's J11 checklist |
| `labels.stale` | A node's own `label` and `sublabel` never expire, so a base label or sublabel that states a number ("4 keys per server") and stays drawn more than 3 s after a related reveal or hide fails with every renderer (W13a, Q03: move the count into `value` or a `set` patch). A quantity label (a number, or per/each, with a word of 3+ letters: "keys per server: 4 each", "D's keys 3"; a bare id such as "7" or "B" is not one) set at world step S (a node's reveal or a `set` patch on it), a chip, or a compare banner over a world panel, must not stay drawn more than 3 s after a later world step reveals or hides a node it counts: a ring node with a `role`, or a node whose label word is in the label text. The v3, v4 and v5 judges each found such a stale chip | With the current template (W11b, `overlayState.ts`) every label ends at the next step unless it says `persist: true` (node, `set` patch, stat, chip props or banner), so only a persist label can be stale: warn (persist is the author's claim that it stays true; confirm it). With an older Remotion project that keeps labels until changed (no `overlayState.ts`): fail, unless updated or hidden within 3 s |
| `labels.early` | W16 (W15 proposal): a quantity on a cued label (chip, panel stat, banner text or side label, verdict, step note, world `set` value or label) shows before it is spoken. "X of Y" counts as one quantity and must be spoken as "X of Y" (or "X of the Y"). A quantity spoken earlier in the same scene passes; one never spoken is not reported; a lead up to 2 s inside the turn that speaks it passes. The detail names the turn the label shows in, the turn that speaks it, and the lead time. W18: when the picture is meant to lead (a cold-open prompt, a recap count carried from the last scene, the same quantity said in other words), add `earlyOk: "<reason>"` to that step, banner, equation line or chip props in `scenes.json`; the check lists it as reviewed with its reason and never counts it. Do not use earlyOk to hide a label that only needs a later anchor | warn in the diagnostic run; FAIL under `--final` while any unreviewed early label remains; pass when every early label is anchored to its word or carries `earlyOk` |
| `world.nodefit` | W16 (W14b D15): every box, pill and circle node is tall enough for its label, sublabel and value (its own or any `set` value). Pills grow to 128 for a value and to 160 for a sublabel plus a value, boxes to 160 for a value; an explicit `h` that is too short fails | fail |
| `marks.focus` | W14a port of worldState.ts `focusProblems` with the W13b expiry rules (spotlight, arcs, tint, change band end at the next step unless the step persists them; walk arrows end at the next step or the anchor turn's end, at least 1.5 s): a walk's item or target dimmed by the current focus, a `speaksOf` node that is hidden, or words naming a visible node while the focus dims it. `qc/stills/index.json` also lists the marks drawn on each still (`marks`) | warn (the same list `build_manifest.py` prints); fix with a step on the word that puts the node in `focus` or `speaksOf`, or `focus: []` |
| `coverage.anchors` | Every `anchor.from` and `anchor.to` turn in `scenes.json` exists in `script.json` | fail; an absolute `ms` anchor is a warn |
| `coverage.pauses` | Every turn with `pause` has a hold in `episode.json` with a prompt | fail |
| `brief.heldout` | `learn.json` designates exactly ONE selfTest item with `heldOut: true` at transfer, apply, analyse or create level (R05), and the video does not already ask it: under 50% of its question's content-word pairs in any ONE spoken turn, pause prompt or on-screen text. Answer overlap (50% of its content-word triples) is EVIDENCE for the judge, not a verdict (W13a, Q02): an answer that applies the taught rule to a new case shares its words by design, and a paraphrased demonstrated case shares none. The judge decides with `heldOut.demonstrated` and quotes the closest case and solution | none designated: warn, fail with `--final`; two or more, a wrong level, or question overlap: fail; answer overlap: warn (the overlap numbers go into the judge brief) |
| `final.artefacts` (`--final`) | `transcript.md`, `transcript.json`, `captions.vtt`, `captions.srt`, `learn.json` and the `learn/` files exist; `transcript.json` `provenance` and `learn/provenance.json` `sources` hold the digests of the current `script.json`, `timing.json` and `learn.json`; the `learn/` files still have the digests `learn.py` wrote; every delivered derivative (N06: transcript.md, transcript.json, captions.vtt, captions.srt, chapters.ffmetadata, `library/<slug>.md`, and the `.srt`, `.vtt` and `transcript.md` sidecars beside the mp4) exists, has the sha256 `delivery.json` recorded, and is byte-equal to what `transcript.py` renders now from the current inputs (so an edit of a file and of `delivery.json` together is caught); the library record is registered with current times; every `library/learn/<slug>/` file is byte-equal to its canonical `<slug>/learn/` file; the episode's `library/index.json` record equals the one `transcript.py` and `learn.py` compute now (mp4 path, chapters, self-test, cards; `openGaps` excluded), and `delivery.json` `record.sha256` binds THAT record, not the whole index (W13a, Q04); every link and image in `learn/*.md` resolves (Q10) | fail |
| `judge.scores` (`--final`) | `qc/scores.json` for this build: `round` 1 to 3; every rubric score a finite number 1 to 10 and 8 or more; every J1 to J11 a finite number 1 to 5, J1, J5, J7, J11 at 4 or more and none below 3; a reason citing an mm:ss or a turn id for every score, and every cited turn id exists in `script.json` and every mm:ss lies inside the episode (N09); `worst`, non-empty while any score is under its bar, each item citing a real turn or time; `heldOut` with `demonstrated` false, `case` and `solution` (the video's closest worked case and its solution, quoted VERBATIM in double quotes with a turn id; every quoted piece of 3 or more words must occur in the spoken or shown text) and `evidence`; every reference in a citation (frame file, turn id, mm:ss) validated on its own, at least one present and none invalid (W13a, Q07); `judgeReply` (the judge's reply VERBATIM) whose sha256 is `judgeReplySha256` and whose last JSON block equals the recorded fields; and `restate` with a score of 4 or 5, a summary, a gaps list, `retrieval` and `transfer` answers each with citations of existing frames or in-range [mm:ss] lines, and `reply` VERBATIM with `replySha256`, its JSON block equal to the recorded fields | fail |
| `audio.listen` (`--final`) | `qc/listen.json` for this build with an empty `problems` list | warn while missing (it is written at gate 3); fail when it names a problem or another build |

Build identity: section 1. `qc.py all` writes every digest and the short `build.id` into `qc/report.json` `build`.

### 2a. Audio fidelity

`align.mjs` keeps each turn's raw ASR (`turns[].asr`, ASR spelling, episode ms) and the `audioSha` of the take it aligned (`alignedAudioSha`), then runs `scripts/fidelity.py`. It compares the raw ASR with the script in both directions: substitutions, deletions (script words nobody said) and insertions (spoken words that are not in the script). Both sides are normalised the same way: contractions expand, number words become digits, "100-200" equals "100 to 200", "5-10%" equals "5 to 10 percent", a sign is a word ("-5" equals "minus 5" and "negative 5"; "-5" heard as "5" is a missing "minus"), and spoken decimals become digits ("zero point seven five" equals "0.75"). Digit homophones (2 and to or too, 4 and for, 1 and won, 8 and ate) are not errors, because they sound the same. Nothing else is fuzzy: the allowed spelling differences are singular and plural, British and American endings (colour/color, normalise/normalize) and one letter in a word of 8 or more letters, never across a negating prefix. A substitution on a direction word (increase/decrease, grow/shrink, more/less/fewer, higher/lower, true/false, correct/wrong, always/never, before/after, earlier/later, include/exclude) changes the meaning and is critical.

| Status | Rule |
|---|---|
| ok | No difference |
| warn | Small non-critical differences (an ASR spelling of a name, a dropped "uh") |
| fail | Any number, sign or negation differs, or a direction word is substituted (critical), or 3 or more differences with a word error rate over 20% |
| stale | `words[]` were aligned to another take (`alignedAudioSha` differs from `audioSha`) |
| missing | No raw ASR: estimated alignment (`--estimate-only`, a declared draft) |

Delivery mode. Only per-turn Gemini takes with measured alignment can ship. Scratch voices, `--mode chunk`, `--experimental`, `alignment.draft` or any estimated word makes the episode a draft (`fidelity.json` `rejected` lists why), and `audio.fidelity` fails.

A fail is resolved by a new take (`tts.py --only tNN --retake`, then `align.mjs --only` for every turn `tts.py` reports as changed) or, after a person listened and the audio is right, by an entry in `<slug>/fidelity-accept.json`: `{"accept": [{"turn": "t07", "audioSha": "<from fidelity.json>", "text": "<the expected text fidelity.py prints>", "reason": "listened: says 'mod 4'"}]}`. `fidelity.py` prints the entry for each fail; you write the reason. The entry binds to the take (`audioSha`) and to the canonical expected text (`text`), and needs a reason: a new take or an edited turn invalidates it, and the report says why an entry was not used. A selective `--retake` of one of several turns with identical text gives that turn its own take (a pin in `audio/cache/pins.json`); the other turns keep their audio and alignment. `node align.mjs <slug> --show-asr t07` prints what was heard. Measured on the 2 Nov 2026 consistent-hashing rerun: 72 turns, 60 ok, 11 warn (names and fillers), 1 fail ("Two seems small" heard as "to seem small"), which led to the homophone rule.

Loudness. Defaults: `tts.py` normalises the mono `episode.wav` to -19 LUFS integrated with a true-peak ceiling of -4.5 dBTP (`--lufs`, `--true-peak`; both from `pe_common.MONO_LUFS` and `pe_common.MONO_TRUE_PEAK`, the one place they are set). Remotion plays the wav as dual-mono stereo in the AAC track, which measures about 3 LU louder, so the mp4 lands near -16 LUFS, the podcast speech norm that `probe.loudness` checks. Remotion's audio path also raises the true peak by 1.6 to 2.5 dB, which is why the wav ceiling sits well under the -1 dBTP limit.

History (measurements, not settings). 2 Nov 2026, consistent-hashing: a -1.5 dBTP ceiling gave an mp4 at +0.1 dBTP and a -3.0 ceiling (measured -2.8) an mp4 at -0.7 dBTP, both fails; a -4.0 ceiling (measured -3.8) gave -16.1 LUFS and -1.5 dBTP, a pass with 0.5 dB margin, so the default moved to -4.5 for more margin; the e2e-v3 render at -4.5 measured -16.1 LUFS and -2.0 dBTP. Earlier, on the W3 hash-maps render, a wav normalised to -16.1 LUFS gave an mp4 at -13.2 LUFS and +0.8 dBTP. YouTube plays at about -14 and turns louder files down, not quieter ones up.

Caption reading rate. The template default `captions.maxCharsPerSecond` is 17, and short pages merge to stay readable. On fast Gemini speech the karaoke peak was 19.2 characters per second (2 Nov 2026, 26 pages over 66 s). That rate is accepted: a karaoke page follows the voice word by word, so the eye does not read it cold. `qc.py` warns only above 21 characters per second. The `say` scratch voice (about 230 words per minute) peaks at 22.3, so a warning on scratch audio is expected.

The raw commands behind the probe, for a manual re-run:

```bash
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels -of json out/episode.mp4
ffmpeg -i out/episode.mp4 -af loudnorm=I=-16:TP=-1.5:print_format=json -f null - 2>&1 | tail -14
ffmpeg -i out/episode.mp4 -vf blackdetect=d=0.2:pix_th=0.03 -an -f null - 2>&1 | grep blackdetect
ffmpeg -i out/episode.mp4 -af silencedetect=noise=-40dB:d=1.5 -f null - 2>&1 | grep silence_
```

Any failure blocks gate 3. Warnings are judge inputs. Checks that `qc.py` does not run (frozen picture, speaker sync, smallest text) are judged from the stills and the contact sheets: no 4 s window inside a turn without a visual change, the speaker highlight on the right host, no text below 28 px, labels readable on the readability reference sheet (`contact-sheet-720-NN.png` for `viewing: desktop`, `contact-sheet-phone.png` for `viewing: phone`).

## 3. Stills Claude reads

`qc.py stills` extracts them from the delivered mp4: per segment an entry still (segment start + 300 ms), a middle still and an exit still (segment end - 300 ms), one per hold, and one at the middle of each causal turn. Read every still with the Read tool. Look for:

- Clipped or overlapping text, text on text during a swap.
- A label that appears before its word is spoken (early reveal, V6).
- A highlight on the wrong node, or no highlight while a host names a part (signalling, V2).
- The concept world resets to an unrelated slide instead of changing state.
- An illustrative number without its "Example data" label.
- Captions that differ from the script text (captions show script spelling; ASR spelling is a bug).

Also read each hold still: it must show the pause card with the prompt and the countdown ring, and never the answer.

Write each defect as `segId tNN @ mm:ss.mmm: what is wrong` in `qc/scores.json` `notes`.

## 4. Scored rubric

Score 1 to 10 on each line. Every line needs 8 or more to pass. Be a harsh reviewer, not a proud author. Each score below 8 names its worst moment with a timestamp.

| # | Dimension | 10 looks like | 5 looks like |
|---|---|---|---|
| 1 | Hook | The first 20 s pose a concrete puzzle and the learner makes a prediction | Opens with a definition or a welcome line |
| 2 | Concept lands | The restate agent (section 5) states the core mechanism and answers the retrieval question correctly | The restate agent names the topic but not the mechanism |
| 3 | Pedagogy | Deep learner questions before key steps, misconception voiced and broken, explain-backs, no praise or filler | Expert monologue with "right" and "exactly" from the learner |
| 4 | Visual matches words | Every spoken claim has a visible state change on its word; one persistent concept world | Visuals decorate; slides reset per segment |
| 5 | Readability | All text at or above 28 px and readable on the reference sheet for `brief.json` `viewing` (desktop: `contact-sheet-720-NN.png`, 1280 px frames; phone: `contact-sheet-phone.png`, 360 px, where text under 36 px at 1080p or a grid over 8 cells per row is a blocker), nothing clipped | Small labels, a 12-cell grid row, text overlaps during swaps |
| 6 | Accuracy | Every number on screen and in speech traces to `facts.json`; negations match their quotes; illustrative data labelled | One number or negation wrong |
| 7 | Caption and speaker sync | Captions light on the word, never before; speaker highlight on the right host; no caption over the active node | Captions lag or cover the diagram |
| 8 | Audio (from numbers only) | `audio.fidelity` pass with no warn turns, `audio.levels` pass, loudness and true peak pass, no `probe.deadair` warning, no truncated turn (no deletion at a turn end in `fidelity.json`) | Fidelity warns on several turns, a level jump over 6 dB, a dead-air warning, or a deletion at a turn end |
| 9 | Pacing | No dead stretch, no frozen picture, total length within 15% of target | A segment drags or rushes |
| 10 | Pauses | A prediction pause in the cold open that targets the core idea; one retrieval pause every 5 to 6 minutes; each hold 6 to 8 s (an explain-back hold up to 15 s, learning-design.md L11) with the prompt card and no answer on screen | No pause, or the answer shown during the hold |

Audio and the ear. The judge cannot listen, so line 8 is scored only from the numbers above. A fidelity warn that is only an ASR spelling of a name (Priya heard as "prayer") does not lower line 8: add the heard spelling to `brief.json` `lexicon` (`fidelity.py` prints a ready suggestion) before the judge round; clicks at turn joins, voice drift, timbre jumps and misread words are not the judge's to score. They are checked by the learner at gate 3, from the list of fidelity-warn turns the judge names, and recorded in `qc/listen.json` (section 6).

The judge also scores the learning-design rubric J1 to J11 ([learning-design.md](learning-design.md) section 10) on its 1 to 5 scale. Pass: no criterion below 3, and J1, J5, J7 and J11 at 4 or above. J11 is "no label contradicts the scene": every comparison, "wrong versus right", verdict, banner and chip label is true of the frame and of the words at that moment, including scenario flags such as "fixed fleet" or "one point per server".

The judge returns its scores as one JSON block in its reply; it is read-only and writes nothing. The parent agent stores each reply as received: the text of the agent's final message, as the Agent tool hands it back, unedited. Run `qc.py save-reply --workspace explainers --slug <slug> --kind restate|judge` with the reply on stdin (or `--file`): it writes `qc/replies/<kind>.md` and records the sha256 at storage time in `qc/replies/<kind>.json`. Then write `qc/scores.json`: the judge's fields, the judge's whole reply VERBATIM as stored (`judgeReply`) with `judgeReplySha256` (sha256 of its UTF-8 text), and the restater's fields and reply the same way. `judge.scores` fails when a stored reply's sha256 differs from the one in `qc/scores.json`. Honest limit: the parent relays the reply, so byte-for-byte fidelity with the model's own output cannot be proven (an HTML entity such as `&gt;` in a relayed reply is the relay's, not the model's). The sha256 proves only that the stored text did not change after storage. `python3 scripts/write_scores.py --workspace explainers --slug <slug>` builds `qc/scores.json` from the two stored replies (do not assemble it by hand). Never retype or summarise a reply:

```json
{"build": "<build.id from qc/report.json>", "round": 1,
 "scores": {"hook": 9, "concept": 8, "pedagogy": 8, "visual": 8, "readability": 8, "accuracy": 9, "captions": 8, "audio": 8, "pacing": 8, "pauses": 8},
 "j": {"J1": 4, "J2": 5, "J3": 4, "J4": 4, "J5": 4, "J6": 3, "J7": 4, "J8": 5, "J9": 4, "J10": 4, "J11": 4},
 "reasons": {"hook": "00:11 t02: prediction with a 7 s hold", "...": "...", "J11": "09:42 t66: chips show move counts"},
 "worst": ["seg03 t16 @ 02:23: ..."],
 "heldOut": {"demonstrated": false, "case": "t41: \"key 7 walks clockwise to B\"", "solution": "t43: \"only the arc behind D moves\"",
             "evidence": "the held-out case is a different input (robot jobs), solved by the same rule"}, "notes": [],
 "judgeReply": "<the judge's whole reply, verbatim>", "judgeReplySha256": "<sha256 of judgeReply>",
 "restate": {"score": 4, "summary": "<the restater's 5 sentences>", "gaps": ["virtual-node cost not shown"],
             "retrieval": {"answer": "<its answer>", "citations": ["[03:36]", "seg04-middle.png"]},
             "transfer": {"answer": "<its answer to the held-out case>", "citations": ["[05:10]"]},
             "reply": "<the restater's whole reply, verbatim>", "replySha256": "<sha256 of reply>"}}
```

`qc.py all --final` rejects a score that is not a finite number in its range (99, Infinity and NaN fail), a missing `round`, a score without a reason citing an mm:ss or a turn id, a cited turn that does not exist (`t999`) or a time outside the episode, an empty `worst` while a score fails, a held-out case the judge found demonstrated, a reply that is missing, does not match its sha256 or whose JSON block differs from the recorded fields, and a missing or low (below 4) restater result or one without its retrieval and transfer answers and citations. Independence: a record that the building agent persists cannot prove that an independent agent wrote it. The verbatim replies with their digests make an edited or invented record visible on review; they do not make it impossible. The learner's self-test stays the final measure (section 9). `qc/report.json` holds only the automated checks and is rewritten on every `qc.py` run.

Fix loop: take the 3 lowest-scoring problems, fix them at the cheapest layer (scenes.json before components, script before audio), re-render only if the fix needs it, re-run `learn.py` and `transcript.py --embed-chapters`, then `qc.py all`, and re-judge (a new build needs new scores). At most 3 rounds. If scores still fail, gate 3 shows the episode as a "FAILED DRAFT (diagnosis only)" with the open problems listed, never as ready for approval.

## 5. Independent judge protocol

The builder does not grade its own work (claude-motion-design section 9c). Start two agents with the Agent tool, each with a fresh context and its own brief: the restate agent FIRST, then the judge, because rubric line 2 ("Concept lands") is scored from the restater's reply (W16, W14b D21: judges started in parallel held line 2 as "provisional"). Store the restater's reply with `qc.py save-reply --kind restate` before you start the judge; the judge brief points at `qc/replies/restate.md`. Give each agent the path to its brief and nothing about how the video was built.

**Judge agent (read-only), `qc/judge-brief.md`.** It lists the mp4, the stills (from the delivered mp4) and contact sheets, `qc/report.md`, `qc/fidelity.json`, `qc/restate/spoken.md`, `script.json`, `facts.json`, `scenes.json`, `timing.json`, `learn/` and the two rubric files (this file, section 4, and `learning-design.md` section 10). Instructions: "Read only. Do not edit, render or run anything except ffprobe and ffmpeg frame extraction into qc/judge/. Score each rubric line 1 to 10 and each J1 to J11 1 to 5, each with a reason citing an mm:ss or a turn id. List the 3 worst problems with segment id, turn id and mm:ss. Check every number and negation against facts.json quotes, and every label against the scene (J11)." It must quote the turn that gives the plain explanation, the turn where the misconception visibly fails, the turn that repairs the model, and the transfer reasoning; a criterion with no quotable turn scores 2 or less. It cannot listen, so it scores audio (line 8) from numbers only (section 4) and names the fidelity-warn turns for the learner's listen. It writes no file: it ends its reply with one JSON block (section 4), and the parent agent writes `qc/scores.json`. Use a read-only agent type (Explore) when available, else general-purpose with that instruction.

**Restate agent (blind), `qc/restate-brief.md`.** It gets only the frames from the delivered mp4, the contact sheet and `qc/restate/spoken.md` (canonical spoken text with [mm:ss], regenerated from the current script and timing, so a stale transcript never reaches it). No facts.json, no outline, no learning goals, never the judge brief. Its task: explain the concept in 5 sentences, answer the restate question, solve a held-out new case, and cite a frame file or an [mm:ss] line for every claim (an uncited claim counts as not supported; a gap is written "not shown"). The restate question is the last `retrieve` pause prompt in the script (never the closing next-time question, which the episode leaves open on purpose), else `brief.learnerOutcome`. The held-out question is the ONE `learn.json` self-test item marked `heldOut: true`; `brief.heldout` checks that the video neither asks nor answers it, and the judge brief tells the judge to verify that the video does not demonstrate the case (`heldOut` in its JSON). It also scores itself 1 to 5 on how completely it could rebuild the mechanism, and ends its reply with one JSON block `{score, summary, gaps, retrieval: {answer, citations}, transfer: {answer, citations}}`; the parent stores the reply with `qc.py save-reply --kind restate`, then those fields as `restate` in `qc/scores.json` with the whole reply VERBATIM as stored (`restate.reply`, `restate.replySha256`). Compare its answers with `learningObjective`. If it misses the mechanism or answers wrong, rubric line 2 scores 5 or less and the episode fails, whatever the other scores; a restater score under 4 fails `judge.scores`. A video that cannot teach a fresh model is unlikely to teach the learner.

## 6. Gate 3: what the learner sees

Run `qc.py all --final` (chapters are already in the mp4 from step 12). Show its verdict ("READY FOR APPROVAL" or "FAILED DRAFT (diagnosis only)"), the mp4 path, the duration, the rubric scores, the restate agent's 5 sentences, the chapter list with `mm:ss` start times, and the turns with a fidelity warning to listen to. Then ask with AskUserQuestion (if it is unavailable, print the options as a numbered list and stop). The question also asks the learner what they heard: clicks at turn joins, voice drift, a misread word. Write their answer to `qc/listen.json` as `{"build": "<build.id>", "listener": "<name>", "problems": [], "note": "..."}` (one string per problem), then run `qc.py all --final` once more: `audio.listen` passes only with an empty `problems` list for this build.

1. "Ship it" (recommended only when the verdict is READY FOR APPROVAL and the learner heard no problem)
2. "Redo one segment" (ask which, and what to change)
3. "Change the look" (scenes only, no new audio)
4. "Start over from the outline"

## 7. Redo one segment

Audio, timing and scenes are keyed by turn id and anchored to turns or words, so a change to one segment re-runs only that segment's paid steps. Steps (exact flags in the SKILL.md Commands table):

1. Edit the segment's turns in `script.json` (the learner's edit, or yours from their note). Keep the other segments byte for byte. Keep ids of unchanged turns. A new turn gets the next free id.
2. Run `validate_script.py` with `--facts` and `--minutes`. A new number needs a fact first.
3. Run `tts.py` with `--segment <segId>`. Unchanged turns come from the audio cache and cost nothing. `episode.wav` and `timing.json` are rebuilt, so later turns shift by the length change. `tts.py` lists every turn whose audio changed (a retake of a turn whose text another turn shares is pinned to the selected turn, so the other keeps its take).
4. Run `align.mjs --only` with exactly the turns `tts.py` listed.
5. Run `build_manifest.py`. Anchors re-resolve to the new times. Do not hand-edit times.
6. Render, then run `qc.py all`. Fix every fail, including `audio.fidelity` for the new takes.
7. Rerun `learn.py`, then `transcript.py --embed-chapters`, because times moved (the gap log keeps the learner's rows and moves their times) and the new mp4 needs chapters.
8. Run `qc.py all` on that mp4. The judge re-scores the new build (changed segment and the 2 segments around it) and the restater runs again; the parent writes `qc/scores.json` with the new build id.
9. Run `qc.py all --final`. Add a learning-log entry (section 8).
10. Gate 3 again, with the segment's new `mm:ss` range so the learner can jump to it.

If the scenes for that segment change but the words do not, skip steps 2 to 4. A `--retake` of unchanged text changes the turn's `audioSha`, so its old words are dropped and step 4 is required.

## 8. Learning log

Each episode keeps `qc/learning.json`, a list of entries:

```json
{"date": "2026-11-02", "segment": "seg03", "turn": "t07",
 "issue": "resizing explained too fast",
 "rootCause": "one 37-word expert turn held three steps",
 "fix": "split t07 into two turns with a learner why-question between",
 "preventionRule": "one causal step per expert turn in mechanism segments",
 "verification": "validate_script.py PASS; judge pedagogy score 6 -> 9",
 "promote": false}
```

Promotion rule: when the same `preventionRule` shows up in 2 episodes, propose it to the learner as a new line in `references/script.md` or a new validator check. Do not edit the skill without their yes.

## 9. What QC cannot prove

Every check here is a proxy. In particular, `qc/scores.json` cannot prove that independent agents reviewed the build: the building agent writes it, and the VERBATIM replies only make a mismatch visible. The validator proves structure, `qc.py` proves the file and the audio match the plan, the judge scores evidence, and the restate agent shows a fresh model can rebuild the idea. None of that shows that the learner learned it. The final measure is the learner's own self-test score: after gate 3 they answer `learn/selftest.md` without the video, and their misses go into `learn/gaplog.md` (and the score into `qc/learning.json`). A run of passing QC with poor self-test scores means the rubric is wrong, not the learner.
