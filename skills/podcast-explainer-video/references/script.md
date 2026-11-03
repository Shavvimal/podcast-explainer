# Script: pedagogy, outline pass, dialogue pass, validators

Load this file for workflow steps 1 to 4 (brief, facts, outline, dialogue). The rule ids S1 to S14 and V1 to V10 below come from the learning-science sources cited in [learning-design.md](learning-design.md), with [learning-design.md](learning-design.md) (rules L1 to L16, moves M1 to M9), TextToTalk's two-pass prompts and repair loop, and Google's Gemini 3.8 TTS prompting guide. Where the two rule sets differ, learning-design.md wins: plain meaning first, the term after it.

## Contents

1. Why the script looks like this
2. Hosts and personas
3. Pedagogy rules
4. Segment roles and the timed template
5. brief.json
6. facts.json: the claim ledger
7. Outline pass (prompt)
8. Dialogue pass (prompt)
9. Text rules for Gemini TTS
10. Validator checks
11. Minimal-repair loop (prompt)
12. A good excerpt

## 1. Why the script looks like this

Three findings drive every rule. First, the dialogue format does not teach by itself. Deep why and how questions from the learner host do (Driscoll 2003, Craig 2006). Second, a clear expository video can teach less than nothing, because a learner who thinks they already know the topic does not notice the gap. A dialogue that voices the misconception and breaks it nearly doubled test scores (Muller). Third, banter adds little. Predictions, questions and retrieval add a lot.

## 2. Hosts and personas

Two hosts, fixed roles. Speaker ids, voices and colours live in `brief.json` and are copied into `script.json`.

| Field | Learner host (default) | Expert host (default) |
|---|---|---|
| `id` | `host` | `guest` |
| `name` | Nia | Theo |
| `voice` | `Sulafat` | `Iapetus` |
| `role` | `learner` | `expert` |
| `side`, `color` | left, `#4F8CFF` | right, `#FFB020` |

**Learner host.** Stands in for the learner. Knows what the learner knows (`brief.json` `learner.knows`) and nothing more. Does not know the concept. Brings the naive model and states it as a confident prediction. Asks why, how, what-if and compare questions before each key step. Explains back in her own words and gets one detail corrected. Is curious and a little sceptical. Never praises the expert. Never says "great question", "fascinating" or "you explain that so well".

**Expert host.** Knows the concept and the sources. Socratic: answers in 1 to 3 sentences, then hands the turn back, often with a question. Breaks the misconception with a question before giving the right model. States where every analogy breaks. Corrects one detail after each explain-back. Never lectures for more than about 20 seconds. Says numbers only when they are in `facts.json`.

The default voices were chosen on 2 Nov 2026 from a 30-voice audition: `Sulafat` (Warm) for the learner and `Iapetus` (Clear) for the expert. To choose other voices, see [gemini-tts.md](gemini-tts.md) section 4. The learner can rename the hosts or change voices in the brief. Keep one learner and one expert. Default names start with N and T because the speaker badge shows an initial: hosts called Ava and Ben gave badges "A" and "B" that clashed with servers A and B on the concept world (2 Nov 2026). When renaming, pick initials that no label in the world uses (avoid A to D).

## 3. Pedagogy rules

