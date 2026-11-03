# Learning design: make the learner understand, not feel that they understand

Use this file when you write `outline.json`, write `script.json`, write the `learn/` artefacts, and when the judge scores an episode. Sources and evidence tags are cited inline. Dialogue rules S1 to S14 are in [script.md](script.md) section 3 and visual rules V1 to V10 in [visuals.md](visuals.md); they are not repeated here.

## Contents

1. The one idea behind this file
2. Rules (L1 to L16)
3. Feynman-in-the-loop moves (M1 to M9)
4. Section library (A to I)
5. Skeleton: 6 minutes (`quick`)
6. Skeleton: 12 minutes (`standard`)
7. Skeleton: 25 minutes (`deep`, two parts)
8. Learning artefacts (`learn/`)
9. Transcript and library fields
10. Judge rubric (J1 to J11)
11. Resolved decisions

## 1. The one idea behind this file

A clear, fluent video raises confidence without raising learning (Carpenter et al. 2013, https://link.springer.com/article/10.3758/s13423-013-0442-z). The effects that work (retrieval, self-explanation, generation, prediction, teaching) all need the learner to produce something. So every episode must (a) make the learner-proxy host produce and repair explanations on screen, (b) give the learner short, specific moments to produce answers themselves, with the answer after a silence, and (c) hand them files that make them test and teach after the video. Never optimise for "smooth".

The "Feynman technique" is a popular 2011-era label, not a validated framework and not Feynman's own method. Use its parts, which have evidence, not its name.

## 2. Rules

Each rule has a one-line rationale. Evidence tags: [strong] meta-analysis, [single] one study, [practitioner] craft or theory.

- **L1. One learning goal per episode, written as a question the cold open asks.** Prequestions help mainly the content they target (meta-analysis, specific g = 0.54, general near 0) [strong].
- **L2. Open on a puzzle and a prediction, never a definition.** Making a prediction lets a violated outcome surprise the learner, and surprise predicts learning (Brod 2018) [single]. Segments between the cold open and the misconception refer to the open prediction once without answering it ("hold that guess"), so the puzzle stays alive until the refutation.
- **L3. Plain meaning first, then the term, then use the term freely.** A term without its referent is a definition, not an idea (Feynman, "What is Science?"); writers suffer from the curse of knowledge [practitioner, single].
- **L4. Concrete, then labelled, then abstract, on one persistent diagram.** Concreteness fading supports transfer (Fyfe 2014 review) [strong].
- **L5. Every causal step gets a why or how question before it and a visible state change on it.** Deep questions drive vicarious learning (Craig 2006); the illusion of explanatory depth hides missing steps (Rozenblit and Keil 2002) [single].
- **L6. Worked example first, then a faded example the Learner drives.** Example-problem pairs beat problems alone for novices (van Gog 2011) [single].
- **L7. Adapt to prior knowledge.** If `brief.json` `learnerLevel` is `near-expert`, cut the `plain` segment and the worked-step scaffolding; high-knowledge learners learn better with less help (d = -0.43, 2025 meta-analysis) [strong]. `novice` keeps both. The validator warns (W24) on a mismatch.
- **L8. Refute the misconception in four parts.** State it, say it is wrong, show it fail, give the right model and why the wrong one tempts (refutation texts g = 0.41) [strong].
- **L9. One analogy at a time, mapped explicitly, with its break stated.** The teaching-with-analogies model requires "indicate where the analogy breaks down" (Glynn) [practitioner].
- **L10. One retrieval hold every 5 to 6 minutes.** Interpolated tests cut mind wandering and raise learning in video lectures (Szpunar 2013) [single, replicated]. The validator fails (E23) when no `retrieve` or `explain-back` pause follows the cold open, and warns (W23) after 6 minutes of episode without a pause turn.
- **L11. A hold is 6 to 8 seconds of silence with a countdown, and the answer comes after it.** Classroom wait time of 3 seconds or more improves answers (Rowe); no video study fixes a number [practitioner]. Mechanics: the turn that asks sets `holdAfterMs` (6000 to 8000; an `explain-back` hold of several sentences aloud may run to 15000) and `pause: {kind, prompt}` in `script.json`; `tts.py` inserts the silence and records it in `timing.json`; `build_manifest.py` writes `holds[]` into `episode.json`; the template's `PauseCue` dims the stage and shows the prompt card with a countdown ring for the hold.
- **L12. Questions ask for understanding, not a word.** At most one "remember"-level question per self-test (revised Bloom) [practitioner].
- **L13. Chapter every 2 to 4 minutes with a title card that names the next question.** Segmenting helps (retention d = 0.32, transfer d = 0.45) [strong]; median MOOC engagement is about 6 minutes per video (Guo 2014) [single].
- **L14. Cut seductive details.** Interesting but irrelevant facts hurt learning (Sundararajan and Adesope 2020) [strong].
- **L15. Normal conversational pace is fine; slow the mechanism with holds, not slower speech.** Lectures at 1.5x to 2x cost little (Murphy 2022) [single]. Gemini speaks at about 168 words per minute (0.357 s per word, measured 2 Nov 2026); plan outlines at 150 and budget scripts at the measured rate.
- **L16. End with work for the learner, not a recap by the Expert.** Teaching after preparing g = 0.56; interactive teaching beats non-interactive (Kobayashi 2018) [strong].

## 3. Feynman-in-the-loop moves

Hosts: EXPERT and LEARNER (the learner-proxy at the learner's level, as `brief.json` `learner.knows` states it). Use M1 to M4 inside segments, M5 and M6 at holds, M7 to M9 at the end.

- **M1. Learner attempts first.** Before the Expert explains a step, the Learner gives a plausible, incomplete plain-word explanation: a skipped step, a vague word ("it just knows"), or the misconception.
- **M2. Expert names the exact gap, then asks one question.** Quote the weak word back ("You said it 'just knows'. What tells it?"). The Learner repairs; the Expert confirms or fixes one detail.
- **M3. Plain first, then name.** Pattern: "That part, the one that does X, is called Y." After this turn, Y may appear on screen and in speech.
- **M4. Jargon tripwire.** If a host uses a term before its plain description, the other host asks "What do you mean by Y?" in the next turn. The writer must not need this often; the validator flags each case (J1).
- **M5. Pause-and-predict.** A host asks the learner directly ("Before we go on, what do you think happens to X?"). Set `holdAfterMs` 6000 to 8000 on that turn. Then the Learner gives a prediction, usually the tempting wrong one.
- **M6. Gap-check.** One why or what-if question, a hold, the Learner's answer, the Expert's confirmation, then "If you missed that, go back to [chapter title]."
- **M7. Learner explains back.** At recap the Learner explains the whole mechanism in 3 to 5 plain sentences. The Expert sharpens exactly one point. The Learner never praises the Expert.
- **M8. Explain-it-aloud prompt.** The last segment asks the learner to explain the idea aloud in three sentences now, and names `learn/teachback.md`.
- **M9. Teach-back worksheet.** Write `learn/teachback.md` (section 8).

Do not tell the Learner to "explain it like I'm five". The learner is an adult expert in other fields. The target is a sharp outsider.

## 4. Section library

Each segment in `outline.json` has one `role` from the single enum in `schemas/common.schema.json` (`$defs.role`): `hook`, `puzzle`, `roadmap`, `plain`, `terms`, `example`, `mechanism`, `misconception`, `analogy`, `transfer`, `compare`, `scale`, `check`, `recap`, `selftest`. The table maps the sections onto roles. A skeleton row that combines two sections uses the role of the section that carries the segment's `learningGoal`; the other section's beats sit inside it. `references/script.md` section 4 lists every role with its job.

| Section | Purpose | Hosts do | Screen does | Anti-pattern |
| --- | --- | --- | --- | --- |
| A. Cold open (`hook`) | Create a gap; voice the naive model | LEARNER states the puzzle and a confident naive prediction. EXPERT asks the learner to predict (M5). | One concrete image; question card with countdown during the hold. | Definition, topic history, "today we'll learn". |
| B. Plain pass (`plain`) | Whole idea in everyday words | M1 then M2. No glossary terms. | Concrete version of the concept world, no labels. | A "simple version" that still uses the terms. |
| C. Mechanism with worked example (`mechanism`) | Each causal step on one case | LEARNER asks why or how before each step; EXPERT answers in at most 3 sentences. | Diagram builds on the word; one focal object per step. | "And then it just..."; visuals ahead of speech. |
| D. Naming (`terms`) | Attach terms to understood parts | M3 for each term. Term limits: [depth.md](depth.md) section 1 (one statement, from `schemas/common.schema.json` `$defs.newTermLimits`). | Labels appear on the diagram at the spoken word; concrete objects fade to boxes. | Glossary dump; label before word. |
| E. Misconception (`misconception`) | Break the naive model from A | LEARNER applies the A prediction; EXPERT asks the breaking question; LEARNER notices; EXPERT gives the right model and why the wrong one tempts (L8). | Wrong model plays out unlabelled, then real outcome side by side. | "A common misconception is..." said in passing. |
| F. Analogy (`analogy`) | Portable mental model | EXPERT offers one analogy; LEARNER maps the parts; one host states where it breaks. | Analogue and target side by side, mapping lines, red mark on the broken mapping. | Stacked analogies; no limit stated. |
| G. Retrieval hold (`check`; transfer form `transfer`, interleave form `compare`) | Recall; show the learner their gap | M6. | Question card, countdown, then answer card with chapter name. | "Make sense?"; answer before the hold. |
| H. Teach-back recap (`recap`) | Model the simplify step | M7; resolve the cold-open puzzle. | Progress strip ticks; diagram replays compressed. | EXPERT recaps; "so we've established". |
| I. Self-test and next time (`selftest`) | Hand the work to the learner; plant spacing | M8; read one self-test question (not its answer, and never the `heldOut` one); state the next-time question. | Check-yourself card: 1 question, no answer. The `learn/` paths go in the transcript and gate 3, not on the card. | "Stay curious"; answers on screen. |

## 5. Skeleton: 6 minutes (`quick`, 5 segments)

About 860 spoken words at the measured 0.357 s per word plus 2 holds. Measure real audio and rescale. One role per segment; the second section sits inside it.

| # | Role | Sections | Time | Share | Words | Holds | Must contain |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `hook` | A | 0:00-0:35 | 10% | 70 | 1 x 7 s `predict` | Puzzle, LEARNER prediction, prequestion to the learner that targets the core idea |
| 2 | `plain` | B, then C | 0:35-2:35 | 33% | 300 | 0 | M1, M2, worked example of at least 3 steps |
| 3 | `misconception` | D, then E | 2:35-4:05 | 25% | 220 | 0 | At most 3 terms via M3 at the start; four-part refutation |
| 4 | `analogy` | F, then G | 4:05-5:10 | 18% | 140 | 1 x 7 s `retrieve` | Analogy with its break; one gap-check |
| 5 | `selftest` | H, then I | 5:10-6:00 | 14% | 120 | 0 | M7 (learner explain-back turn), M8, next-time question |

If L7 applies (`learnerLevel: near-expert`), segment 2 becomes `mechanism` (C only, no plain pass) and the time goes to E and a second hold.

## 6. Skeleton: 12 minutes (`standard`, 8 segments)

Word budget and term limits: [depth.md](depth.md) section 1 (about 1,900 spoken words plus 3 to 4 holds).

| # | Role | Sections | Time | Share | Must contain |
| --- | --- | --- | --- | --- | --- |
| 1 | `hook` | A + roadmap | 0:00-0:50 | 7% | `predict` hold; 3 questions as a progress strip (advance organiser) |
| 2 | `plain` | B | 0:50-2:20 | 12% | LEARNER attempt, EXPERT gap, LEARNER repair |
| 3 | `example` | C | 2:20-4:40 | 20% | Worked example 1, EXPERT-led |
| 4 | `terms` | D | 4:40-5:30 | 7% | At most 4 terms via M3 (the per-segment cap; 5 per episode) |
| 5 | `misconception` | G, then E | 5:30-7:30 | 17% | `retrieve` hold at about 6:00, then four-part refutation of the cold-open prediction |
| 6 | `mechanism` | C faded, F | 7:30-9:40 | 18% | LEARNER drives example 2; one analogy with its break |
| 7 | `transfer` | G (transfer) | 9:40-10:50 | 10% | New context from the learner's world; one compare-with-neighbour question; `retrieve` hold |
| 8 | `selftest` | H, I | 10:50-12:00 | 10% | M7, M8, next-time question |

## 7. Skeleton: 25 minutes (`deep`, two parts of 12 minutes, 12 segments)

Part 1 builds the model. Part 2 stresses it. Part 2 opens with retrieval, not a recap lecture. At least 5 holds in total. Each part is its own episode folder (`references/depth.md` section 5).

| # | Part | Role | Sections | Time in part | Must contain |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | `hook` | A + roadmap | 0:00-1:00 | `predict` hold; roadmap of both parts |
| 2 | 1 | `plain` | B | 1:00-2:45 | First-principles version: what must be true for this to work |
| 3 | 1 | `example` | C | 2:45-5:30 | Worked example 1, concrete stage |
| 4 | 1 | `terms` | D, then G | 5:30-7:15 | Terms via M3; `retrieve` hold at about 6:30 |
| 5 | 1 | `misconception` | E | 7:15-9:15 | Refute the cold-open prediction |
| 6 | 1 | `selftest` | H, I | 9:15-12:00 | M7; one question left open for part 2; 3 card fronts |
| 7 | 2 | `recap` | G | 0:00-1:15 | Two retrieval questions from part 1, each with a hold, answers after (the series opener the validator accepts) |
| 8 | 2 | `mechanism` | C faded | 1:15-3:45 | LEARNER drives; abstract stage of the diagram |
| 9 | 2 | `analogy` | F | 3:45-5:30 | One analogy, mapped, with its break |
| 10 | 2 | `misconception` | E, then G | 5:30-8:00 | Second, subtler misconception; hold at about 7:00 |
| 11 | 2 | `transfer` | G (transfer) | 8:00-10:15 | Apply to a domain from the learner's world; one interleaved question against a neighbour concept |
| 12 | 2 | `selftest` | H, I | 10:15-12:00 | Full M7, M8, next-time question |

## 8. Learning artefacts (`learn/`)

Write `explainers/<slug>/learn.json` after `script.json` passes validation and `timing.json` exists, then run `python3 scripts/learn.py --workspace explainers --slug <slug>`. Every item names a turn id, never a time; `learn.py` looks up the `[mm:ss]` in `timing.json`, so a redo re-times every item. It writes the six files below into `explainers/<slug>/learn/` (plain markdown, one paragraph per line, stable headings), copies them to `explainers/library/learn/<slug>/` and registers them in `library/index.json`. Run details, failure messages and idempotency: `library.md` section 13.

`learn.json` shape (schema `schemas/learn.schema.json`, closed objects; example `evals/files/sample-learn.json`):

```json
{ "version": 1, "slug": "hash-maps", "title": "How a hash map works",
  "selfTest": [ {"question": "...", "level": "understand", "answer": "...", "segment": "seg03", "turn": "t07"} ],
  "teachBack": {"task": "...", "requiredIdeas": ["..."], "mustNotClaim": "...", "interactivePrompt": "..."},
  "cards": [ {"front": "Why ...?", "back": "...", "turnId": "t07"} ],
  "summary": {"puzzle": "...", "answer": "...", "plain": "...", "mechanism": ["..."],
              "terms": [{"term": "...", "meaning": "..."}], "misconception": {"claim": "...", "whyFails": "..."},
              "analogy": {"mapping": "...", "breaksWhere": "..."}, "stillOpen": ["..."], "heroStill": "qc/stills/turn-t12.png"},
  "gapLog": [ {"question": "...", "where": "n/a", "turn": "t10", "status": "open"} ] }
```

`selfTest` holds exactly 5 items (`brief.json` `selfTestCount`, 3 to 8, overrides), with at least one at `apply` or `transfer` level and at most one at `remember` level: `learn.py` refuses anything else (judge v6, 3 Nov 2026). When the script or outline has an `analogy` segment, `cards` must hold the analogy-limit card ("Where does the <analogy> analogy break?"), or `learn.py` refuses it. `summary.heroStill` must name a file that exists inside the episode folder (a still of the delivered mp4, for example `qc/stills/<name>.png` after `qc.py all`); a missing one is left out of `summary.md` with a warning, never linked (W13a, Q10); `level` is one of `remember`, `understand`, `apply`, `analyse`, `compare`, `transfer`; `turn` is the turn that explains the answer and must sit in `segment`. Exactly ONE item at `transfer` or `apply` level carries `"heldOut": true`: the new case the blind restater must solve (R05). Pick a case the video never works: another input, another domain. `qc.py brief.heldout` fails when 50% of its question's word pairs sit in one spoken or shown text; 50% of its answer's word triples in the video is a warning and evidence for the judge, who decides whether the video demonstrates the same case (quoting the closest case and solution). Do not read the held-out question aloud in the self-test segment; read a different one. `cards` holds 6 to 12 items. `analogy`, `stillOpen` and `heroStill` are optional.

### 8.1 `selftest.md`

```markdown
# Self-test: <title>

Answer aloud or on paper before you open the key. Then log every miss in gaplog.md.

## Questions

1. (understand) In your own words, why does <core effect> happen?
2. (apply) <new case>. What happens, and why?
3. (analyse) Someone says "<misconception>". What is wrong with it?
4. (compare) When does <concept> apply and <neighbour concept> not?
5. (transfer) <case from the learner's world>. How does <concept> show up here?

## Answer key

1. <1 to 3 sentences> Explained at [03:12] (seg03, t07). Cite [<slug> 03:12]. Rewatch: file:///.../episode.mp4#t=192
...
```

`learn.py` writes this file from `selfTest[]`. The `Rewatch` link appears once the mp4 exists. `search.py` parses these exact line shapes, so do not edit the generated file by hand: edit `learn.json` and rerun.

Rules: 5 questions; at most 1 at "remember" level; Q3 targets the episode's misconception; Q4 interleaves a neighbour concept (in a series, a concept from an earlier episode); no question is answerable by copying one transcript sentence.

### 8.2 `teachback.md`

Sections, in order:

1. **Task.** "Explain <concept> to a smart friend outside the field in at most 150 words. Use at most 3 terms and define each at first use. Do not look at the video or summary."
2. **Required ideas.** A checklist of 4 to 6 items taken from the segments' `learningGoal` values and the causal steps, plus one line: "Must not claim: <misconception>."
3. **Score yourself.** Tick the items you covered. Each missed item goes in `gaplog.md` with the timestamp to rewatch.
4. **Interactive version.** A paste-ready prompt for a chat model: "Play a curious student who knows <the learner's background> but not <concept>. After each sentence I write, ask one why or how question about the weakest step. Do not explain the concept yourself. After 6 exchanges, list which of these ideas I never explained: <required ideas>."

### 8.3 `cards.csv` and `cards.md`

6 to 12 cards. `cards.csv` is Anki-importable: no header, tab separated, columns `front`, `back`, `tags`. The back ends with the deep reference `[<slug> mm:ss]`. Tags: `explainer::<slug>` and the segment id of the card's turn. `cards.md` lists the same cards as `N. **Q:** <front>` and an indented `**A:** <back> [<slug> mm:ss] (segNN, tNN)` line with the deep link.

- Fronts are questions that need the mechanism ("Why does X slow down when Y fills up?"), never a cloze of a term.
- Include exactly one misconception card ("True or false, and why: <misconception>") and one analogy-limit card ("Where does the <analogy> analogy break?").
- Back: 1 to 2 sentences plus `[mm:ss]`.
- Suggested reviews: day 1, 3, 7, 21 (a convention; spacing itself is well supported).

### 8.4 `summary.md` (one page, at most about 400 words)

Headings, in order: `Puzzle and answer` (one sentence each), `Plain explanation` (3 to 5 sentences), `Mechanism` (numbered steps), `Terms` (term: plain meaning), `Misconception` (claim, why it fails), `Analogy` (mapping, where it breaks), `Still open` (items deliberately simplified). Embed the hero still of the mechanism: set `summary.heroStill` to its path under the episode folder (a still of the delivered mp4, for example `qc/stills/turn-t12.png`); `learn.py` embeds it as an absolute `file://` image only when the file exists, and `qc.py --final` fails a summary link that does not resolve. `learn.py` warns when the page runs over about 400 words.

### 8.5 `gaplog.md`

```markdown
# Gap log: <title>

| Date | Question I could not answer | Where I got stuck | Rewatch | Status | Closed by |
| --- | --- | --- | --- | --- | --- |
| <seed> | <point the script simplified on purpose> | n/a | [08:40] | open | |
```

Seed it with the points the script simplified on purpose (`learn.json` `gapLog[]`). `learn.py` writes the seed rows once, with the Rewatch cell as `[mm:ss] (tNN)`. The learner adds rows. A rerun never removes a row and never changes the learner's cells (date, question, where, status, closed by); it refreshes the `[mm:ss]` of every row that names a turn id (seed rows, and the learner's rows when they write one), appends only seed rows whose question is new and recounts `openGaps`. The next episode in a series reads open rows and the previous `cards[]` to write its retrieval opener and to choose its misconception.

## 9. Transcript and library fields

Implemented by `scripts/transcript.py` and `scripts/learn.py` (formats in `library.md` sections 3, 7 and 13):

- `transcript.md` front matter adds `learningGoal` (script `learningObjective`), `misconceptions` (list, from `learn.json` and `facts.json`), `analogies` (list of `{analogy, breaksWhere}` from `learn.json`), and `learn: "learn/"` when `learn.json` exists.
- `transcript.md` adds a section `## Check yourself` after the last chapter. It lists each pause as `- [mm:ss] Pause (<kind>, 7 s): <prompt>` at the time the hold starts, then the self-test questions without answers, each with `Answer explained at [mm:ss]`. A search for a question then lands on the moment that answers it.
- Each turn with `holdAfterMs` shows `[hold 7 s]` after its text.
- The `index.json` record gains, from `learn.py`: `learningGoal`, `misconceptions[]`, `learn` (absolute paths of the six files and `libraryDir`), `selfTest[]` as `{question, level, answer, segment, turn, t}`, `cards[]` as `{front, back, turn, t}` (t in seconds), and `openGaps` (count of open `gaplog.md` rows). Both scripts write these fields with the same function (`learn.compute_fields`): `transcript.py` registers them when `learn/` exists, and `learn.py` registers them when the index record exists, so the two scripts run in either order.
- `search.py` searches self-test items (question plus answer) and cards (front plus back) from `library/learn/<slug>/`, and pause prompts from `## Check yourself`. Each hit is labelled `self-test`, `card` or `pause` and carries the `[mm:ss]` and deep link of the turn that explains it.

## 10. Judge rubric (J1 to J11)

The judge is a separate agent with fresh context. It reads `script.json`, `timing.json`, the stills from `qc/`, and `learn/`. It scores each criterion 1 to 5 and quotes the turn ids or timestamps behind each score. Pass: no criterion below 3, and J1, J5, J7 and J11 at 4 or above (`qc.py` `J_BAR`). The judge must not reward "clear", "smooth" or "engaging", and must not use its own feeling of understanding as evidence.

| # | Criterion | Detect on the script | Detect on stills and timing | Score 1 / 5 anchors |
| --- | --- | --- | --- | --- |
| J1 | Plain meaning before jargon | For each glossary term, its first use must be in or after a turn that describes the same part in plain words. Any glossary term in sections A to C fails unless the brief marks it as known. | No still shows a term's label before the term's spoken timestamp. | 1: 3 or more terms used cold. 5: every term follows M3. |
| J2 | Prediction before explanation | The hook has a LEARNER prediction and a direct question to the learner; no answer before the hold. | `timing.json` gap of at least 6 s after that turn; the still in the gap shows the question, not the answer. | 1: no prediction. 5: prediction, hold, later visibly violated. |
| J3 | Concrete first, worked example | The first concrete example precedes the first general statement; worked example has at least 3 steps, each preceded by a why or how question. | Early stills show concrete objects; later stills show the same nodes labelled or abstract. | 1: opens abstract. 5: concrete, labelled, abstract on one diagram. |
| J4 | No unexplained steps | List each causal connective ("so", "therefore", "which means", "that's why"); each must point to a stated cause. Flag "just", "simply", "basically", "obviously" before a causal claim. | Still at each causal turn's midpoint shows a state change. | 1: 3 or more leaps. 5: none. |
| J5 | Misconception refuted | All four parts present: stated, called wrong, shown to fail, right model with why the wrong one tempts. | A side-by-side wrong versus right frame exists; the wrong model is not labelled wrong before it fails. | 1: absent or in passing. 5: all four parts, tied to the cold-open prediction. |
| J6 | Analogy bounded | Every "it's like", "think of", "imagine" has a turn stating where it breaks within 3 turns; at most one analogy per segment. | Analogy still shows mapping lines and a marked break. | 1: unbounded analogy. 5: mapped and bounded. |
| J7 | Retrieval present and spaced | At least 1 hold per 6 minutes; each a specific question at "understand" or above; "make sense?" does not count. | Holds of 6 to 8 s in `timing.json`; still during the hold shows the question without the answer. | 1: none, or recap only. 5: spaced holds with answers after. |
| J8 | Learner generates, no monologue | At least 2 LEARNER explain-backs of 25 words or more with a causal connective; no EXPERT run over about 50 words (`validate_script.py` W38 warns on back-to-back EXPERT turns over 60 words, a hold counted at 0.357 s per word); LEARNER at least 25% of words; no LEARNER praise of EXPERT. | Speaker rail never shows one speaker for over 30 s. | 1: expert lecture with "right?" prompts. 5: LEARNER builds and repairs the model. |
| J9 | Coherence, no seductive details | Every turn serves its segment's `learningGoal`; flag trivia, anecdotes and history not needed for the mechanism. | Each still has one focal object tied to the spoken line; no decorative motion. | 1: several detours. 5: none. |
| J10 | Artefacts force generation | `selftest.md` has 5 questions, at most 1 "remember"; cards are questions, not term clozes; `teachback.md` has a required-ideas list. Proxy test: give a fresh model only `transcript.md`; any self-test answer it can produce by copying one sentence marks that question as too shallow. | A retrieval card with an answer shows it only from its `answerAt` (build_manifest.py now requires one), after the hold. The final self-test card never shows an answer. | 1: missing or recall-only. 5: all specs met. |
| J11 | No label contradicts the scene | Every comparison, "wrong versus right" or verdict label in the outline `visualPlan` and `scenes.json` agrees with what the hosts say at that moment, including scenario flags ("fixed fleet", "one point per server"): a WRONG chip on a scheme the episode calls fine for a fixed fleet, or a "one neighbour" banner after a server gets 2 points, fails. | At each compare, verdict, banner and chip still, the label is true of the frame and of the words. Prefer counts ("moves 9 of 12") to verdict words. `qc.py` `labels.counts` computes X-of-Y counts, server counts ("5 to 6" over a mod 3 / mod 4 table) and "fixed fleet" against two-row compare tables; the judge brief lists what it checked, and the judge checks the rest. | 1: a label states the opposite of the scene. 5: every label is true where it shows. |

Readability while judging: read every still on the reference sheet that `brief.json` `viewing` names. `desktop` (the default): `qc/contact-sheet-720-NN.png`, frames at 1280 px as in a 720p player; the 360 px phone sheet is optional evidence and text under 36 px at 1080p or a grid over 8 cells per row is a warning (`text.phone`). `phone`: `qc/contact-sheet-phone.png`, and those findings are a blocker. Text under 28 px at 1080p fails in both (`text.minsize`). A label the judge cannot read on the reference sheet counts as not shown for J1, J4 and J11.

Redo loop: a failed criterion names the segment ids. Repair those segments only, per [qc.md](qc.md) section 7.

The judge must quote the turn behind each claim: the plain explanation, the turn where the misconception visibly fails, the repaired model and the transfer reasoning. A criterion with no quotable turn scores 2 or less.

What structure cannot prove. `validate_script.py` now hard-fails the missing learning actions it can see: no target length (E06), no prediction pause in the cold open (E25), no retrieval or explain-back pause after it (E23), no deep learner question (E15), no `onScreen` term at all (E07), no fact cited (E09), a misconception segment without a learner turn (E17), a circular "because" in a mechanism or misconception segment (E27), a mechanism segment with no turn that pairs a cause with a number, name or example (E28), a term named with no plain-words description before it (E29), a worked-example number shown but never said (E34), a core segment where every learner question is answered at once (E35) an explain-back pause after, not before, the host's explain-back (E37), and, since 3 Nov 2026 (codex round 3), a mechanism segment with fewer than 2 distinct causal connectives (E41), no plain definition (E42) or no worked number or named case (E43), and a misconception segment with no turn that names the wrong belief and refutes it (E44). These are errors only in mechanism and misconception segments. It warns on a circular "because" elsewhere (W26) and on a worked case with no general rule after it (W33; E33 with `requireGeneralRule`). The "mechanism works because it works" lesson now fails (tests/test_w8.py). A script can still pass every check and teach nothing: structure, the judge and the restate agent are proxies. The final measure is the learner's own self-test score on `learn/selftest.md`, taken after gate 3 without the video, with misses logged in `gaplog.md`.

What the score record cannot prove. The judge and the restater return JSON in their replies, and the building agent persists `qc/scores.json`. So the record cannot prove that independent agents wrote it. The parent stores each reply VERBATIM with its sha256, and `qc.py` checks that the recorded fields equal the JSON block inside each reply, that every cited turn and time exists in the episode, and that the restater's retrieval and transfer answers are kept with their citations. That makes an edited or invented record visible on review; it does not make one impossible.

## 11. Resolved decisions (2 Nov 2026)

- **Per-turn hold.** `holdAfterMs` and `pause` on a turn in `script.json` (`schemas/common.schema.json`), carried into `timing.json` by `tts.py` and into `episode.json` `holds[]` by `build_manifest.py`. The template shows `PauseCue`.
- **Role enum.** One enum of 15 roles in `schemas/common.schema.json`; `naming` became `terms`.
- **`learn/` folder.** `learn.json` in, `scripts/learn.py` out (section 8); fields in `library/index.json` (section 9).
- **Order.** Plain meaning first, then the term. `references/script.md` rule S7 follows this file; `explainer-pedagogy.md`'s "terms before the example" order no longer applies.
