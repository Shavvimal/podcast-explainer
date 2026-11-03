---
name: podcast-explainer-video
description: Makes a two-host podcast-style explainer video that helps one learner understand a concept, then files it in a searchable library with self-test material. A learner host asks deep why and how questions and an expert host breaks a common misconception. The skill writes a sourced claim ledger, an outline and a validated dialogue script with pause-and-think holds, then makes per-turn Gemini TTS audio (gemini-3.8-flash-tts), word timing and a Remotion video with one persistent concept diagram, captions, a speaker highlight and pause cues. It checks the MP4 with qc.py and an independent judge, and writes a timestamped transcript, captions, chapters, flashcards and a self-test. Use it when the user asks for an explainer video, a podcast video, a two-host or dialogue explanation, "help me understand X" as a video, a deep dive in parts, a video from a document or URL, Remotion plus Gemini TTS work on such an episode, redoing one segment, or finding where a past episode explained something.
---

# Podcast explainer video

Turns a concept (a topic, a document or a URL) into a two-host explainer video for one learner, and leaves a transcript they can search and a `learn/` folder they can test themselves with. Audio is Gemini TTS, one call per turn. Video is Remotion, driven by the measured audio. Every step writes one JSON file in `explainers/<slug>/`, and a script checks it before the next costly step.

"The learner" is the person who asked for the video. They approve each gate, listen at gate 3 and take the self-test. The Learner host (Nia by default) is a persona in the script that stands in for them.

Set two shell variables once, as ABSOLUTE paths in double quotes (paths may contain spaces), and run every command exactly as written: each one starts with its own `cd`, so no command depends on where the previous one left the shell.

```bash
SKILL="/absolute/path/to/podcast-explainer-video"   # this skill's folder
PROJECT="/absolute/path/to/project"                  # the folder that holds explainers/
```

## Non-negotiables

1. **The key never shows.** Read `GEMINI_API_KEY` from the environment or, inside code only, from `~/.config/podcast-explainer/env`. Never `cat`, echo, print, log or write the key, its prefix or its length. `preflight.py` reports only "present" or "missing".
2. **Fail loudly.** A failed TTS turn stops the run with the turn id. Never ship silence, a skipped turn or a guessed duration. A script that exits non-zero stops the workflow until the cause is fixed.
3. **Human gates.** Stop at gate 1 (outline), gate 2 (look) and gate 3 (watch). No paid TTS before gate 1 and a validator PASS. No full Gemini run before gate 2. The free `--scratch` voice is allowed at any time.
4. **Every claim sourced.** Every number traces to `facts.json` with a verbatim quote, or to arithmetic on sourced facts, or carries an "Example data" label. Never state a number from memory.
5. **Searchable transcript always written.** Every finished episode gets `transcript.md`, captions, chapters, a library record and the `learn/` files, even when the learner skips gate 3 feedback.
6. **Measured audio is the clock.** Never type a duration, frame count or millisecond time by hand. Times come from `timing.json` through `build_manifest.py`.
7. **Understanding, not fluency.** Plain meaning before any term, a prediction pause in the cold open, one retrieval pause every 5 to 6 minutes, a misconception voiced and broken. A smooth video that only feels clear fails ([references/learning-design.md](references/learning-design.md)).
8. **Every spoken claim gets a visible state change** in one persistent concept world. Cards only for title, recap and check.
9. **The judge is not the builder.** A separate read-only agent scores the video from `qc/judge-brief.md`, and a fresh blind agent restates the concept from `qc/restate-brief.md` alone (delivered-mp4 frames and canonical spoken text, nothing else).
10. **Gemini `gemini-3.8-flash-tts`** on the Gemini Developer API. Fallback `gemini-3.8-flash-lite-tts`. Never the Cloud Text-to-Speech API. Never `gemini-3.1-flash-tts-preview` (shutdown listed for 17 Nov 2026).
11. **The learner's own self-test is the final measure.** Structure checks, the judge and the restater are proxies. After gate 3, the learner answers `learn/selftest.md`; record their score and misses in `learn/gaplog.md` or `qc/learning.json`.

## Depth and the intake questions