- **S1 Deep questions.** Before each key explanatory step, the learner asks a why, how, what-if or compare question. At least one per 45 seconds of expert speech. "And then?" and "Right?" do not count.
- **S2 Misconception first.** The learner states the plausible wrong model as a prediction. The visual shows the wrong model without labelling it wrong. The expert asks the question that makes the prediction fail. Only then the right model. A script without a misconception segment fails validation.
- **S3 Explain back.** The learner explains back at least twice (after the mechanism and in the recap). The expert sharpens one detail each time.
- **S4 Match the learner.** Tie examples to the learner's world from `brief.json` `learner.worldExamples`. Skip what they already know.
- **S5 Short turns.** An expert turn is at most 3 sentences, about 20 seconds, 45 words (validator cap).
- **S6 Concrete before abstract.** Never open with a definition. Earn the abstraction with a worked example first.
- **S7 Plain meaning first, then the term (L3, M3).** Describe a part in everyday words first. Then name it: "That part, the one that does X, is called Y." After that turn, Y may appear in speech and on screen. A term used before its plain description is a jargon tripwire (M4): the other host asks "What do you mean by Y?" in the next turn. Term limits per depth: [depth.md](depth.md) section 1. This replaces the older "pre-train terms before the example" order.
- **S8 Analogy limits.** Every analogy states where it breaks, in the same turn or the next.
- **S9 Story arc.** Open on a puzzle, resolve it in the recap.
- **S10 One objective.** One `learningObjective` per episode. Several concepts make several episodes.
- **S11 Length.** Quick about 6 minutes. Longer depths follow `references/depth.md`.
- **S12 Retrieval.** End with one question that needs the mechanism, not a word recall. Then a hold (`holdAfterMs`, 6 to 8 s, with a `pause` cue), then a one-sentence answer.
- **S12a Prequestion (L1, L2).** The cold open asks the learner to predict, with a pause cue of kind `predict`. The prequestion targets the core idea of `learningObjective`, not a side fact, because prequestions help mainly the content they target.
- **S12b Spaced pauses (L10).** One retrieval pause every 5 to 6 minutes of episode: a turn with `pause` and `holdAfterMs`. `validate_script.py` warns (W23) after 6 minutes without one.
- **S13 No sycophancy, little filler.** At most one backchannel per 4 turns. No praise. No "stay curious" closer. No "so we've established".
- **S14 Write for the ear.** One idea per spoken sentence. Plan an outline at 150 words per minute (the planning default). Budget the script at the measured Gemini rate: 0.357 s per word, about 168 words per minute (`gemini-tts.md` section 13). `validate_script.py` uses the measured rate and subtracts holds from the time.
- **S15 Match prior knowledge (L7).** `brief.json` `learnerLevel`: `novice` keeps a `plain` segment and a second worked example. `familiar` (default) keeps the plain pass short. `near-expert` skips the `plain` segment and the worked-step scaffolding and gives that time to the misconception and a second pause (validator W24).
- **S16 Case, then rule (`requireGeneralRule`).** A worked case with numbers ends, in the same segment, with its general rule said aloud: a rule with a variable ("a new server takes about K over N of the keys"), or "in general ...", "on average ...". The case makes the rule believable; the rule is what transfers. The 2 Nov 2026 run stopped at "about a quarter, on average" and the restater had to guess "1 over N plus 1". Set `requireGeneralRule: true` on the outline segment that must end in a rule: the validator then fails it without one (E33); elsewhere it warns (W33).
- **S17 Say the case aloud.** Every key number and position of a worked example is spoken, not only shown: "B sits at 3 and at 7, A at 1 and 9". A number in `onScreen` that no host says in that turn or next to it fails in a `mechanism` or `example` segment (E34) and warns elsewhere (W34).
- **S18 Thinking time in the core step.** Tag the ONE segment with the core mechanism step `coreSegment: true` in the outline. In it, at least one learner question gets `pause {kind: "predict"}` and `holdAfterMs` 7000 before the expert answers (or the expert asks the core question with that pause and the learner answers after the hold, as in consistent-hashing v4 t16), so the learner works the step themselves (E35). In other mechanism segments an instant answer only warns (W35).
- **S19 Explain back before hearing it.** When the outline sets `explainBack: true` on a segment, the explain-back pause (`pause {kind: "explain-back"}`, `holdAfterMs` 7000 to 8000) sits on a turn BEFORE the host's explain-back turn, so the learner says it first and then hears it (E37).
- **S20 No hollow causes.** In `mechanism` and `misconception` segments a "because" that repeats its claim fails (E27), and a mechanism segment needs one turn that pairs a cause (because, so, which means, if, when) with a number, a name or an example (E28).

Signalling and coherence (V1, V2, V5) shape the script too, because `onScreen` and `visualPlan` are written here:

- **Signalling.** When a host names a part, that part lights up. Put the term in the turn's `onScreen` list, and the scene pass binds a highlight to the word.
- **Coherence.** Every visual event shows the point the narration makes at that moment. `visualPlan` names a state change, not a decoration.
- **No duplicated narration.** `onScreen` holds labels of 1 to 5 words that the host says, never the sentence. Full captions live in the caption track and the SRT sidecar, not in the scene.
- **No early reveal.** A number or conclusion appears on screen only when it is spoken.

