# Library: transcripts, captions, chapters and search

Every finished episode becomes searchable text. `scripts/transcript.py` writes the transcript files. `scripts/learn.py` writes the learner's after-video work (`learn/`). `scripts/search.py` finds a moment, a self-test question or a card and links to it in the video. The library is plain markdown, so `grep`, `rg`, `qmd` and `cairn` read it with no extra tool.

## Contents

1. What gets written, and where
2. Run it
3. transcript.md format (with an example)
4. transcript.json
5. captions.vtt and captions.srt
6. chapters.ffmetadata and chapter markers in the mp4
7. library/index.json
8. Naming rules
9. Search
10. Cite a timestamp
11. Index with qmd and cairn
12. Regenerate after a redo
13. Learning artefacts: learn.json, learn.py and learn/
14. Export a portable delivery

## 1. What gets written, and where

```
explainers/
  <slug>/
    transcript.md          front matter + chapters + glossary + sources
    transcript.json        same data, word level when timing.json has words[]
    captions.vtt           speaker-prefixed cues, at most 2 lines of 42 characters
    captions.srt           same cues, SRT format
    chapters.ffmetadata    one [CHAPTER] per segment, for ffmpeg
    glossary.json          optional input: {"terms": [{"term", "definition"}]}
    out/episode.mp4        chapters embedded with --embed-chapters
    out/episode.srt        sidecar copy of captions.srt (VLC, IINA and mpv load it by name)
    out/episode.vtt        sidecar copy of captions.vtt
    out/transcript.md      copy of transcript.md beside the video, so sharing out/ shares both
    learn.json             input for learn.py, written by the agent (schemas/learn.schema.json)
    learn/                 selftest.md, teachback.md, cards.csv, cards.md, summary.md, gaplog.md
  library/
    <slug>.md              copy of <slug>/transcript.md
    learn/<slug>/          copies of the six learn/ files (written by learn.py)
    index.json             one record per episode (schemas/library-index.schema.json)
```

Inputs: `script.json` and `timing.json` are required. `facts.json` (Sources section), `outline.json` (chapter titles, `newTerms`), `brief.json` (concept), `glossary.json` (definitions) and `learn.json` (definitions from `summary.terms`, the Check yourself chapter) are optional. If a turn in `timing.json` has `words[]`, captions use word times. If not, the script spreads the turn's time over its words by character count.

## 2. Run it

Run after the render and `qc.py all` (SKILL.md step 12), before the judge, and again after every redo. Add `--embed-chapters` at step 12 itself, so the mp4 the judge scores already has its chapters (SKILL.md step 12; qc.md section 1). For a deep series part, add `--series <series-id> --part <N> --depth deep`:

```bash
python3 scripts/transcript.py --workspace explainers --slug hash-maps --tags data-structures,python
python3 scripts/transcript.py --workspace explainers --slug hash-maps --embed-chapters
```

| Flag | Meaning |
|---|---|
| `--workspace DIR` | Workspace folder. Default `./explainers`. |
| `--slug X` | Episode folder name. Required. Validated (lowercase letters, digits, single hyphens) and must resolve inside the workspace. |
| `--mp4 PATH` | Video path. Default `<slug>/out/episode.mp4` when it exists. Recorded as an absolute path. |
| `--embed-chapters` | Writes chapter markers into the mp4 with stream copy (no re-encode), to a temporary file that then replaces the mp4. Needs ffmpeg. |
| `--tags a,b` | Tags, lowercase. Kept from the index on later runs unless the flag replaces them. |
| `--depth quick\|standard\|deep` | Default: kept from the index, else inferred from the duration (under 9 minutes quick, up to 16 standard, else deep). |
| `--series ID --part N` | Marks one part of a deep series (see `depth.md`). |
| `--date YYYY-MM-DD` | Episode date. Default: kept from the index, else today. |