| Depth | Length | Segments | Pauses | Research | Use when |
|---|---|---|---|---|---|
| `quick` | about 6 min | 5 | 2 | 1 source is enough | "a quick one", one fact, 5 minutes or less |
| `standard` | about 12 min | 8 | 3 or 4 | 2 or more sources | no length named, one mechanism |
| `deep` | 20 to 35 min as 2 or 3 parts of at most 12 min | 10 to 16 | 5 or more | 5 or more sources, 3 per load-bearing claim | "in depth", "from first principles", "properly", two or more mechanisms |

Depth precedence: an explicit depth name in the request (quick, standard, deep) always wins over trigger words such as "in depth". With no depth and no length named, use the one default stated in [references/depth.md](references/depth.md) section 2 (`standard`, about 12 minutes).

Intake flow. Take everything the request already says. Then ask with one AskUserQuestion call, at most these, and only the ones the request leaves open:

1. **Depth** (quick / standard / deep), recommended option from the table above.
2. **Learner level** for this concept: `novice`, `familiar` (default) or `near-expert`. `near-expert` skips the plain pass (rule L7).
3. **Source**, only when the concept or the source is unclear: a document path, a URL, or "research it".

Then write the brief. Details: [references/depth.md](references/depth.md).

## Workflow

Copy this checklist into the first reply and tick it as you go. On multi-step work, start each reply with the state: "Step 5 of 15 done: script.json passes. Next: scenes."

```text
Episode <slug> progress
- [ ] 0  Preflight passes (key present, model listed, Remotion workspace installed); `--warm-whisper` reports whisper ready
- [ ] 1  brief.json: concept, source, learner, learnerLevel, depth, minutes; validated
- [ ] 2  facts.json digest: every number sourced (deep: research/ folder, 3 sources per load-bearing claim); validated
- [ ] 3  outline.json valid -> GATE 1 (the learner approves the outline)
- [ ] 4  script.json dialogue, segment by segment, with pause turns
- [ ] 5  validate_script.py PASS (max 3 minimal repairs)
- [ ] 6  scenes.json + 3 hero stills (placeholder timing) -> GATE 2 (the learner approves the look)
- [ ] 7  optional: tts.py --scratch timing draft; trim words if long
- [ ] 8  real audio: tts.py -> turn wavs, episode.wav, timing.json
- [ ] 9  align.mjs -> words[] and raw ASR; fidelity.py PASS (no unresolved fail)
- [ ] 10 build_manifest.py -> episode.json synced
- [ ] 11 render -> out/episode.mp4; qc.py all (diagnostic); fix every fail
- [ ] 12 learn.json + learn.py; transcript.py --embed-chapters (the mp4 is now final)
- [ ] 13 qc.py all on the final mp4 -> judge + blind restater -> parent writes qc/scores.json; fix loop, max 3 rounds
- [ ] 14 qc.py all --final (read-only check of the judged build) -> GATE 3 (the learner watches; listen note)
- [ ] 15 redo loop if asked: one segment only, then steps 5 and 8 to 14 for it
```

**Step 0, preflight.** Run `preflight.py --warm-whisper`. If the Remotion workspace is missing, run the fix it prints (copy `templates/remotion/` to `explainers/remotion/`, `npm install`, about 10 s), then run preflight again. `--warm-whisper` builds whisper.cpp and downloads its model into the cache `align.mjs` uses (about 30 s plus a 466 MB download the first time, under 1 s after that) and transcribes one second of silence to prove it runs, so step 9 never stalls on a build after the TTS money is spent. Do it before step 8; a `whisper ready` FAIL blocks paid audio until fixed. If the key is missing, tell the learner to export it in their shell; never ask them to paste it. Without a key, run up to step 7 with `--scratch`.

**Step 1, brief.** Write `explainers/<slug>/brief.json` (`schemas/brief.schema.json`) and validate it with `validate_script.py`. Add `lexicon` for names and terms whisper mishears, for example `{"Priya": ["pria", "prayer"], "softmax": ["soft max"]}`: fidelity then reads the alias as the name, but an alias can never be a number, sign, negation or direction word (E40), unless it is only the term split or joined ("soft max"). Defaults are in [references/script.md](references/script.md) section 5. Default hosts: Nia (learner, voice `Sulafat`) and Theo (expert, voice `Iapetus`), the learner's choice of 2 Nov 2026; other voices: [references/gemini-tts.md](references/gemini-tts.md) section 4. A deep run is a series: one folder per part, slugs `<series-id>-p1`, `-p2`, plus `explainers/<series-id>/series.json` ([references/depth.md](references/depth.md) section 5).