## 4. Segment roles and the timed template

The role enum is defined once, in `schemas/common.schema.json` (`$defs.role`). `outline.schema.json`, `script.schema.json` and `validate_script.py` read it from there, and [learning-design.md](learning-design.md) section 4 says what each role does. The 15 roles:

| Role | Job | Learning-design section |
|---|---|---|
| `hook` | Cold open: puzzle, confident naive prediction, prediction pause | A |
| `puzzle` | A second puzzle, or the series question | A |
| `roadmap` | The 2 or 3 questions the episode answers | A |
| `plain` | The whole idea in everyday words, no terms | B |
| `example` | One worked example, a deep question before each step | C |
| `mechanism` | The causal steps, or the formal rule mapped onto the example | C |
| `terms` | Name parts that are already understood (M3) | D |
| `misconception` | Four-part refutation of the cold-open prediction (L8) | E |
| `analogy` | One analogy, mapped, with where it breaks | F |
| `transfer` | The model in a new context from the learner's world | G (transfer) |
| `compare` | Against a neighbour concept | G (interleave) |
| `scale` | Edge cases and limits | C |
| `check` | Retrieval question with a hold, then the answer | G |
| `recap` | The learner explains back; the expert sharpens one point | H |
| `selftest` | Hands the work to the learner: explain aloud, `learn/` files, next-time question | I |

Structure rules the validator enforces:

- The first role is `hook` or `puzzle`. Part 2 onwards of a deep series may open with `recap`.
- The last role is `check` or `selftest`. The recap comes either as its own `recap` segment just before it, or inside the last segment as a learner turn with `kind: "explain-back"` (the folded form).
- A `misconception` segment is required (in at least one part of a series).
- A `check` or `selftest` segment holds at least one question.

Order of a 6-minute episode (about 860 spoken words at the measured rate plus 2 holds). Scale every row in proportion for other lengths, but keep the prediction pause, the misconception beat and the closing retrieval at every length. The segment skeletons per depth are in [learning-design.md](learning-design.md) sections 5 to 7. This table is the beat order inside them.

| # | Beat | Time | Words | Drives | What happens | Segment role |
|---|---|---|---|---|---|---|
| 1 | Cold open: the puzzle | 0:00-0:35 | 70 | Learner | A surprising observation. The learner makes a confident naive prediction. A direct question to the learner with a 7 s `predict` pause. No definitions. | `hook` |
| 2 | Plain pass and worked example | 0:35-2:35 | 300 | Both | The whole idea in plain words (M1, M2), then one example step by step, a deep learner question before each step. No glossary terms yet. | `plain` or `example` |
| 3 | Naming | inside 3 or 4 | 40 | Expert | At most 3 terms in a quick episode (per-segment and per-episode limits in depth.md section 1), each attached to a part the learner already understands (M3). | `terms` (or inside `example`) |
| 4 | Misconception and conflict | 2:35-4:05 | 220 | Learner, then expert | The learner applies the cold-open prediction. The visual plays it out. The expert's question breaks it. The right model, and why the wrong one tempts. | `misconception` |
| 5 | Mechanism and analogy | 4:05-5:10 | 140 | Expert | The general rule, earned by the example. One analogy with its limit. A gap-check with a 7 s `retrieve` pause. | `mechanism` or `analogy` |
| 6 | Learner recap and self-test | 5:10-6:00 | 120 | Learner | 3 points in the learner's words. The expert sharpens one. The puzzle resolves. The learner is asked to explain it aloud; `learn/` is named. | `recap` + `check`, or `selftest` |

`validate_script.py` splits the word budget across segments by role weight (a folded last segment counts as recap plus check). Set `targetSec` on a segment to override its share.

Rhythm (optional `rhythm` field): `anchor` for the 1 or 2 core segments, `dense` for build-up, `breathing` for a short hand-off.

## 5. brief.json

Schema: `schemas/brief.schema.json`. Ask the learner only for what the request does not give. Defaults: `depth` and `minutes` from the one default in [depth.md](depth.md) section 2 (an explicit depth name in the request always wins), `learnerLevel` familiar, hosts from section 2, `audioMode` per-turn, model `gemini-3.8-flash-tts`. Set `learnerLevel` to `near-expert` when the concept sits next to what the learner already does (`learner.knows`), and to `novice` when they name it as new. Fill `learner.knows` and `learner.confusedBy` from the request ("I never got why the ring helps" goes in `confusedBy`). `learnerOutcome` is one thing the learner can do after watching. It becomes the retrieval question.