The script fails loudly and names the turn when `script.json` and `timing.json` disagree: a script turn with no timing, or a timing turn that the script does not have. Rerun `tts.py` for that segment, then rerun `transcript.py`. A rerun with the same inputs writes byte-identical files and prints `unchanged`.

## 3. transcript.md format

Rules: YAML front matter, then one `#` title, then fixed `##` headings. One paragraph per line, never hard-wrapped. Every front matter value is JSON, which is valid YAML, so a plain JSON parser reads each line. Every turn is one line that starts with `**[mm:ss] Name:**`. Minutes do not wrap into hours (`[72:05]` is valid). Chapter headings are `## [mm:ss] Chapter N: Title`. A `## Check yourself` heading follows the last chapter when the script has holds or `learn.json` exists. The last two headings are always `## Glossary` and `## Sources`.

```markdown
---
title: "Why the hash ring stops the reshuffle"
slug: "consistent-hashing"
concept: "Why adding a cache server moves only about 1/N of keys on a hash ring"
tags: ["distributed-systems", "caching"]
date: "2026-11-02"
durationSec: 75
depth: "quick"
speakers: ["Nia (learner)", "Theo (expert)"]
sources: ["https://dl.acm.org/doi/10.1145/258533.258660"]
glossary: ["hash ring", "mod N", "virtual nodes"]
chapters: 4
timing: "mixed"
mp4: "/path/to/project/explainers/consistent-hashing/out/episode.mp4"
---

# Why the hash ring stops the reshuffle

Concept: Why adding a cache server moves only about 1/N of keys on a hash ring

Episode: consistent-hashing. Length 01:15. Depth quick. Hosts: Nia (learner), Theo (expert).

Video: file:///path/to/project/explainers/consistent-hashing/out/episode.mp4

## Contents

- [00:00] Chapter 1: The reshuffle puzzle
- [00:20] Chapter 2: The ring

## [00:00] Chapter 1: The reshuffle puzzle

Goal: See why mod N moves most keys

**[00:00] Nia:** I add one cache server and suddenly almost every key misses. Why would one extra box break everything?

**[00:07] Theo:** Because the rule you use is key hash mod N. Change N and nearly every remainder changes.

## [00:20] Chapter 2: The ring

**[00:20] Theo:** Put the servers on a circle of hash values. Each key walks clockwise to the next server.

## Glossary

- **hash ring** [00:20]
- **virtual nodes** [00:57]: many ring points per server, so arcs even out

## Sources

- s1: Karger et al. 1997, Consistent hashing and random trees. https://dl.acm.org/doi/10.1145/258533.258660. Retrieved 2026-11-02. Facts used: f1, f2.
```

Other details:

- `timing` is `word` (every turn has `words[]`), `mixed`, or `turn`.
- A `series` line (`{"id": "...", "part": 2, "of": 3}`) appears only for a part of a deep series. Scripts and outlines say `series.parts`; `transcript.py` maps it to `of`.
- Turn text is the canonical spoken text (the same function `tts.py`, `align.mjs` and `build_manifest.py` use): Gemini `<tags>` and `|backchannels|` are dropped. Per-turn audio never speaks a backchannel, so it never reaches the transcript. In the experimental chunk mode a backchannel belongs to the other host: `transcript.json` lists it under the turn's `backchannels` with that host's name, and the markdown shows it after the turn as `_(Theo: oh)_`.
- The Glossary takes terms from `glossary.json`, then `script.json` or `outline.json` `glossary` if present, then outline `newTerms`, then `learn.json` `summary.terms`. Each definition comes from the entry, else from `glossary.json`, else from `learn.json` `summary.terms` (term to meaning). On-screen labels ("9 of 12", "mod 3") are never glossary terms. The `[mm:ss]` is the first turn that shows or says the term.
- The Sources section lists every source in `facts.json` and the fact ids that the script cites from it.
- Scratch audio (`timing.json` `scratch: true`) adds a note that the times change after the Gemini pass.
- A turn with `holdAfterMs` in `script.json` (or `timing.json`) ends with `[hold 7 s]`.
- Front matter adds `learningGoal` (script `learningObjective`), `misconceptions` (from `learn.json` and `facts.json`) and `learn: "learn/"` when `learn.json` exists.
- `## Check yourself` lists each pause as `- [mm:ss] Pause (predict, 7 s): <prompt>` (the time is the end of the turn, where the hold starts), then the self-test questions from `learn.json` without answers, each with `Answer explained at [mm:ss]`. A search for a question then lands on the moment that answers it.