**Step 2, digest.** Write `facts.json`, the claim ledger ([references/script.md](references/script.md) section 6). From a document: quote it. From a topic or a URL: load the `firecrawl` skill, search and scrape (2 or 3 pages for quick, 5 to 10 for deep, [references/depth.md](references/depth.md) section 4). List misconceptions, analogies with where each breaks, and `openQuestions`. Validate it with `validate_script.py`.

**Step 3, outline, GATE 1.** Write `outline.json` with the outline prompt ([references/script.md](references/script.md) section 7) and the skeleton for the depth ([references/learning-design.md](references/learning-design.md) sections 5 to 7). Roles come from the single enum in `schemas/common.schema.json`. Validate it, then stop at gate 1.

**Step 4, dialogue.** Write `script.json` segment by segment with the dialogue prompt ([references/script.md](references/script.md) section 8). Plain words first, the term after. The cold-open question gets `holdAfterMs: 7000` and `pause: {kind: "predict", prompt}`; each retrieval question gets a `retrieve` pause.

**Step 5, validate.** Run `validate_script.py`. If it exits 1, make the smallest repair (section 11 of script.md) and run it again. After 3 failed repairs, show the learner the numbered problems and ask. Fix cheap warnings (W12, W14, W15, W23, W25). The `length:` line predicts the final audio (words x 0.357 s + holds + 250 ms gaps + 600 ms segment tails + lead); more than 15% over the target is E39 and blocks TTS, more than 8% is W39: cut words before paying for audio.

**Step 6, scenes, GATE 2.** Write `scenes.json` with [references/visuals.md](references/visuals.md) (schema in [references/manifest.md](references/manifest.md)). For a list-like concept, decide on the route recall pass with [references/memory-palace.md](references/memory-palace.md); its rule is "use narrowly": switch it on only when the concept has 4 to 9 discrete parts whose order the learner must recall. Build with `--placeholder-timing`, render three hero stills (hook, hardest mechanism moment, ending), then stop at gate 2.

**Step 7, scratch draft (optional).** `tts.py --scratch` gives a free timing draft with macOS `say`. The `say` voice runs faster than Gemini, so judge length by word count at 0.357 s per word, not by the scratch duration.

**Step 8, real audio.** Run `tts.py --dry-run` (turns, cost), then `tts.py` ([references/gemini-tts.md](references/gemini-tts.md)). A failed turn stops the run: fix that turn's text or retake it, never skip it. Holds are inserted silence, not billed, and not in the cache key.

**Steps 9 and 10, align and manifest.** Run `align.mjs`. It keeps each turn's raw ASR and runs `fidelity.py`, which compares what was heard with the script in both directions (substitutions, deletions, insertions; a differing number, sign or negation, or a swapped direction word such as increase/decrease, true/false, more/less, before/after, is critical). Exit 1 means a fidelity failure: retake that turn (`tts.py --only tNN --retake`, then `align.mjs` for every turn `tts.py` names as changed), or listen and, if the audio is right, paste the entry `fidelity.py` prints into `<slug>/fidelity-accept.json` and write your reason: it binds to the take's `audioSha` and to the turn's expected text, so a new take or an edited turn needs a new listen. Scratch, chunk, experimental and `--estimate-only` audio is a draft that never ships. Then run `build_manifest.py` (it writes `episode.json` with `holds[]` and syncs to `remotion/public/episodes/<slug>/`). Never edit `episode.json` or `timing.json` by hand: fix `scenes.json` or `script.json` and rebuild.

**Step 11, render and diagnostic QC.** Render ([references/remotion.md](references/remotion.md)), then run `qc.py all` ([references/qc.md](references/qc.md)). Stills come from the delivered mp4. Fix every `fail` before anything else. The briefs this run writes are not for judging yet: the mp4 has no chapters and `learn.json` may not exist.

**Step 12, learn and chapters: finish the deliverable.** Write `learn.json` from the script (self-test with exactly ONE transfer or apply question marked `"heldOut": true`, about a case the video never shows or answers, teach-back, cards, summary, gap log, each item citing a turn id, never a time; [references/learning-design.md](references/learning-design.md) section 8), then run `learn.py`. Then run `transcript.py --embed-chapters` ([references/library.md](references/library.md)): it writes the transcript, captions, library record and `delivery.json` (the sha256 of every transcript, caption, library and sidecar file) and puts the chapters into the mp4. From here the mp4 does not change unless a fix needs a new render. Both scripts record the digests of the `script.json`, `timing.json` and `learn.json` they were built from. `rg "a phrase from the episode" explainers/library` finds the episode at once. Indexed search (`cairn search`, `qmd`) finds it only after the library folder is in a QMD collection and `qmd update` has run; that is an optional completion step.