## 6. facts.json: the claim ledger

Schema: `schemas/facts.schema.json`. Write it before the outline. The outline and the dialogue may only state what the ledger holds.

- **Every number in a turn has a fact.** The validator extracts every digit token (`16`, `0.75`, `2^32` gives `2` and `32`) and every multiplier word (`hundred`, `thousand`, `million`, `billion`, `trillion`) and matches it against `facts[].numbers` of the facts the turn cites in `factIds`. Write numbers above ten as digits so the check can see them. Small counts in words ("two keys", "one fix") are free.
- **Three kinds of fact.** `sourced`: needs `sourceId` and a verbatim `quote` from that source. `arithmetic`: pure arithmetic on other facts, needs `derivedFrom` and `working` ("16 x 0.75 = 12"). Do not add assumptions. `illustrative`: an example value such as "a table of 100 keys", needs `label` ("Example data"), and the scene must show that label.
- **Sources.** A document the learner gave: `path`. A web page: `url` and `retrieved` date. If the concept needs facts beyond the given source, or there is no source, run the `firecrawl` skill (search, then scrape the 2 or 3 best pages) and record each URL with a verbatim quote. Never write a number from memory.
- **Negations.** Set `polarity: negative` on every not, never or no claim. The judge checks each one against its quote.
- **Misconceptions.** `misconceptions[]` holds the wrong model, the correction and the facts that break it. The outline's misconception segment uses one of them.
- **Analogies.** `analogies[]` holds each analogy with `breaksWhere`.
- **Open questions.** Ambiguities in the source go in `openQuestions[]`. Show them to the learner at gate 1.
- **One fact, one home.** A key number is the core point of one segment only (outline `ownedFactIds`). The recap and check may repeat it.

## 7. Outline pass (prompt)

Write `outline.json` (schema `schemas/outline.schema.json`) with this instruction to yourself. Then run `python3 scripts/validate_script.py <slug>/outline.json --facts <slug>/facts.json`.

```text
Write outline.json for one episode. Inputs: brief.json, facts.json, references/depth.md if depth is not quick.
- learningObjective: one sentence, the thing the learner can explain afterwards.
- conceptAngle: one sentence that names the persistent concept world (one diagram whose parts change state).
- misconception: the naive model the learner will voice, and its correction. Use facts.json misconceptions[].
- arc: one sentence, puzzle -> conflict -> resolution.
- segments: follow the skeleton for the depth in learning-design.md sections 5 to 7. For each segment:
  role from schemas/common.schema.json; title (at most 6 words, it becomes a chapter heading);
  learningGoal; keyQuestion = the deep why/how/what-if question the learner asks here;
  visualPlan = the state change on screen, not a decoration; ownedFactIds; newTerms (limits in [depth.md](depth.md) section 1);
  pauses = planned pause-and-think holds in this segment.
- Flags: coreSegment true on the ONE segment with the core mechanism step (S18); explainBack true on the segment
  where the learner explains it back (S19); requireGeneralRule true where a worked case must end in its rule (S16).
- Order: plain meaning first, then the term. A segment may name a term only after an earlier segment
  (or an earlier turn) described that part in plain words. Skip the plain segment if brief.learnerLevel is near-expert.
- Pauses: the hook's keyQuestion is the prequestion and must target the core idea of learningObjective;
  plan one retrieval pause every 5 to 6 minutes of episode.
- Rules: first role hook or puzzle; misconception segment present; last role check or selftest, with the recap
  as its own segment before it or named in the last segment's learningGoal;
  one key fact is the core of one segment only; no segment repeats another's core claim;
  do not spoil a later segment's number early; no definitions in the hook.
- Self-check before you answer: every field in its enum? every fact id in facts.json? every keyQuestion a why/how/what-if?
```

Human gate 1 shows the outline as a table (segment, role, title, keyQuestion, visualPlan, minutes), the misconception, and `facts.openQuestions`.

## 8. Dialogue pass (prompt)