## 4. transcript.json

The same data as the markdown, for programs. Top level: `slug`, `title`, `concept`, `tags`, `date`, `depth`, `series`, `durationMs`, `durationSec`, `wordLevel`, `model`, `scratchAudio`, `mp4`, `speakers[]`, `learningGoal`, `misconceptions[]`, `learnDir`, `holds[]` (`turnId`, `atMs`, `holdMs`, `kind`, `prompt`), `selfTest[]` (`question`, `level`, `turnId`, `answerMs`), `chapters[]`, `glossary[]`, `sources[]`, `captions`. A turn also carries `holdAfterMs` and `pause` when the script sets them. Each chapter has `id`, `index`, `title`, `role`, `learningGoal`, `keyQuestion`, `startMs`, `endMs` and `turns[]`. Each turn has `id`, `speaker`, `speakerName`, `startMs`, `endMs`, `text`, `onScreen`, `factIds`, and `words[]` (`text`, `startMs`, `endMs`, `source`) when alignment ran. Each glossary entry has `term`, `definition`, `firstMs` and `turnId`. All times are integer milliseconds from the start of `audio/episode.wav`.

`provenance` holds the sha256 digests of the `script.json`, `timing.json` and `learn.json` (null when absent) this transcript was built from. `learn.py` writes the same digests to `learn/provenance.json` `sources`, plus `files`: the digest of each generated `learn/` file (not `gaplog.md`). `qc.py all --final` compares them with the current files, so a transcript or `learn/` file from an older script or timing, or a hand-edited one, fails `final.artefacts` even when its times still match. `transcript.py` also writes `<slug>/delivery.json` (N06, 3 Nov 2026): the sha256 of every delivered or searchable derivative as written (transcript.md, transcript.json, captions.vtt, captions.srt, chapters.ffmetadata, `library/<slug>.md`, and the `.srt`, `.vtt` and `transcript.md` sidecars beside the mp4), keyed by name with the path relative to the workspace, plus the source digests. `qc.py all --final` fails `final.artefacts` when one is missing, differs from its recorded digest, or differs from what `transcript.py` renders now from the current inputs (so a hand edit of a file together with `delivery.json` is still caught). `delivery.json` is part of the build identity. Never edit these files by hand: rerun `transcript.py`.

## 5. captions.vtt and captions.srt

- Each cue starts with the speaker name: `Nia: ...`. Plain prefix, not a VTT `<v>` voice span, because players show voice spans in different ways.
- At most 2 lines per cue and 42 characters per line, the prefix included. A cue never crosses a turn boundary. A cue lasts at most 7 seconds and at least 0.7 seconds when the next cue leaves room. A cue breaks early at the end of a sentence once it fills one line.
- With `words[]`, cue times come from the words. If the word count equals the script word count, the cue text keeps the script spelling and punctuation. Otherwise it uses the aligned word text.
- These files are the sidecar captions (pedagogy rule V5c). The video itself shows only short key-term labels on diagrams.

## 6. chapters.ffmetadata and chapter markers in the mp4

One chapter per segment, `TIMEBASE=1/1000`. Chapter 1 starts at 0 so the chapters cover the whole file. Each later chapter starts at its first turn. The last chapter ends at `durationMs`. Titles are `N. Title`.

`--embed-chapters` runs:

