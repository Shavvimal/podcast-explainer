# Depth: quick, standard, deep

Read this file before the outline pass. It sets the size of an episode, the research it needs, and how a deep episode becomes a series of parts. The outline and dialogue rules in `script.md` still apply at every depth.

## Contents

1. The depth ladder (table)
2. Pick a depth
3. Build depth, not length
4. Research a deep episode
5. Split a deep episode into a series
6. Outline templates per depth
7. Failure modes and checks

## 1. The depth ladder

Word budgets use the measured Gemini rate: 0.357 s per word, about 168 words per minute (`gemini-3.8-flash-tts`, Kore and Puck, 2 Nov 2026, [gemini-tts.md](gemini-tts.md) section 13). `validate_script.py` uses the same rate and subtracts pause holds. 150 words per minute stays only as the planning default for a first outline (rule S14). Pace varies by voice, so measure the real audio after `tts.py` and trim words, not segments.

| | quick | standard | deep |
|---|---|---|---|
| Minutes | about 6 | about 12 | 20 to 35, as 2 or 3 parts of at most 12 minutes |
| Segments | 5 | 8 | 10 to 16 in total, 4 to 8 per part |
| Spoken words (0.357 s per word, minus holds) | about 950 | about 1,900 | 3,200 to 5,600 (at most 1,900 per part) |
| Pause holds (6 to 8 s each, one per 5 to 6 minutes) | 2 | 3 or 4 | at least 5, at least 2 per part |
| Turns (about 5 to 10 per minute at 45 words max; measured 72 turns for 11 minutes on 2 Nov 2026) | 30 to 60 | 60 to 120 | 100 to 300 (at most 120 per part) |
| New terms (the one term rule) | at most 3 per episode | at most 5 per episode | at most 5 per part, glossary of 8 to 20 terms for the series |
| Fact digest (`facts.json`) | 8 to 15 facts, 1 source is enough | 15 to 30 facts, at least 2 sources | 40 to 80 facts, at least 5 sources, 3 independent sources per load-bearing claim, contradictions listed |
| Retrieval checks | 1 at the end, plus the cold-open prediction pause | 1 or 2, plus a mid-episode `retrieve` pause | at least 2: one at the end of each part, plus one spaced check that reaches back to an earlier part |
| Misconception beats | 1 | 1 or 2 | one per major idea, collected in a misconceptions list |
| Worked examples | 1, plus 1 transfer | 1 or 2, plus 1 transfer | at least 2 full worked examples, plus 1 transfer per part |
| Gemini TTS cost, `gemini-3.8-flash-tts`, until 31 Dec 2026 | about $0.08 | about $0.16 | $0.27 to $0.47 |
| Same, from 1 Jan 2027 | about $0.16 | about $0.32 | $0.54 to $0.95 |

Term rule, stated once: at most 4 new terms in any one segment (`outline.schema.json` `newTerms` maxItems 4), and per episode at most 3 for quick, 5 for standard and 5 per part for deep (`validate_script.py` W20). The numbers live in `schemas/common.schema.json` `$defs.newTermLimits`, which the validator reads; every other file points here. The standard word budget is 1,900 words; other files link here instead of restating it.
| Render time, local Apple Silicon Mac, `--concurrency=16` | about 1 minute | about 2 minutes | about 2 minutes per part |