Write the turns one segment at a time, in order, into `script.json` (schema `schemas/script.schema.json`). Copy `id`, `role`, `title`, `learningGoal`, `visualPlan` from the approved outline. Then add the turns.

```text
Write the turns for segment <segN> of script.json.
Context: brief.json (learner profile), facts.json, the approved outline (all segments),
the turns already written for earlier segments, and the titles of later segments.
- The learner asks the segment's keyQuestion (or a sharper version) before the expert explains.
- Plain words first. Name a term only after a turn has described that part in everyday words
  ("That part, the one that does X, is called Y."). If a host uses a term cold, the other host asks
  "What do you mean by Y?" in the next turn.
- Pauses: on the hook's prediction question and on each retrieval question, set holdAfterMs 7000 and
  pause {kind: predict | retrieve | explain-back, prompt: the question in at most 12 words}. The answer
  comes in the next turn, never in the pause turn. One pause every 5 to 6 minutes.
- The expert answers in 1 to 3 sentences, at most 45 words, then hands back.
- Use only numbers that are in facts.json and list their ids in factIds. Say every number and position you put
  in onScreen (S17). End a worked case with its general rule, said aloud (S16).
- coreSegment: give one learner question a predict pause and holdAfterMs 7000 before the answer (S18).
  explainBack: put the explain-back pause before the host's explain-back turn (S19).
- onScreen: 0 to 4 labels of 1 to 5 words each, each one spoken in this segment.
- Do not repeat a core claim of an earlier segment. Do not give a later segment's number early.
- No three turns in a row from one host. No praise. At most one backchannel per 4 turns.
- Text is verbatim speech: no stage directions, no "Name:" prefixes, no brackets, no markdown.
- Light disfluency is welcome ("Oh.", "Uh, so...", "Wait,") but not in every turn.
- Word budget for this segment: about <N> words at 0.357 s per word (validate_script.py prints a budget line for every segment on every run).
```

Then run the critique: read the whole script as the learner and check the section 3 rules the validator cannot see (does each key step have a deep question, does every analogy state its limit, does the recap resolve the opening puzzle). Add disfluencies last, after the fact check, so they do not hide errors.

## 9. Text rules for Gemini TTS