```bash
ffmpeg -i out/episode.mp4 -f ffmetadata -i chapters.ffmetadata -map 0:v -map 0:a? -map_metadata 1 -map_chapters 1 -c copy -movflags +faststart out/episode.chapters.tmp.mp4
```

Then it replaces `episode.mp4` with the temporary file. It maps only video and audio, because the MP4 muxer stores chapters as a data track and copying the old track would add one more on every run. Check with `ffprobe -v error -show_chapters -of compact out/episode.mp4`. QuickTime, IINA, VLC and mpv show the chapters.

## 7. library/index.json

Schema: `schemas/library-index.schema.json`. One record per slug, sorted by slug. `transcript.py` replaces the record for its slug and leaves the others alone. The file has no "last updated" stamp, so reruns do not change it.

```json
{ "version": 1, "episodes": [
  { "slug": "consistent-hashing", "title": "Why the hash ring stops the reshuffle",
    "concept": "...", "tags": ["distributed-systems", "caching"], "date": "2026-11-02",
    "depth": "quick", "series": null, "durationSec": 75, "speakers": ["Nia", "Theo"],
    "chapters": [ {"id": "seg01", "index": 1, "title": "The reshuffle puzzle", "startMs": 0, "startSec": 0, "at": "00:00"} ],
    "glossary": ["hash ring", "mod N", "virtual nodes"],
    "mp4": "/abs/path/explainers/consistent-hashing/out/episode.mp4",
    "transcript": "/abs/path/explainers/consistent-hashing/transcript.md",
    "libraryFile": "consistent-hashing.md" } ] }
```

Paths are absolute so that a deep link works from anywhere. If the workspace moves, rerun `transcript.py` and `learn.py` for each slug. `transcript.py` binds this episode's record (not the whole index, and without `openGaps`, which follows the learner's gap log) into `<slug>/delivery.json` `record.sha256`; `qc.py --final` recomputes the record from the current inputs, compares it with the stored one and with that digest, and checks every `library/learn/<slug>/` copy against the canonical `<slug>/learn/` file (W13a, Q04). After the learner edits `gaplog.md`, rerun `learn.py` so the searchable copy follows.

`learn.py` adds six optional fields to the slug's record, after the fields above and in this order: `learningGoal`, `misconceptions[]`, `learn` (absolute paths `dir`, `selfTest`, `teachBack`, `cards`, `summary`, `gapLog`, plus `libraryDir` relative to the library), `selfTest[]` (`question`, `level`, `answer`, `segment`, `turn`, `t`), `cards[]` (`front`, `back`, `turn`, `t`) and `openGaps` (open rows in `gaplog.md`). Both scripts compute these fields with one function (`learn.compute_fields`): `learn.py` writes them when the record exists, and `transcript.py` writes them when `learn/` exists. So either order gives the same record, and no second run is needed.

Time units in the index: fields ending in `Ms` are integer milliseconds; `durationSec`, `startSec` and the `t` of `selfTest[]` and `cards[]` are integer SECONDS (floored) for display and `#t=` deep links; `at` is an `mm:ss` label. These are the only exceptions to the millisecond rule.

## 8. Naming rules

- Slug: lowercase letters, digits and single hyphens, at most 60 characters, the same as the episode folder and `script.json` `id`. Name the concept, not the format: `consistent-hashing`, not `video-3`.
- Series parts: `<series-id>-p<N>`, for example `transformers-p2`.
- Tags: lowercase, hyphens for spaces (`distributed-systems`). Use a broad field tag (`ml`, `systems`, `maths`, `business`) plus 1 to 3 topic tags. Reuse existing tags: run `search.py --list` first.
- Do not rename a slug after the first run. If you must, delete `library/<old>.md` and the old record in `index.json`, then rerun.

## 9. Search

