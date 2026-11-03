# Route recall pass (method of loci, used narrowly)

Read this file at the outline pass when the concept has a list of parts. Evidence and sources are cited inline (research date 2 Nov 2026).

## Contents

1. Verdict in one paragraph
2. When to switch it on (decision rule)
3. When to leave it off
4. Terms
5. Map the route to scenes.json
6. Script rules for the hosts
7. The route recall pass
8. Artefacts: route card and rebuild test
9. Checks
10. Test it on one episode

## 1. Verdict in one paragraph

Use narrowly. The method of loci improves recall of ordered, discrete items (pooled g = 0.65 over 13 trials, https://pubmed.ncbi.nlm.nih.gov/33535926/), mostly by fixing their order (https://profiles.wustl.edu/en/publications/the-effectiveness-of-four-mnemonics-in-ordering-recall/). No study shows it improves understanding or transfer, and full proficiency takes about 20 hours of practice (https://pmc.ncbi.nlm.nih.gov/articles/PMC5439266/). A supplied virtual route works as well as a familiar one (https://pubmed.ncbi.nlm.nih.gov/23098905/), but no study tests a viewer who only watches. So the skill does not teach the technique. It gives list-like episodes a fixed route through the concept world and ends them with a route recall pass. The pass is retrieval practice plus signalling plus a stable place per item, which all carry stronger evidence than the palace itself.

## 2. When to switch it on (decision rule)

Switch it on only if all four tests pass. "On" means `scenes.json` has a `world.route` and the closing segment runs the route recall pass. There is no outline flag: write "Route recall: on, because <reason>" (or "off, because ...") into the `visualPlan` of the recap, check or selftest segment, so the learner sees the decision at gate 1.

1. **Enumerable.** The concept has 4 to 9 discrete, named parts: steps, stages, layers, components, rules, failure modes.
2. **Recall matters.** the learner must recall the full set or its order later, not only the idea behind it.
3. **Order is natural or harmless.** The route follows the concept's own flow (data flow, time, call order), or the parts have no order and a left-to-right order contradicts no edge.
4. **One station per segment fits.** At least half of the content segments map to one station each.

On: compiler pipeline stages, OSI layers, TLS handshake steps, failure modes of a distributed lock. Off: why the CAP trade-off exists, how attention weights values, amortised O(1) inserts, a compare episode. Mixed: a mechanism episode with a pipeline inside it uses the route for the pipeline only and keeps a "trace the cause" retrieval question.

## 3. When to leave it off

- The content is causal or relational ("why", "what happens if"). A route encodes order, not cause. The mechanism lives in the world edges, and the retrieval check traces a cause.
- Fewer than 4 parts, or more than 9 in one part. For more than 9, use two routes in two series parts (`references/depth.md`).
- The route order would contradict an arrow in the world.
- A `quick` episode with only one content segment.

When it is off, the world still follows the normal visual rules in `references/visuals.md`. Nothing in this file applies.

## 4. Terms

- **route**: the ordered list of stations for one episode.
- **station**: one node, or one small group of nodes, that holds one or two items. Never more than two items per station (https://pmc.ncbi.nlm.nih.gov/articles/PMC12514325/).
- **anchor**: a small glyph in the station corner that relates to the item's meaning.
- **route recall pass**: the closing retrieval segment that revisits each station in route order with labels hidden.
- **route card**: the one-page artefact with the numbered route and a blank copy.

Never write "memory palace" on screen or in the dialogue.

## 5. Map the route to scenes.json

**Layout rules for `world.nodes`.**

1. Lay stations out along one reading direction: left to right, top to bottom, or along the edges. Spatial order helps recall only when the order of locations can be rebuilt (https://pubmed.ncbi.nlm.nih.gov/8884744/).
2. A station node never moves, never changes shape and never changes base colour across the episode. Stable places help recall, moved places do not (https://pubmed.ncbi.nlm.nih.gov/6210746/).
3. Give each station a distinct colour or shape so that two stations never look alike (https://www.nature.com/articles/s41539-022-00147-6).
4. No scenery: no rooms, buildings or backgrounds. Irrelevant decoration hurts learning (https://link.springer.com/article/10.1007/s10648-020-09522-4).

**Fields (in `schemas/scenes.schema.json`, drawn by `WorldScene.tsx`, checked by `build_manifest.py`, 2 Nov 2026).**

```json
{ "world": {
    "nodes": [ {"id":"lex","label":"Lexer","sublabel":"split","x":200,"y":400,"anchorImage":"icons/scissors.svg"} ],
    "edges": [ {"id":"e1","from":"lex","to":"parse","directed":true} ],
    "route": [ {"station":1,"nodes":["lex"],"segment":"seg02","anchor":"scissors","item":"splits text into tokens"} ] } }
```

- `world.route[]`: 4 to 9 ordered stations (schema `minItems` 4, `maxItems` 9). `station` is 1-based and must run 1..n in order. `nodes` lists 1 or 2 node ids. `segment` (`segNN`) is the segment that teaches the station. `anchor` (optional, at most 24 characters) is the glyph name. `item` is the one-line answer used in the recall pass and on the route card.
- `node.anchorImage`: an SVG or PNG under `img/` or `icons/` of the episode folder (schema pattern `^(img|icons)/[^/]+\.(svg|png)$`). `WorldScene` draws it 44 px in the node's top-right corner. `build_manifest.py` copies `img/` and `icons/` into `public/episodes/<slug>/` and fails if the file is missing.
- `build_manifest.py` fails when station numbers have a gap or run out of order, when a route node id is not in `world.nodes`, when a station's segment is not in `script.json`, or when a station's segment comes earlier in the script than the station before it.
- Nothing draws the route by itself. The route lives in where the nodes sit and in the world `steps` that visit them.

**Drive the route with world steps** (`references/visuals.md`):

- On arrival at a station: one step with `camera` centred on the station, `focus` set to its node ids, anchored to the turn where the learner host names it.
- The recall pass: one step per station in route order, with `set: {"<id>": {"label": "?"}}` and `focus` on the station. Then a second step 3 to 5 s later that restores the label with `set: {"<id>": {"label": "<original>"}}`. Give the learner's "What sits here?" turn `holdAfterMs` 3000 to 5000 so the silence is real audio, not a guess. A pause cue is optional here: the "?" labels are the prompt.

## 6. Script rules for the hosts

1. In each content segment the camera reaches that segment's station before the expert explains it.
2. The learner host names the station on arrival, in one short line: "So this is the lexer." Route talk is at most one sentence per segment.
3. The station name is the node label, word for word, every time. One name per thing.
4. A vivid image is allowed only for an arbitrary fact (a number, a name, a fixed order). For a meaningful fact, the explanation is the hook. Supplied images are as good as self-made ones (https://imagesrvr.epnet.com/embimages/pdh2/xap/xap24330.pdf).
5. The image relates to the meaning. No bizarre or comic images that need art.
6. Never say the route improves understanding. Never teach the technique, unless the concept is memory itself.

## 7. The route recall pass

It replaces or extends the episode's existing retrieval question (`references/script.md`). It does not add a second retrieval beat.

1. The camera pulls back to the whole world. All station labels show "?". Anchors stay visible as cues.
2. For each station in route order: the camera moves to it, the learner host asks "What sits here?", the video holds 3 to 5 s of silence, then the label returns and the expert answers in one sentence that uses the mechanism, not only the name.
3. Last beat: one "why" question that crosses two stations ("Why must the lexer run before the parser?"). This keeps one understanding check in the pass.
4. Length: about 6 to 8 s per station, so 30 to 70 s for 4 to 9 stations. Budget it in `targetSec` of the recap or check segment.

## 8. Artefacts: route card and rebuild test

**Route card.** Write `explainers/<slug>/out/route-card.png` (a 1920x1080 still of the world at the start of the recall pass, with numbered stations and labels shown) and `route-card.md`:

```markdown
# Route: <title>
1. Lexer (split) - splits text into tokens
2. Parser (tree) - builds the syntax tree
...
## Blank
1. ____ (split)
2. ____ (tree)
```

Render the still with `npx remotion still` at the recall-pass start frame. Link `route-card.md` from `learn/summary.md` under "Still open" or from the gap log, so it sits with the other learning artefacts. `transcript.py` does not read it.

**Rebuild test (optional).** the learner redraws the stations and arrows from memory on paper, then checks the card. Building a map beats studying one: g = 0.82 against 0.37 (https://www.sfu.ca/~jcnesbit/research/NesbitAdesope2006.pdf).

## 9. Checks

Add to QC when `scenes.json` has a `world.route` (the judge checks these from the stills; `build_manifest.py` already enforces the numbering, node and segment-order rules):

- Every route station appears in the world from its segment onwards and its x and y never change.
- Stations follow one reading direction, and no edge points backwards against the route.
- 4 to 9 stations, at most two items each.
- Each content segment has a camera step to its station before the expert's first explanatory turn.
- The recall pass visits every station in route order, holds at least 3 s with "?", then restores the label.
- The script names each station with its exact node label.
- `route-card.png` and `route-card.md` exist and list the same stations as `world.route`.

## 10. Test it on one episode

n = 1 is a pilot, not proof. It answers one question: is the route worth its cost for the learner?

1. Pick two concepts of similar size that pass section 2. Toss a coin: one gets the route and the route recall pass, the other gets the same world with a plain retrieval question.
2. Before each episode, the learner writes what they know for 2 minutes.
3. Right after, at 1 day and at 7 days, the learner does a 5-minute self-test without notes: list the parts (1 point per part, 1 per correct position), and answer 3 "why" questions written before the render (0 to 2 each).
4. Record the extra runtime seconds, the extra authoring minutes, and the learner's 1 to 5 rating of "this felt like clutter".
5. Keep the route as a default for list-like concepts if the 7-day list score is at least 2 points higher, the "why" score is not lower, and clutter is at most 2. Otherwise switch it off by default.

Cost to the learner: about 30 minutes across one week.