Gemini 3.8 reads `text` verbatim (source: Google's speech generation guide, https://ai.google.dev/gemini-api/docs/speech-generation). Delivery details are in `references/gemini-tts.md`.

- One turn = one part. The speaker comes from the `speaker` field. Never write `Nia:` or `Speaker 1:` in the text.
- No stage directions: `(laughs)`, `[excited]`, `*sighs*` are spoken aloud or are legacy tags. The validator fails them.
- Inline events only from this list, in angle brackets: `<laugh>`, `<chuckle>`, `<sigh>`, `<breath>`, `<gasp>`, `<cough>`, `<throat-clearing>`, `<short pause>`, `<long pause>`, `<tsk>`, `<exhales>`, `<whispers>`. Any other tag is read as text.
- Backchannels in pipes, 1 to 3 words, inside the active speaker's turn: `So it doubles |oh| and every key moves.` They render only in the experimental `--mode chunk --experimental` (a two-speaker request, not for delivery). In the default per-turn mode, write a reaction as its own short turn.
- Short turns. Split a long turn at a sentence boundary and put a learner question between the halves.
- Disfluencies are written as words: "Oh, uh, yeah", "hm", `...` and `--` for hesitation. CAPS for stress, sparingly.
- `style` is empty by default. If a host needs a delivery note, put one short constant string on `speakers[].style` and reuse it. Long style blocks cause voice drift.
- Say numbers the way a person would and keep them as digits: `0.75`, `16 buckets`, `2^32` becomes "2 to the 32" in text.

## 10. Validator checks

`python3 scripts/validate_script.py <slug>/script.json --facts <slug>/facts.json --minutes 6` prints numbered problems with segment and turn ids. Exit 1 on any error, 0 on warnings only. `--json` prints the same as JSON. `--max-turn-words` changes the cap (default 45). `--audio-mode chunk` stops the backchannel warning (chunk mode is experimental). Every run prints a `budget:` line with total words against the budget and words against budget per segment. `--brief` points at `brief.json` for the `learnerLevel` check; by default the validator reads `brief.json` next to the script when it exists. `--outline` points at `outline.json` for `coreSegment`, `explainBack`, `requireGeneralRule` and `newTerms`; by default the validator reads `outline.json` next to the script when it exists. `series.json --final` is the strict series check. The same command checks `outline.json`, `facts.json`, `brief.json` and a deep run's `<series-id>/series.json` (with every part folder) against their schemas. A clean result is necessary, not sufficient: structure cannot prove the episode teaches; the judge, the blind restater and in the end the learner's own self-test score decide that.

| Code | Level | Check |
|---|---|---|
| E00 | error | File missing or invalid JSON |
| E01 | error | JSON Schema (closed enums, required fields, no unknown fields) |
| E02 | error | One learner and one expert; every turn speaker is a known id |
| E03 | error | Duplicate segment, turn or fact id |
| E04 | error | Three turns in a row from one host (across segment boundaries too) |
| E05 | error | Turn longer than the cap (default 45 words) |
| E06 / W06 | error / warning | No target length (`--minutes` or `targetMinutes`) is an error. Total words more than 30% (error) or 15% (warning) off the budget: (minutes x 60 minus holds, the 250 ms gaps between turns, the 600 ms segment tails and the 250 ms lead) / 0.357 s per word. Segment words more than 60% off its role-weighted share (warning) |
| E07 | error | An `onScreen` term is not spoken in its segment; or no turn has any `onScreen` term |
| W07 | warning | An `onScreen` term has more than 5 words |
| E08 | error | A number in a turn (or in its `pause.prompt`, which the message names) has no fact, or the turn does not cite the fact that has it, or there is no `--facts` file |
| W08 | warning | A spelled number above ten (write digits) |
| E09 | error | A `factIds` or `ownedFactIds` entry is not in facts.json; or `--facts` is given and no turn cites any fact |
| E10 | error | A fact's `sourceId` or `derivedFrom` points nowhere; a source has neither url nor path |
| E11 | error | Stage directions, speaker prefixes, unknown `<tags>`, bad `|backchannel|` markup. A speaker prefix is a host name or id, or a generic label (Host, Guest, Speaker 2, Narrator), followed by a colon at the start of the text. A spoken colon such as "So the opening puzzle: ..." is fine |
| W11 | warning | Backchannel in per-turn mode |
| W12 | warning | A turn repeats a core claim of an earlier segment (content-word trigram overlap, recap and check exempt) |
| E13 | error | First role not hook or puzzle; last role not check or selftest; no recap (own segment or learner explain-back in the last segment); no misconception segment |
| W13 | warning | Series part: no misconception in this part, or the opening recap is not followed by a hook, puzzle, example or mechanism |
| W14 | warning | Learner praises the expert; more than one backchannel per 4 turns |
| E15 / W15 | error / warning | No deep learner question at all (error); fewer than one per 45 s of expert speech (warning) |
| E16 | error | A check or selftest segment has no question |
| W16 | warning | Learner speaks less than half of the recap |
| E17 | error | The misconception segment has no learner turn |
| E19 | error | Outline: one fact owned by two segments |
| W20 | warning | Outline: more new terms than the depth allows |
| E21 / W21 | error / warning | Depth rules: deep needs 2 or more check or selftest segments; a series part is at most 12 minutes; segment count per depth |
| E22 | error | A turn has `pause` but `holdAfterMs` is under 3000 |
| W22 | warning | A pause hold outside 6000 to 8000 ms (6000 to 15000 for `explain-back`); `holdAfterMs` without a `pause` cue; a pause turn without a question |
| E23 | error | No `retrieve` or `explain-back` pause (with a hold of 3000 ms or more) after the cold open |
| W23 | warning | More than 6 minutes of episode (speech at 0.357 s per word, plus gaps and holds) since the start or the last pause |
| W24 | warning | `learnerLevel` near-expert with a `plain` segment, or novice with no `plain` or `example` segment |
| E25 | error | The cold open has no `predict` pause |
| W25 | warning | The cold-open prequestion (outline keyQuestion, script pause prompt) shares no content word with `learningObjective` |
| W26 | warning | Circular explanation: the words after "because" repeat the claim before it (outside mechanism and misconception segments) |
| E27 | error | Circular explanation in a `mechanism` or `misconception` segment (S20) |
| E28 | error | A `mechanism` segment has no turn with a cause (because, so, which means, if, when) AND a number, a name or an example (S20) |
| E29 | error | No turn defines anything in plain words, or (with an outline) a `newTerms` term is named with no plain description in the 2 turns before it or the turn after (S7) |
| E30 / W30 | error / warning | Series: parts not numbered 1..n, slug not `<series-id>-p<N>`, or a part's `script.json` series fields disagree (error); a part folder not written yet (warning; error with `--final`) |
| E31 / W31 | error / warning | Series: hosts differ between parts (error); `glossary.json` differs or is missing in some parts (warning; with `--final` every part needs the same `glossary.json`: error); a malformed `glossary.json` (error) |
| E32 / W32 | error / warning | Series: a later part's world drops a node on screen at the end of the part before it, or changes its label, value or position (warning; error with `--final`); a malformed `scenes.json` or `episode.json` in a part (error). The end state is what the renderer DISPLAYS at the end of the part (W13a, Q01): it replays the part's resolved `episode.json` (or the `scenes.json` order) with the expiry rules, so a `set` value or label without `persist` has ended by then and must not be carried |
| E21 (series) | error | Series: fewer than 2 distinct retrieval checks across all parts (a check segment counts once; a `retrieve` pause counts only outside one), a part's measured audio over 12 minutes, a malformed `timing.json` or one without a positive `durationMs` and a turns list (never read as 0), a `timing.json` whose turn count differs from the part's script or whose `durationMs` is under 0.8 x words x 0.357 s (`{"durationMs": 1, "turns": []}` is not measured audio; W13a), or (with `--final`) a part without `timing.json` or with draft timing (scratch, chunk, estimated) |
| E33 / W33 | error / warning | A turn with 2 or more numbers (a worked case) and no later turn in the segment with a general rule (S16); error when the outline sets `requireGeneralRule` |
| E34 / W34 | error / warning | An `onScreen` number is not spoken in its turn or the turns next to it (S17); error in `mechanism` and `example` segments |
| E35 / W35 | error / warning | In the `coreSegment`, every learner question is answered at once with no `pause` and no `holdAfterMs` (error); in another `mechanism` segment, any such question (warning) (S18). A `predict` or `retrieve` hold on an expert question that the learner then answers also counts |
| E36 / W36 | error / warning | Outline: more than one `coreSegment` (error); none in a standard or deep outline (warning) |
| E37 | error | The outline sets `explainBack` and the segment has no explain-back turn, or no explain-back pause before it (S19) |
| E39 / W39 | error / warning | Predicted final length more than 15% (error) or 8% (warning) over the target: words x 0.357 s + pause tags + holds + 250 ms gaps + 600 ms segment tails + 250 ms lead (`pe_common.predict_length`). A series part (`series` set) predicted over 684 s (12 minutes minus 5% planning headroom) is also E39: the series check rejects measured audio over 12 minutes, and that is knowable before payment (W13a, Q08). `pe_common.length_check` is the one gate: `validate_script.py`, `tts.py --dry-run` (exits 1 on an error) and the paid `tts.py` run (refuses to start unless `--allow-over-length "<reason>"`, recorded in `timing.json` `lengthOverride`) all call it. The v5 script was 15.9% over and only the measured audio showed it |
| E40 | error | `brief.json` `lexicon`: an ASR alias that is a number, sign, negation or direction word, or a negating-prefix variant of its term (it would hide a meaning change from fidelity) |
| E41 | error | A `mechanism` segment uses fewer than 2 DISTINCT causal connectives across its turns (because, so, therefore, which means, as a result, leads to, if, then, unless ...): a mechanism chains at least two steps |
| E42 | error | A `mechanism` segment has no turn that defines its key term in plain words (means, is called, think of it as ...) |
| E43 | error | A `mechanism` segment has no worked example: no turn with a number or a named case (a specific server, key, person or object) |
| E44 | error | A `misconception` segment has no turn that refutes the learner's wrong belief: after the learner states it, a later turn must repeat its key words and say that it fails (not, doesn't, can't, wrong, actually ...). The lazy sample "How does the mechanism work? For example, Alice says mechanism means a process, so a result follows." in every turn fails E41 and E44 (tests/test_w11a.py) |
| E45 | error | No turn in a `mechanism` segment uses two domain terms: words of `outline.json` `newTerms` or of `facts.json` claims, quotes, misconceptions and concept (generic words such as mechanism, process, step, result do not count). The lesson must be about THIS concept (W13a, codex round 4 lazy lesson) |
| E46 | error | The `mechanism` segment's worked example (turns with a number or a named case) uses no number or name that occurs in `facts.json` or `outline.json`. Work the case the plan names, or add it to facts.json as illustrative data |
| E47 | error | No turn in a `misconception` segment shares two content words with the wrong belief in `outline.json` `misconception.statement` (else `facts.json` `misconceptions`). The longer lazy lesson "How does the mechanism work? For example, Alice says mechanism means a process because a step happens, so a result follows. That mechanism belief is not correct." fails E45, E46 and E47 (tests/test_w13a.py) |
| E48 / W48 | error / warning | A turn states a number or a rule word (always, never, only, every time, guaranteed, must) and cites no `factIds`: an error for an EXPERT turn in a `mechanism`, `example` or `misconception` segment, a warning elsewhere and for learner turns (judge v6: the t08 collision rule had no source). Pause turns and explain-back turns are exempt |
| W49 | warning | A turn says "always" or "never" with no scope words (with, in that, when, if, for a, under, unless, per ...); say where it holds ("with one point per server", "in that simulation"). Not counted (W14a): a question, a sentence about a named case (a server letter such as D, or "key 4"), and a same-input determinism statement ("the same name always gives the same number") |
| W38 | warning | Two or more EXPERT turns back to back with no LEARNER turn between (across segment boundaries too) total more than 60 words, counting each `holdAfterMs` on them as words at 0.357 s per word (an 8 s hold is 22 words). Insert a short learner turn or merge and cut (J8) |

Run it after every edit to `script.json`, including the learner's edits in the redo loop.

## 11. Minimal-repair loop (prompt)

If the validator exits 1, repair with a minimal edit. Do not regenerate. At most 3 attempts. If errors remain after 3, show the learner the numbered list and ask.

```text
validate_script.py found these problems in script.json:
<paste the numbered list>
Make the smallest change that fixes only the listed items. Keep every other turn exactly as it is,
including ids, wording, onScreen and factIds. If a number has no fact, either cut the number or add a
sourced fact to facts.json first (never invent one). If a turn is too long, split it at a sentence
boundary and give the learner a short question between the halves, with a new turn id.
```

Warnings do not block. Fix W12, W14, W15 and W26 when the fix is cheap, because they are the pedagogy failures the learner notices.

New turn ids: when a split needs a new id, use the next free number (`t13`) and keep the order in the array. Ids do not need to be consecutive. They must be unique, because audio files and timing are keyed by them.

## 12. A good excerpt

From `evals/files/sample-script.json` (hash maps). The learner predicts, the expert breaks it with a question, the learner finds the contradiction herself.

```json
{"id": "t03", "speaker": "host", "text": "Okay, so you hash the key into a number, and that number is the slot. So every key gets its own private slot, and nothing ever shares. Right?", "onScreen": ["hash"], "kind": "prediction"},
{"id": "t04", "speaker": "guest", "text": "Try it. The table starts with 16 buckets, and there are far more possible keys than that. What happens when two keys land in the same bucket?", "onScreen": ["16 buckets"], "factIds": ["f2"], "kind": "question"},
{"id": "t05", "speaker": "host", "text": "Oh. So no key gets a private slot: two keys can share one. Uh, so the bucket has to hold a short list, and the lookup checks that list. That's a collision.", "onScreen": ["collision"], "kind": "explain-back"}
```

A pause turn from the same file. The expert asks, `tts.py` inserts 7 s of silence after the turn, the video shows the prompt card with a countdown ring, and the answer comes in the next turn:

```json
{"id": "t11", "speaker": "guest", "text": "Your question. A table gets 100 keys that all have the same hash. Does doubling the table help?", "factIds": ["f7"], "kind": "question", "holdAfterMs": 7000, "pause": {"kind": "retrieve", "prompt": "100 keys, one hash: does doubling help?"}},
{"id": "t12", "speaker": "host", "text": "No. Doubling only separates keys whose hashes differ. Same hash, same bucket, so it's still a scan of 100 keys.", "factIds": ["f7"], "kind": "answer"}
```