```bash
python3 scripts/search.py "virtual nodes" --library explainers/library
python3 scripts/search.py "why does the ring help" --limit 5 --json
python3 scripts/search.py "load factor" --tag data-structures
python3 scripts/search.py "small arcs" --open            # open hit 1 in a player at its time
python3 scripts/search.py --list                          # every episode with its chapters
```

How it ranks: if `rg` (ripgrep) is on the PATH, exact-phrase hits (case-insensitive) come first. BM25 hits over the chunks follow, with boosts for query words in the episode title, the tags and the glossary. Without `rg`, BM25 runs alone (`--engine bm25` forces it). A query that equals a tag returns that episode at `[00:00]`. Chunks are turns, chapter goal lines, glossary entries, pause prompts from `## Check yourself` (kind `pause`), self-test items from `library/learn/<slug>/selftest.md` (kind `self-test`, question plus answer) and cards from `library/learn/<slug>/cards.md` (kind `card`, front plus back). A self-test or card hit carries the `[mm:ss]` of the turn that explains it, so its deep link jumps to the explanation. `--slug` and `--tag` filter episodes. The default library is `$EXPLAINERS_LIBRARY`, else `./explainers/library`. Exit code 2 means no hits.

Each hit prints the episode title and slug, the chapter, the `[mm:ss]` time, the speaker, a snippet with the match marked (bold in a terminal, `**...**` in a pipe), the deep link `file:///.../episode.mp4#t=SECONDS`, a citation tag, and the transcript line (`/abs/library/<slug>.md:LINE`).

`--open` limits on macOS:

- A plain `open file:///...mp4#t=83` hands the file to QuickTime, which ignores the time. So `search.py` picks a player that can seek: mpv (`--start`), then IINA (`iina-cli --mpv-start`), then VLC (`--start-time`), then Google Chrome or Safari with the `#t=` media fragment. If none is found, it opens the file at 0:00 and says so.
- The deep link rounds down to the whole second, so playback starts up to 1 second early.
- `--hit N` opens hit N instead of hit 1. `--dry-run` prints the player command and opens nothing.

Plain tools work too: `rg -n "virtual nodes" explainers/library` gives the line, and the line itself holds the `[mm:ss]`.

## 10. Cite a timestamp

Cite a moment as `[<slug> mm:ss]`, for example `[consistent-hashing 00:57]`. `search.py` prints this tag for each hit. To turn a citation into a link, take `mp4` from `index.json` and add `#t=<seconds>`: `00:57` becomes `#t=57`. In notes, write the citation and the link together, so the note still makes sense when the video is offline:

```markdown
Virtual nodes even out the arcs [consistent-hashing 00:57](file:///abs/explainers/consistent-hashing/out/episode.mp4#t=57).
```

## 11. Index with qmd and cairn

The library is one markdown file per episode with stable headings, so `qmd` indexes it as is.

Plain search works at once: `rg "virtual nodes" explainers/library` finds a new episode the moment `transcript.py` has run. Indexed search does not: qmd and cairn see the episode only after its folder is in a QMD collection and `qmd update` has run. Treat that as an optional completion step, and do not report an episode as findable in cairn before it.

- If a qmd collection already covers the workspace (pattern `**/*.md`), it includes the library. Run `qmd update` after new episodes, then `qmd search "virtual nodes"` (BM25) or `qmd query "how does the ring spread load"` (hybrid).
- If the workspace is elsewhere, add the library as its own collection once. Check the exact flags with `qmd collection add --help` first, because they can change between qmd versions. Then run `qmd update` and, for vector search, `qmd embed -c <name>`.
- `cairn` recall and search run over qmd collections, so `/cairn:search "virtual nodes"` finds the episode once qmd has indexed it.
- qmd and cairn return the markdown line. The `[mm:ss]` at the start of that line is the time. Use `search.py` when you need the deep link.

## 12. Regenerate after a redo