**Step 13, evidence, judge and restate.** Run `qc.py all` on the final mp4. It writes the stills, `qc/report.json` with the build identity, `qc/judge-brief.md` and `qc/restate-brief.md` (whose held-out question comes from `learn.json`). Run the blind restater FIRST with the restate brief, and store its reply as received (the text of its final message) with `qc.py save-reply --kind restate`; it records the sha256 at storage time. Then give the judge brief to a read-only judge agent: it scores rubric line 2 ("Concept lands") from the stored restater reply. Store the judge's reply with `qc.py save-reply --kind judge`. Neither agent writes files: each ends its reply with one JSON block. The parent agent (you) writes `qc/scores.json`: the judge's JSON fields (`build`, `round`, `scores`, `j`, `reasons`, `worst`, `heldOut`, `notes`), the judge's stored reply as `judgeReply` with `judgeReplySha256`, and `restate` = the restater's fields `{score, summary, gaps, retrieval: {answer, citations}, transfer: {answer, citations}}` plus its stored reply as `restate.reply` with `restate.replySha256`. `qc.py` compares the fields with the JSON block inside each reply, the digests with the stored replies, and checks that every cited turn, mm:ss and frame exists. Honest limit: the parent relays each reply, so byte-for-byte fidelity with the model's output cannot be proven, and a record the building agent persists cannot prove that an independent agent wrote it; the learner's own self-test stays the final measure. Fix the 3 worst problems until every rubric score is 8 or more, J1, J5, J7 and J11 reach 4, no J is below 3 and the restater scores 4 or 5 (at most 3 rounds). After each fix, rerun the steps it touches through step 12, then `qc.py all` and a new judge round: any change makes a new build.

**Build identity.** `build.id` in `qc/report.json` is a digest over `script.json`, `scenes.json`, `timing.json`, `episode.json`, `audio/episode.wav`, `facts.json`, `outline.json`, `learn.json`, the generated `learn/` files (not `gaplog.md`), `transcript.json`, `delivery.json`, the resolved glossary, the review fields of `brief.json` (viewing, depth, minutes, targetMinutes, learnerLevel, lexicon, learnerOutcome, coreMessage) with the held-out item, and the final mp4 (chapters included). Scores bind to it, so they must be made on the finished deliverable, never before step 12.