Where the cost numbers come from: audio output is 25 tokens per second and costs $9.00 per million tokens until 31 Dec 2026, then $18.00 (https://ai.google.dev/gemini-api/docs/pricing, read 2 Nov 2026). So one minute of audio costs about $0.0135 now and $0.027 from January 2027. Text input is under 1% of the cost. Add 20% for re-takes of truncated turns. The free tier also works, but Google can use free-tier data to improve its products.

Where the render numbers come from: measured on 2 Nov 2026, a 10:48 standard episode rendered in about 100 s wall time on an M-series Mac at `--concurrency=16` (about 0.15 times real time, three renders within 2 s of each other). Older planning numbers (2 to 4 times real time on 8 server vCPUs, Remotion issue 4783; `../../../research/playbooks/remotion-podcast-video.md`) were 7 to 22 times too pessimistic for this template.

TTS wall time is not measured. Planning number (unverified): per-turn calls with 4 workers, about 5 seconds per call, so about 2 minutes for a quick episode and 5 to 10 minutes for a deep series. The project's TTS requests per minute (RPM) limit is shown only in AI Studio. Check it before a deep run, because a deep series makes 200 to 500 calls.

## 2. Pick a depth

Precedence: an explicit depth name in the request (quick, standard, deep) always wins over the trigger words below. "An in-depth explainer, standard depth" is `standard`.

Default, stated once for the whole skill: when the request names no depth and no length, use `standard` (about 12 minutes, 8 segments). SKILL.md, script.md and learning-design.md link here.

- If the learner asks for "a quick one", a single fact, or 5 minutes or less, use `quick`.
- If the learner names no length and the concept has one mechanism, use `standard` (the default).
- If the concept has two or more mechanisms that build on each other, or the learner says "in depth", "from first principles", "properly" or "deep dive", use `deep`.
- If a `quick` outline needs more than 3 new terms, it is not quick. Ask the learner to pick `standard` or to narrow the concept.

Set the learner level at the same time (`brief.json` `learnerLevel`, [learning-design.md](learning-design.md) rule L7). `near-expert`: the concept sits next to the learner's work, so skip the `plain` segment and spend the time on the misconception and a second pause. `novice`: keep the `plain` segment and add a second worked example. `familiar` (default): a short plain pass.

Record the choice in `brief.json` `depth` and `learnerLevel`, and pass `--depth quick|standard|deep` to `transcript.py` (it also infers depth from the duration when the flag is absent).

## 3. Build depth, not length

Depth is the number of distinct levels of understanding the episode climbs, not the minutes. A 30-minute episode that restates one idea six times is long and shallow. Each segment in a `standard` or `deep` outline must sit on one rung of the ladder below, and the outline must climb it in order. A `quick` episode uses rungs 1, 2, 4 and 6 only.

| Rung | What the learner gets | Typical segment role | Test question for the outline |
|---|---|---|---|
| 1. Intuition | A concrete picture of what happens, before any term | hook, puzzle, example | Can the learner predict the outcome of one simple case? |
| 2. Mechanism | The causal steps: what moves, in what order, and why | mechanism | Can the learner say why each step must happen? |
| 3. Formal view | The rule, equation or invariant that the steps obey | mechanism, terms | Can the learner state the rule and map each symbol back to the picture? |
| 4. Worked example | The rule applied to numbers or a real case, step by step | example | Can the learner do the next step themselves before the expert does? |
| 5. Edge cases | Where the rule bends: limits, extreme inputs, failure | scale, compare | Can the learner say what happens at the boundary, and why? |
| 6. Misconceptions | The plausible wrong models, voiced and broken | misconception | Can the learner say why the wrong model fails, not only that it fails? |
| 7. Connections | Links to what the learner already knows (`brief.json` `learner.knows`) and to the next concept | transfer, compare | Can the learner use the idea in a context the episode did not show? |

Four devices make the climb stick:

- **Spiral recap.** At the start of each new rung, the learner host restates the previous rung in one sentence, then the expert adds the new layer. Each recap must add something: the rung name or a new consequence. A recap that only repeats is padding (section 7).
- **Glossary.** Every term gets one plain sentence and one picture when it first appears. A `deep` episode writes `<slug>/glossary.json` (`{"terms": [{"term": "...", "definition": "..."}]}`). `transcript.py` puts it in the transcript's Glossary section, with the time of first mention.
- **"What would break if" questions.** Once per rung from rung 2 on, the learner asks "what would break if we removed X?" or "what if X were ten times bigger?". The expert answers with a visible change in the concept world. This is the deep-question rule S1 in its strongest form.
- **Retrieval checks.** A check asks for the mechanism, not a word. The asking turn sets `holdAfterMs` 6000 to 8000 and a `pause` cue, so the video shows the prompt with a countdown before the answer. One pause every 5 to 6 minutes of episode (validator W23). A spaced check in part 2 or 3 reaches back to part 1.

## 4. Research a deep episode

A `deep` episode needs a fact digest wide enough that no load-bearing claim rests on one page. Do this before the outline. A deep run is a series, so the research lives once, in `explainers/<series-id>/research/`, and the master `facts.json` in `explainers/<series-id>/facts.json`. Copy that `facts.json` into each part folder unchanged (the validator's `--facts`, `qc.py` and the judge read `<slug>/facts.json`); edit the master and copy again, never a part's copy.

1. **Search.** Load the `firecrawl` skill and search for the concept with 3 to 5 phrasings: the plain name, the mechanism, "misconception" or "common mistake", and "worked example". For papers, use the `firecrawl-research-index` skill instead of web search. For library or API behaviour, use `firecrawl-developer-index`.
2. **Scrape.** Scrape the 5 to 10 best sources to markdown in `<slug>/research/sources/` (one file per source, named `s<N>-<short-name>.md`). If a PDF scrapes garbled (two-column text, repeated abstract), try `firecrawl parse` on a downloaded copy, or cite a secondary source that quotes it. Prefer primary sources: the original paper, the official documentation, the standard. Use a secondary explainer only for analogies and misconceptions, never as the only source for a number.
3. **Claim ledger.** Write every number, named entity, causal claim and negation into `facts.json`, each with a verbatim `quote` and a `sourceId` (schema in `schemas/facts.schema.json`). A fact without a quote is a gap, not a fact.
4. **Three independent sources for load-bearing claims.** A claim is load-bearing when a segment or a misconception depends on it. For each such claim, add one fact per source (same `claim`, different `sourceId` and `quote`). Two pages that copy the same blog are one source. If you find fewer than 3, mark the claim in `facts.json` `openQuestions` and tell the learner at gate 1.
5. **Contradictions section.** When two sources disagree, do not pick one in silence. Add an entry to `facts.json` `openQuestions` in the form `Contradiction: s2 says X ("quote"), s5 says Y ("quote"). Proposed reading: ...`. The learner decides at gate 1. A contradiction that survives into the script needs a turn that says the sources disagree.
6. **Misconceptions list.** Collect plausible wrong models in `facts.json` `misconceptions`. A deep episode needs one per major idea. Prefer misconceptions that a source documents (forum threads, textbook "common errors" boxes) over invented ones.

Budget: about 15 to 30 minutes of agent time and 10 to 20 Firecrawl calls for a deep digest. A `standard` episode needs steps 1 to 3 with 2 or more sources. A `quick` episode can use the source the learner gave alone.

## 5. Split a deep episode into a series

Default: every `deep` episode is a series of parts. Reasons: the conversational-style effect fades past 35 minutes (Ginns 2013, rule S11), median engagement with one video is about 6 minutes (Guo 2014), and chapters of 2 to 4 minutes inside parts of at most 12 minutes keep each file watchable in one sitting. The schemas allow 16 segments and 40 minutes in one script, but `validate_script.py` warns (W21) on an unsplit deep script over 12 minutes and fails (E21) a series part over 12 minutes.

Rules:

- Each part is at most 12 minutes and has 4 to 8 segments. Each part is a normal episode with its own folder, `script.json`, audio, `episode.mp4` and transcript. Slugs: `<series-id>-p1`, `<series-id>-p2`, and so on.
- Cut at a rung boundary, never inside a worked example. Part 1 usually covers rungs 1 to 3, part 2 rungs 4 to 5, part 3 rungs 6 to 7.
- Each part after the first opens with a recap segment of 30 to 45 seconds. The learner host recaps the previous part in their own words (explain-back), and the expert corrects one detail. Then the part's own hook follows.
- Each part except the last ends with a retrieval check and one preview line that names the next part's question. A preview names a question, not a cliffhanger promise.
- Keep the same two hosts, voices, colours and sides in every part. Keep one concept world: same diagram, same colours, same positions. Part 2 starts from the final state of part 1's world.
- Keep one `glossary.json` for the series and copy it into each part folder, so each transcript lists every term. A part's transcript lists a term it never speaks without a first mention. `search.py` ranks transcript turns above glossary lines, ranks a glossary line with no first mention last, and links it to the part whose transcript first mentions the term ("taught in `<series-id>-p2`"), so a search lands on the part that teaches it (W16).
- Leave room in part 1's world layout for the nodes part 2 adds: the series check fixes every carried node's position (E32). End each part's world on the state the next part opens with: the series check carries what the last world step displays, so a what-if `set` on that step is carried too (W14b D25).
- Export a finished series with `export_delivery.py --series explainers/<series-id>/series.json --to "<DIR>"`: every part, the series folder and an `index.md` with relative links.

Write the series index at `explainers/<series-id>/series.json`:

```json
{ "version": 1, "id": "transformers", "title": "Transformers from first principles",
  "depth": "deep", "learningObjective": "...",
  "parts": [
    { "part": 1, "slug": "transformers-p1", "title": "Attention as a lookup", "rungs": [1, 2, 3], "targetMinutes": 11 },
    { "part": 2, "slug": "transformers-p2", "title": "Attention in numbers", "rungs": [4, 5], "targetMinutes": 12 },
    { "part": 3, "slug": "transformers-p3", "title": "What it is not", "rungs": [6, 7], "targetMinutes": 10 } ],
  "recapLines": { "2": "Last time: attention lets each word look up the others by similarity.", "3": "..." },
  "previewLines": { "1": "Next: what those similarity numbers are, for one real sentence.", "2": "..." } }
```

Validate the series with `python3 scripts/validate_script.py explainers/<series-id>/series.json` (schema `schemas/series.schema.json`). It checks every part folder too: parts numbered 1..n with slugs `<series-id>-p<N>`, each part's `script.json` `series` matching (`id`, `part`, `parts`), the same hosts (id, name, voice, colour, side) in every part, one `glossary.json`, at least 2 retrieval checks across the series, a misconception segment somewhere, world nodes carried into the next part, and, once a part has `timing.json`, its MEASURED audio at most 12 minutes (the plan's `targetMinutes` is not enough). Before any payment, `validate_script.py` E39 already refuses a part script whose PREDICTED length is over 684 s (12 minutes minus 5% headroom), and `tts.py` runs the same check (W13a). A part's `timing.json` must hold one turn per script turn and at least 0.8 x words x 0.357 s. The world carried into the next part is what the renderer displays at the end of the part (expired `set` values are not carried). A malformed `timing.json` or `scenes.json` in a part is an error, never a duration of 0 or a skipped world (E21, E32). With `--final` every part must have the same, valid `glossary.json` (E31). `qc.py probe.partcap` checks the same cap on the rendered part.

Then run `transcript.py --slug <series-id>-p<N> --series <series-id> --part <N> --depth deep` for each part. Scripts say `series.parts`; `library/index.json` writes it as `series.of`. `search.py --list` shows the part numbers.

## 6. Outline templates per depth

The segment skeletons are defined once, in [learning-design.md](learning-design.md): section 5 (`quick`, 5 segments), section 6 (`standard`, 8 segments) and section 7 (`deep`, two parts of 6 segments). Roles come from the single enum in `schemas/common.schema.json`. This section adds the rung each skeleton row climbs (section 3), so the outline can pass the "flat ladder" check in section 7.

| Depth | Segment roles in order | Rungs climbed |
|---|---|---|
| quick | `hook`, `plain`, `misconception`, `analogy`, `selftest` | 1 (hook, plain), 4 (worked example inside plain), 6 (misconception), 2 (analogy carries the rule), recap and retrieval |
| standard | `hook`, `plain`, `example`, `terms`, `misconception`, `mechanism`, `transfer`, `selftest` | 1, 1, 4, 3, 6, 2 and 3, 5 and 7, recap |
| deep part 1 | `hook`, `plain`, `example`, `terms`, `misconception`, `selftest` | 1, 1 and 2, 4, 3, 6, recap and preview |
| deep part 2 | `recap`, `mechanism`, `analogy`, `misconception`, `transfer`, `selftest` | spaced retrieval of part 1, 2 and 3 (abstract), 2, 6, 5 and 7, recap |
| deep part 3 (optional, for 3-part series) | `recap`, `example`, `scale` or `compare`, `misconception`, `transfer`, `selftest` | retrieval, 4 with numbers, 5, 6, 7, the series puzzle resolved |

Rules that hold at every depth:

- `near-expert`: replace `plain` with `mechanism` (no plain pass). `novice`: keep `plain` and add a second `example` when time allows.
- The cold-open `hook` holds a `predict` pause whose prompt targets the core idea of `learningObjective` (validator E25 when the pause is missing, W25 when the prompt misses the objective).
- One `retrieve` pause every 5 to 6 minutes (W23). A part of 12 minutes has at least 2 pauses.
- The last segment of every part is `selftest` or `check`. A part that is not the last ends with one preview line that names the next part's question.
- Each part after the first opens with `recap` as retrieval: questions with holds, the learner answers, the expert corrects one detail. Not a lecture by the expert.

## 7. Failure modes and checks

Run these checks on the outline (before gate 1) and again on the script (after `validate_script.py`). Each check names what to count.

| Failure | What it looks like | Check | Fix |
|---|---|---|---|
| Padding | Turns that add words but no new fact, step or question: "That's a great point", long restatements, generic stakes ("this changes everything") | For each segment, list the new facts, steps or questions it adds. A segment that adds none fails. Words per new item above about 120 is a warning. | Cut the segment or merge it. Do not stretch a quick concept to standard length. |
| Repetition | The same explanation in two segments with different words | Compare each segment's learningGoal with every other: two goals that say the same thing fail. Recaps are allowed only at part starts and in the final check, and each must add a rung name or a consequence. | Merge, or replace the second instance with an edge case or a transfer. |
| Drift off the learning goal | Interesting asides that do not serve the objective: history, trivia, a second concept | Every segment's learningGoal must name a step toward the episode's learningObjective. Ask: "if this segment were cut, would the retrieval question get harder?" If no, cut it. | Move the aside to the next episode's idea list. |
| Flat ladder | Ten segments all at the mechanism rung | Tag each segment with its rung (section 3). A standard outline covers at least 5 rungs. A deep series covers all 7. | Replace a duplicate rung with an edge-case or a connections segment. |
| Shallow retrieval | "What is X called?" | The question needs the mechanism to answer: it starts with why, how, what if, or predict. | Rewrite as a prediction about a new case. |
| Thin sources | A load-bearing number from one blog | Count distinct sources per load-bearing fact in `facts.json`. Deep needs 3. | Research more, or flag the claim as uncertain on screen and in a turn. |
| Lost thread across parts | Part 2 assumes terms that part 1 never defined | Every term used in part N appears in the series glossary and in part N or earlier. | Add the term to the recap segment. |
| Over-long part | A part runs past 12 minutes after TTS | Read `durationMs` in `timing.json` after `tts.py --scratch`. The `say` voice runs faster than Gemini, so scale by 0.357 s per word, not by the scratch length. | Cut words in the densest segment, or move one segment to the next part. |
| No pauses | 8 minutes of talk with no `pause` turn | `validate_script.py` W23 | Add a `retrieve` pause on an existing question turn (`holdAfterMs` 7000). |