After a segment redo (edit turns, `tts.py`, `align.mjs`, `build_manifest.py`, render), rerun `transcript.py` with the same slug. It rewrites the five episode files, replaces `library/<slug>.md`, replaces the slug's record in `index.json`, and refreshes the sidecar captions next to the mp4. Add `--embed-chapters` again, because the render writes a new mp4 without chapters. The date, tags, depth and series stay as they were. A search for the new wording then returns the new times. Then rerun `learn.py`: the turn ids in `learn.json` stay valid when ids are kept, and every `[mm:ss]` moves with the new timing, gap-log rows included.

## 13. Learning artefacts: learn.json, learn.py and learn/

The agent writes `<slug>/learn.json` from the approved script once `timing.json` exists (rules and judge criteria in `learning-design.md` section 8; schema `schemas/learn.schema.json`; example `evals/files/sample-learn.json`). Every item names a turn id, never a time, so a redo re-times it.

```bash
python3 scripts/learn.py --workspace explainers --slug hash-maps          # text report
python3 scripts/learn.py --workspace explainers --slug hash-maps --json   # JSON report
```

What it does, in order:

1. Validates `learn.json` against the schema (`jsonschema` when importable, else a built-in checker) and checks that every `turn`, `turnId` and `segment` exists in `script.json` and `timing.json`, and that a self-test turn sits in its stated segment. Any problem stops the run with exit 1 and a numbered list naming the item (`cards[3]: turn t99 is not in script.json`).
2. Warns (exit 0) when the self-test does not have 5 questions, has more than one `remember` question, a card front is not a question, or `summary.md` runs over about 400 words.
3. Writes `learn/selftest.md` (questions, then an answer key with `Explained at [mm:ss] (segNN, tNN)`, a `[slug mm:ss]` citation and a `#t=` deep link when the mp4 exists), `teachback.md`, `cards.csv`, `cards.md`, `summary.md` and `gaplog.md`.
4. Copies the six files to `library/learn/<slug>/`, so `grep`, `rg`, qmd and cairn see them next to the transcripts.
5. Updates the slug's record in `library/index.json` (fields in section 7). If there is no record yet, it still writes `learn/`; `transcript.py` registers the fields when it runs.

`cards.csv` is ready for Anki: no header row, TAB separated, columns front, back, tags. The back ends with `[<slug> mm:ss]`. Tags are `explainer::<slug>` and the segment id. Import with File, Import, note type Basic, separator Tab.

`gaplog.md` is seeded once from `learn.json` `gapLog`, with the Rewatch cell written as `[mm:ss] (tNN)`. The learner adds rows by hand; a turn id in their Rewatch cell keeps that time current too. A rerun keeps every row and every cell the learner wrote, refreshes the `[mm:ss]` of each row from its turn id (so a redo moves them), appends only seed rows whose question is new, and recounts `openGaps` (rows with status `open`).

Reruns are idempotent: the same inputs give byte-identical files and the report says `unchanged`. Measured on 2 Nov 2026 with the consistent-hashing test episode: 5 questions, 6 cards, 12 files written on the first run, 0 on the second; `transcript.py` after `learn.py` reported `unchanged`.

## 14. Export a portable delivery

`scripts/export_delivery.py --workspace explainers --slug <slug> --to <DIR>` copies the COMPLETE delivery of one episode into a folder that works on its own (an example, an archive, a share): the mp4 with its sidecars, `transcript.md`/`.json`, captions, chapters, `delivery.json`, `learn.json` and `learn/`, the planning JSON files, `audio/episode.wav`, the whole `qc/` tree (`scores.json`, `listen.json`, the judge and restate briefs and replies when present), `library/<slug>.md`, `library/learn/<slug>/` and a one-record `library/index.json`. It rewrites every absolute path or `file://` link into the workspace to a relative one, records each file's sha256 and its source's sha256 in `<DIR>/export.json`, checks the copies and the `delivery.json` digests, and exits 1 on a broken link unless `--allow-broken-links`. `--force` replaces a previous export (only the files its `export.json` lists; a `README.md` stays).