**Step 14, final QC, GATE 3.** Run `qc.py all --final`. It never changes the reviewed deliverable (mp4, transcript, captions, library copy, `learn/` files, `qc/scores.json`); it refreshes the QC outputs (report, briefs, stills from the same mp4) and checks the judged build. Its verdict is "READY FOR APPROVAL" only when every check passes: chapters in the mp4; every transcript, caption, library and sidecar file equal to its `delivery.json` digest and to what `transcript.py` renders now; `learn/` files built from the current script, timing and `learn.json` (digests); a designated held-out question the video does not already ask or answer; and a valid `qc/scores.json` for this build (finite scores in range, reasons citing real turns and times, both replies verbatim, the restater's answers with citations). Otherwise show the episode as "FAILED DRAFT (diagnosis only)". Show the mp4 path, duration, rubric scores, the restate agent's summary, chapters with mm:ss, the `learn/` paths, and the turns with a fidelity warning. The judge cannot listen: ask the learner, in the gate question, whether they heard clicks, voice drift or a misread word, and write their answer to `qc/listen.json` (`{build, listener, problems: [], note}`) before "Ship it"; `qc.py all --final` then checks it too.

**Step 15, redo loop.** Redo one segment with [references/qc.md](references/qc.md) section 7: edit its turns, validate, `tts.py --segment`, `align.mjs --only` for every turn `tts.py` reports as changed, rebuild, render, `qc.py all`, `learn.py`, `transcript.py --embed-chapters`, `qc.py all`, re-judge, then `qc.py all --final`. Do not regenerate other segments.

## Human gates

At each gate, show the evidence, then ask with AskUserQuestion. If AskUserQuestion is not available (a sub-agent or headless run), print the evidence and the options as a numbered list and stop. Put the recommended option first and mark it "(recommended)". One question per gate. Do not continue until the learner answers. Free text instead of an option is a change request: loop back to the step that owns it.

| Gate | After step | What the learner sees | Options (recommended first) |
|---|---|---|---|
| 1 Outline | 3 | A table: segment, role, title, key question, pauses, minutes. The misconception in one line. The learning objective. `openQuestions`. Cost and render time from depth.md. For deep: one table per part | Approve outline / Change segments (say which) / Change depth or length / Different misconception |
| 2 Look | 6 | The three hero stills (paths, read into the reply), the concept-angle sentence, host names and voices, route recall on or off | Approve look, make audio / Change the concept world / Change one still / Audition voices first (`tts.py --audition`) |
| 3 Watch | 14 | Verdict from `qc.py all --final` (READY FOR APPROVAL or FAILED DRAFT), mp4 path, duration, rubric and J scores, restate summary, chapters with mm:ss, `learn/` paths, turns to listen to | Ship it (record their listen note in `qc/listen.json` first) / Redo one segment / Change the look only / Back to the outline |

## Degrees of freedom

- **Low (run exactly):** preflight, validation, TTS, alignment, manifest, render, qc, transcript, learn, search. Use the scripts and flags below. Do not call the Gemini API by hand, do not join audio yourself, do not hand-edit `timing.json` or `episode.json`.
- **Medium (follow the template, adapt the content):** brief, facts, outline, dialogue, `learn.json`. The schemas and the validator are strict; the wording, examples and analogies are yours.
- **High (design):** the concept world, scene choreography and custom scene components. Use the patterns in [references/visuals.md](references/visuals.md) and judge by the rubric.

## Commands

| Step | Command |
|---|---|
| 0 | `cd "$PROJECT" && python3 "$SKILL/scripts/preflight.py" --workspace explainers --warm-whisper` (`--scratch` for a key-free run, `--offline`, `--json`, `--whisper-cache-dir`). Its fixes print absolute, quoted paths: run them as printed. Alone: `cd "$PROJECT/explainers/remotion" && node "$SKILL/scripts/align.mjs" --warm --workspace ..` |
| 1-3 | `cd "$PROJECT" && python3 "$SKILL/scripts/validate_script.py" explainers/<slug>/brief.json`; the same for `facts.json`; `... outline.json --facts explainers/<slug>/facts.json`; deep series: `... explainers/<series-id>/series.json` |
| 5 | `cd "$PROJECT" && python3 "$SKILL/scripts/validate_script.py" explainers/<slug>/script.json --facts explainers/<slug>/facts.json --minutes <m>` (`--brief`, default the sibling brief.json; `--json`, `--max-turn-words 45`, `--kind`). Always prints a word-budget line and a predicted-length line (E39/W39) |
| 6 | `cd "$PROJECT" && python3 "$SKILL/scripts/build_manifest.py" --workspace explainers --slug <slug> --placeholder-timing`, then `cd "$PROJECT/explainers/remotion" && npx remotion still Episode ../<slug>/qc/hero-<name>.png --props='{"slug":"<slug>"}' --frame=<n>` |
| 7 | `cd "$PROJECT" && python3 "$SKILL/scripts/tts.py" explainers/<slug> --scratch` |
| 8 | `cd "$PROJECT" && python3 "$SKILL/scripts/tts.py" explainers/<slug> --dry-run` (prints the predicted final length; exits 1 on a length error), then without it (it refuses the same error unless `--allow-over-length "<reason>"`). Redo: `--only t07,t08`, `--segment seg03`, `--retake`. Other: `--audition Sulafat,Iapetus`, `--model gemini-3.8-flash-lite-tts`, `--lufs -19` and `--true-peak -4.5` (defaults, from `pe_common.py`), `--gap-ms 250`, `--tail-pad-ms 600`, `--workers 4`. Experimental, not for delivery: `--mode chunk --experimental` |
| 9 | `cd "$PROJECT/explainers/remotion" && node "$SKILL/scripts/align.mjs" <slug> --workspace ..` (`--only t07,t08`, `--show-asr t07`, `--estimate-only` draft, `--model small.en`, `--help`); it runs `fidelity.py --workspace .. --slug <slug>` itself. Alone: `cd "$PROJECT" && python3 "$SKILL/scripts/fidelity.py" --workspace explainers --slug <slug>` (`--json`). Step 0's `--warm-whisper` has already built whisper.cpp and downloaded its model; without it, the first run does that here (needs build tools and network) |
| 10 | `cd "$PROJECT" && python3 "$SKILL/scripts/build_manifest.py" --workspace explainers --slug <slug>` (`--auto-chips`, `--tail-ms`, `--no-sync`, `--remotion-dir`) |
| 11 | `cd "$PROJECT/explainers/remotion" && npx remotion render Episode ../<slug>/out/episode.mp4 --props='{"slug":"<slug>"}' --codec=h264 --crf=18 --image-format=jpeg --concurrency=16` |
| 11 | `cd "$PROJECT" && python3 "$SKILL/scripts/qc.py" all --workspace explainers --slug <slug>` (`probe`, `stills`, `captions`, `coverage`, `audio` run one part; `--mp4`, `--remotion-dir`, `--from-remotion` source preview, `--skip-stills`, `--json`) |
| 12 | `cd "$PROJECT" && python3 "$SKILL/scripts/learn.py" --workspace explainers --slug <slug>` (`--json`), then `cd "$PROJECT" && python3 "$SKILL/scripts/transcript.py" --workspace explainers --slug <slug> --embed-chapters --tags a,b` (`--mp4`, `--date`); deep series part: add `--series <series-id> --part <N> --depth deep` |
| 13 | `cd "$PROJECT" && python3 "$SKILL/scripts/qc.py" all --workspace explainers --slug <slug>` on the final mp4, then the restater, then the judge; store each reply: `cd "$PROJECT" && python3 "$SKILL/scripts/qc.py" save-reply --workspace explainers --slug <slug> --kind restate\|judge --file <reply.md>` (or stdin) |
| 14 | `cd "$PROJECT" && python3 "$SKILL/scripts/qc.py" all --workspace explainers --slug <slug> --final`; deep series: `cd "$PROJECT" && python3 "$SKILL/scripts/validate_script.py" explainers/<series-id>/series.json --final` |
| search | `cd "$PROJECT" && python3 "$SKILL/scripts/search.py" "query" --library explainers/library` (`--list`, `--open --hit N --dry-run`, `--slug`, `--tag`, `--engine auto\|rg\|bm25`, `--limit`, `--json`) |
| export | `cd "$PROJECT" && python3 "$SKILL/scripts/export_delivery.py" --workspace explainers --slug <slug> --to "<DIR>"` (`--force`, `--allow-broken-links`, `--json`): the complete delivery as a portable folder with relative links and `export.json` digests ([references/library.md](references/library.md) section 14). Deep series: `--series explainers/<series-id>/series.json` exports every part, the series folder and an `index.md` |

Every script prints its full usage with `--help`. Requirements: Python 3.10 or later (checked under 3.10 and 3.11) (standard library; `jsonschema` used when importable), Node 20 or later, ffmpeg and ffprobe, macOS `say` for scratch audio. `align.mjs` must run from `explainers/remotion` (the step 9 command does the `cd`), because it loads `@remotion/install-whisper-cpp` from there.

Remotion rules come from the official skills: `npx skills add remotion-dev/skills` (https://github.com/remotion-dev/skills), then load `remotion-best-practices` before writing any Remotion code. Ignore its ElevenLabs voiceover default; this skill uses Gemini. Remotion is free for individuals and companies of up to 3 people; check the licence before any company use ([references/remotion.md](references/remotion.md) section 9).

## Find something in a past episode

Search with `rg "the phrase" explainers/library` (works at once), or `cairn search` once the library is in a QMD collection and `qmd update` has run. The optional `search.py "the phrase"` also gives a deep link. A `search.py` hit gives the episode, chapter, `[mm:ss]`, speaker, a snippet and `file:///.../episode.mp4#t=SECONDS`. Hits come from transcript turns, chapter goals, glossary entries, pause prompts, self-test questions and flashcards. Cite a moment as `[<slug> mm:ss]`. `rg`, `qmd` and `cairn` read the same markdown ([references/library.md](references/library.md)).

## File map

| Path | What it holds | Read when |
|---|---|---|
| [references/script.md](references/script.md) | Personas, pedagogy rules, role table, brief and facts, outline and dialogue prompts, TTS text rules, validator codes, repair loop | Steps 1 to 5 |
| [references/learning-design.md](references/learning-design.md) | Rules L1 to L16, moves M1 to M9, segment skeletons per depth, `learn/` artefacts, judge rubric J1 to J11 | Steps 3, 4, 12, 13 |
| [references/depth.md](references/depth.md) | Depth ladder, picking a depth, research for deep, series split, rungs | Step 1 and any episode longer than quick |
| [references/gemini-tts.md](references/gemini-tts.md) | Models, request shape, voices, limits, cost, holds, loudness, retries, troubleshooting | Steps 7, 8 |
| [references/manifest.md](references/manifest.md) | timing.json, scenes.json, episode.json (with `holds[]`), anchor rules | Steps 6, 9, 10 |
| [references/remotion.md](references/remotion.md) | Project layout, composition, captions, pause cue, safe areas, stills, render, licence | Steps 0, 6, 11 |
| [references/visuals.md](references/visuals.md) | Concept world, claim-to-visual rule, scene types, custom scenes | Step 6 |
| [references/memory-palace.md](references/memory-palace.md) | Route recall pass for list-like concepts; decision rule "use narrowly" | Step 6, only for 4 to 9 ordered parts |
| [references/qc.md](references/qc.md) | qc.py checks, build identity, stills, rubric, judge protocol, gate 3, redo loop, learning log | Steps 11, 13, 14, 15 |
| [references/library.md](references/library.md) | Transcript, captions, chapters, library index, `learn/` registration, search, citations | Step 13 and any search |
| `schemas/` | JSON Schemas: brief, facts, outline, script, common (role enum, pause), scenes, timing, episode, learn, library-index, series | When a validator error names a field |
| `scripts/` | preflight, validate_script, tts, align, fidelity, build_manifest, qc, transcript, learn, search, plus `pe_common.py` (shared helpers). Run them; read one only when it fails | Each step |
| `templates/remotion/` | The Remotion project, copied once per workspace | Step 0 |
| `evals/` | Three scenarios plus sample script, facts, scenes and learn files for the hash-map episode | When testing the skill |

## When things go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `preflight.py` says key missing | Key not in env or the env file | The learner exports it in their shell; meanwhile run with `--scratch` |
| `validate_script.py` E08 number has no fact | A number not in `facts.json` | Add a sourced fact or cut the number; never invent one |
| E22, or W23 "min since the last pause" | Pause without `holdAfterMs`, or 6 minutes without a pause | Set `holdAfterMs` 7000 on a question turn and add `pause {kind, prompt}` |
| `tts.py` stops on a turn (truncation, `finishReason OTHER`) | Gemini take failed 3 times | Rephrase or split that turn, then `--only <id>`; see gemini-tts.md section 12 |
| `turn tNN has no cached take` | `--only` run while another turn changed | Add that turn to `--only`, or run without it |
| `align.mjs` "not installed" | Run from the wrong folder | `cd explainers/remotion` first |
| preflight `whisper ready` WARN or FAIL | whisper.cpp not built, model not downloaded, or no `make`/compiler | Run `preflight.py --warm-whisper` before any paid TTS; on FAIL install the Xcode command-line tools (`xcode-select --install`) and run it again |
| `build_manifest.py` overlap or missing word | Scene anchors out of order, or a word not in the turn | Fix `scenes.json`; the error quotes the turn text |
| `build_manifest.py` holdAfterMs differs | Hold changed after the last `tts.py` | Rerun `tts.py` (costs nothing for a hold change), then `align.mjs` is not needed |
| `qc.py` probe.loudness fail at about -13 LUFS | wav normalised to -16 instead of -19 | Rerun `tts.py` with the default `--lufs -19`, rebuild, render |
| `qc.py` probe.truepeak fail | Remotion's encode raises the true peak 1.6 to 2.3 dB | Rerun `tts.py` with a lower `--true-peak` (the hint names a value below the default -4.5), free for cached turns, then rebuild and render |
| `fidelity.py` or `audio.fidelity` FAIL | The audio differs from the script (a number, sign, negation, direction word, or many words) | `--show-asr tNN`; retake the turn, or listen and paste the `{turn, audioSha, text, reason}` entry `fidelity.py` prints into `fidelity-accept.json` |
| `audio.fidelity` DRAFT | Scratch, chunk or experimental audio, or estimated alignment | Per-turn Gemini takes (`tts.py` without `--scratch` or `--mode chunk`), then `align.mjs` without `--estimate-only` |
| `tts.py` "pinned to tNN only" | `--retake` of one of several turns with identical text | Expected: the other turns keep their take. Realign the turns `tts.py` lists as changed |
| `build.fresh` fail | mp4 older than `episode.json`, or Remotion's copy differs | Rerun `build_manifest.py`, render again, then `qc.py all` |
| `judge.scores` fail | Scores missing, out of range, without reasons or restater result, below the bar, or for another build | Re-judge the final build (after step 12); write the judge's JSON plus `restate` into `qc/scores.json` |
| `final.artefacts` fail "built from another" | transcript or `learn/` made before the last script, timing or `learn.json` change | Rerun `learn.py` and `transcript.py --embed-chapters`, then `qc.py all` and re-judge |
| `brief.heldout` warn or fail | No selfTest item has `"heldOut": true` or more than one has (fail), its question is already spoken or shown (50% overlap: fail), or its answer's words are (warn: evidence for the judge, who decides with `heldOut.demonstrated` and quotes the closest case and solution) | Mark ONE transfer or apply question about a case the video never works; run step 12 again, then `qc.py all` |
| `validate_script.py` E39 or W39 | Predicted length more than 15% (8%) over the target, or a series part predicted over 684 s (12 min minus 5% headroom) | Cut words or holds, or move a segment to the next part, before any paid TTS. `tts.py --dry-run` exits 1 on the same error and the paid run refuses it unless `--allow-over-length "<reason>"` (recorded in `timing.json`) |
| `validate_script.py` E45, E46, E47 | The mechanism uses no domain terms, works an example whose numbers or names are in neither facts.json nor the outline, or the misconception segment never names the outline's wrong belief | Name this concept's parts in the causal step, work the planned case, voice the outline's misconception in its own key words |
| `learn.py` refuses learn.json | Not exactly 5 self-test items (`brief.json` `selfTestCount` overrides), no apply or transfer item, 2 or more remember items, or an analogy segment without its "Where does the ... analogy break?" card | Fix learn.json to the spec in references/learning-design.md section 8 |
| `labels.early` warn (fail under `--final`) | A chip, stat, note, banner or `set` label shows a number before the hosts say it (the detail names both turns and the lead) | Anchor the step to the word that speaks the number, never to a summary turn before it; if the picture is meant to lead, add `earlyOk: "<reason>"` to that step, banner or chip ([references/qc.md](references/qc.md)) |
| `world.nodefit` fail | A node's label, sublabel and value need more height than its explicit `h` | Drop the `h` (pills and boxes grow for a value line), or show the value in another node |
| `build_manifest.py` matrix "text must be at least 28 px" | Too many rows or columns, or headers and cells too long, for the stage | Cut to the column count the message names, shorten headers or cells to 12 characters or fewer, or drop the title |
| `fidelity.py` FAIL in a headless run | Nobody can listen to the take | Retake once (`--retake`); if it fails again, rewrite the turn plainly and retake. Never write an accept entry without a listen |
| `labels.stale` fail | A quantity label (a number, per, each) stays on screen after a world step reveals or hides what it counts | `set` the new value in that step, hide the label, or mark it `persist: true` when it stays true |
| `labels.counts` unchecked | Ambiguous wording or a partly filled table | Write the claim exactly ("2 of 4 move to D"); the judge checks the rest |
| `final.artefacts` "changed after transcript.py" or "differs from what transcript.py renders" | A transcript, caption, library or sidecar file was edited by hand or is stale | Rerun `transcript.py --embed-chapters`, then `qc.py all` and re-judge |
| `judge.scores` "does not exist" or "verbatim" | A reason cites a turn or time not in the episode, or the record differs from the reviewer's reply | Store each reply verbatim with its sha256 and copy the fields from its JSON block; re-judge |
| `qc.py` captions.rate warn above 21 cps | Very fast speech or scratch voice | Split the turn, or lower `captions.maxCharsPerSecond`; ignore on scratch audio |
| `qc.py` coverage miss | `onScreen` term or number with no visual | Add a chip or node label, or `build_manifest.py --auto-chips` |
| Restate agent misses the mechanism | The video does not teach | Back to the outline for the failing segment; do not ship |
| `learn.py` unknown turn | `learn.json` cites a turn that changed id | Fix the turn id in `learn.json`; rerun |
| `search.py` exit 2 | No hits, or library path wrong | Pass `--library explainers/library`; run `transcript.py` and `learn.py` first |
