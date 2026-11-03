# Visuals: the concept world, the claim-to-visual rule, scene types

Contents
- [1. Order of work](#1-order-of-work)
- [2. The concept-angle sentence](#2-the-concept-angle-sentence)
- [3. The persistent world](#3-the-persistent-world)
- [4. The claim-to-visual rule](#4-the-claim-to-visual-rule)
- [5. Scene-type catalogue](#5-scene-type-catalogue)
- [6. Write a bespoke scene](#6-write-a-bespoke-scene)
- [7. Three simulation paradigms](#7-three-simulation-paradigms)
- [8. Density limits](#8-density-limits)
- [9. Captions over diagrams](#9-captions-over-diagrams)
- [10. What not to do](#10-what-not-to-do)
- [11. Visible text: the function QC mirrors](#11-visible-text-the-function-qc-mirrors)
- [12. Stale labels: expiry, persist, migration](#12-stale-labels-expiry-persist-migration)
- [13. Marks expire too (W13b): spotlight, arcs, change band, tint, walk](#13-marks-expire-too-w13b-spotlight-arcs-change-band-tint-walk)

Sources: Mayer's multimedia principles (signalling, coherence, spatial contiguity), and the custom-scene patterns of https://github.com/znyupup/knowledge-explainer-skill and https://github.com/vibe-motion/remotion-code-motion-explainer (`KnowledgeWorld`). The schema is `schemas/scenes.schema.json`; anchors are in `manifest.md`.

## 1. Order of work

1. Write the concept-angle sentence.
2. Design the world: nodes, edges, positions. Render its full state as one still (every node revealed) and check it reads.
3. Walk the script turn by turn and give every claim a visible state change (section 4). Write it as a world step, or as a cut to another scene type only when the world cannot show it.
4. Place framing cards: title at the hook, recap and check at the end.
5. Build with `--placeholder-timing`, render the three hero stills (hook, hardest mechanism, ending) for gate 2.

Design the hero frame first, then the motion. A sequence of entrances does not add up to a good frame by accident.

## 2. The concept-angle sentence

One sentence that names the world the whole episode lives in: what the parts are and what moves between them. Put it in `scenes.json` as `conceptAngle` and show it to the learner at gate 2.

- Good: "A hash map is an address calculator: the key computes its own bucket, so lookup is arithmetic plus one jump."
- Good: "Attention is a weighted vote: each word asks a question, every word answers with a key, and the votes mix the values."
- Bad: "An overview of hash maps." (no parts, nothing moves)
- Bad: "Hash maps are like a library." (an analogy is a scene, not the world)

The nouns in the sentence become nodes. The verbs become edges, flows and value changes.

## 3. The persistent world

One diagram per episode, defined once at `scenes.json` top level as `world`, shown by every `world` scene. Steps from all world scenes form one timeline, so a node revealed in segment 2 is still there when segment 5 returns to the world. The camera continues from where it was. This keeps one visual invariant across the episode, which is what lets a muted viewer still follow.

World coordinates: default 1728 x 712 units, one unit = one pixel at zoom 1 (the stage size). `x`, `y` are node centres.

Node fields:

| Field | Meaning |
| --- | --- |
| `id` | unique; also the target of steps |
| `label` | up to 18 characters, 34 px bold |
| `sublabel` | up to 22 characters, 28 px, muted |
| `value` | up to 14 characters, mono, accent colour; change it with `set`. A label for the state at the node's reveal: it disappears at the next step unless `persist` (section 12) |
| `persist` | `true` keeps the node's own `value` after the next step |
| `x`, `y` | centre in world units |
| `w`, `h` | size; defaults box 280 x 120 (160 with a value), pill 260 x 88 (128 with a value, 160 with a sublabel AND a value; W16), circle 160. A pill also widens by h / 2 past its text, for its rounded ends. An explicit `h` too short for the label, sublabel and value fails `qc.py world.nodefit` |
| `shape` | `box` (default), `pill` (functions, operations), `circle` (tokens, items) |
| `color` | accent for focus ring and value |
| `revealAt` | anchor; default is the first step that names the node |
| `anchorImage` | `img/` or `icons/` SVG or PNG drawn 44 px in the top-right corner (route stations, `memory-palace.md`) |
| `virtualOf` | ring owner that is one point of a server (virtual node): names the server; the colour defaults to that node's colour, and the label draws with a point subscript (A1, A2) |
| `point` | the subscript of a virtual node; default its 1-based index among nodes with the same `virtualOf` |

Edge fields: `id`, `from`, `to`, `label` (up to 16 characters, drawn beside the line), `dashed`, `directed` (default true), `bend` (curve offset in units), `revealAt`. Edges draw on with `evolvePath` over 18 frames.

`world.route[]` (optional): route recall stations `{station, nodes, segment, anchor, item}`, numbered 1..n in segment order. `build_manifest.py` fails on a gap in numbering, an unknown node, or a station whose segment comes earlier in the script than the station before it.

Step fields (inside a world scene's `props.steps`):

| Field | Effect | Inherits to the next step? |
| --- | --- | --- |
| `at` | anchor (required) | |
| `reveal` | node or edge ids appear (if not yet visible) | stays revealed |
| `focus` | spotlight: these nodes get the focus ring; all others dim to 45 % | no: until the next step unless `persist` (section 13); `[]` clears |
| `focusEdges` | these edges turn accent and thicker | no, as `focus` |
| `speaksOf` | nodes the words of this step talk about: never dimmed while the step is current; `build_manifest.py` warns when a focus dims a node the words name (section 13) | no |
| `persist` | `true` keeps every mark this step sets (focus, focusEdges, arcs, change band, tint, walk) until a later step sets that kind again; a list such as `["arcs", "change"]` keeps only those | |
| `flow` | dots travel along these edges while the step is current | no |
| `pulse` | one ring pulse (700 ms) on these nodes | no |
| `set` | `{nodeId: {value?, label?, color?, persist?}}`; the value pops when it changes | `value` and `label` until the next step, then no value and the node's own label (never an older value); `persist: true` keeps them; `color` stays |
| `camera` | `{x, y, zoom}` centre and zoom; moves over 800 ms; any field may be left out | yes |
| `note` | a callout (up to 60 characters) at the stage top-left | no |
| `hide` | node or edge ids fade out and stay hidden until a later `reveal` (a server dies, a step is undone) | stays hidden |
| `walk` | ring layout: an arrow walks clockwise from each item and ends at its owner over 900 ms. An entry is an item id (ends at its successor) or `{item, to, overshoot?}`; `to` other than the successor fails the build and the render unless `overshoot: true` (drawn dashed red). One item may walk several times in one step (copies on the next servers) | no: until the next step or the end of its anchor turn, whichever is first, at least 1.5 s; `persist` keeps it |
| `arcs` | ring layout: `[{from, to, color?}]` highlighted slot ranges (inclusive), a band behind the items | no: until the next step unless `persist`; `[]` clears |
| `freeze` | ring layout: `true` holds item colours; `false` recolours them with the change arc | until the next `freeze` |
| `tint` | `{"<colour>": [node ids]}`: a solid 8-unit outline in that colour around each node; the colour is a theme name (`accent`, `good`, `warn`, `bad`, `muted`, `text`) or `#RRGGBB`; up to 4 colours. A tinted node shows its tint instead of the dashed moved outline | no: until the next step unless `persist`; `{}` clears |

`world.camera` may be partial (`{"zoom": 1.2}`): missing fields keep the default centre `{x: width/2, y: height/2, zoom: 1}`.

### Ring layout

Use it for anything cyclic: consistent hashing, a circular buffer, a round-robin scheduler, a token ring, a clock, modular arithmetic. Set `world.layout: "ring"` and `world.ring`; nodes with `pos` or `angle` sit on the circle, nodes with `x`, `y` stay free (rule boxes, counters). `build_manifest.py` writes `x`, `y` for every ring node, so QC geometry and the renderer agree.

| Field | Meaning |
| --- | --- |
| `ring.positions` | slots on the ring; `pos` runs 0..positions-1 clockwise from 12 o'clock |
| `ring.cx`, `ring.cy`, `ring.r` | centre and radius in world units; default the world centre and 0.31 x min(width, height) |
| `ring.ownership` | `clockwise` (default): each visible `item` takes the colour of the next visible `owner` clockwise (an item on the owner's slot belongs to it); `none` turns it off |
| `ring.ownershipAt` | anchor; items stay grey until this word (say the rule first). An item named in a `walk` before it colours when its walk ends |
| node `pos` or `angle` | slot, or degrees clockwise from 12 o'clock |
| node `ringOffset` | radial offset from the ring line; put owners about 92 units outside so they never touch the items. Every owner must use the same `ringOffset`, and every item the same one: each role sits on one circle, and the renderer stops with the reason otherwise |
| node `role` | `owner` (filled disc, 96 units, in its `color`) or `item` (disc, 72 units, owner's colour); labels are 42 units |

What the renderer does on its own, so scenes.json only states events:

- Every ring node sits at `pos x 360 / positions` degrees clockwise from 12 o'clock (or its `angle`) on its role's circle, so keys 3 and 9 are on the horizontal diameter as far out as 0 and 6. A clock face (a disc whose rim is the owner circle) sits behind the ring, so owners read as hour marks on one dial and the outline is round, not the "heart" that three owners on a bare ring made in the v3 to v5 judge rounds.
- An owner appears (`reveal`) or disappears (`hide`): only the items whose owner changed recolour, over 400 ms. A warm band covers the affected range (previous owner, changed owner], and each moved item gets a dashed outline. From W13b both end at the next step after the change, unless the step that caused it (the reveal, hide or `freeze: false` step) has `persist: ["change"]`; a later step that sets `arcs` always clears them. A first reveal that moves nothing shows no band.
- `freeze: true` before the change, `freeze: false` on the word that gives the answer: the server can appear while the learner predicts, and the recolour lands on the answer.
- `walk` draws the path the rule takes, to the successor on the ring as drawn at the step (even inside a freeze). With owners on an outer circle the arrow leaves the item outward, follows the owner circle clockwise and stops with its head on the owner's disc; no other visible owner lies between an item and its successor, so it crosses none. Before W11b the head stopped inside the ring at the owner's slot, next to a key, so "key 4 never gets as far as D" showed an arrow pointing at the D side.

Worked example (consistent hashing, 12 keys, servers A, B, C, then D joins at 9):

```json
"world": {
  "layout": "ring",
  "camera": {"x": 1000, "y": 356, "zoom": 1.15},
  "ring": {"positions": 12, "cx": 1150, "cy": 356, "r": 165, "ownershipAt": {"turn": "t12", "word": "Each server owns"}},
  "nodes": [
    {"id": "k0", "label": "0", "pos": 0, "role": "item"},
    {"id": "A", "label": "A", "pos": 2, "role": "owner", "ringOffset": 92, "color": "#5BD69A"},
    {"id": "D", "label": "D", "pos": 9, "role": "owner", "ringOffset": 92, "color": "#F2D16B"},
    {"id": "count", "label": "keys moved", "value": "0 of 12", "x": 560, "y": 500, "w": 460}
  ],
  "edges": []
}
```

```json
{"at": {"turn": "t10", "word": "Key 4 walks"}, "walk": [{"item": "k4", "to": "B"}]},
{"at": {"turn": "t16", "word": "lands at 9"}, "reveal": ["D"], "freeze": true, "pulse": ["D"]},
{"at": {"turn": "t17", "word": "Keys 7 and 8"}, "walk": ["k7", "k8"]},
{"at": {"turn": "t18", "word": "D takes"}, "freeze": false, "note": "D takes keys 7, 8 and 9"},
{"at": {"turn": "t20", "word": "3 changed owner"}, "set": {"count": {"value": "3 of 12", "persist": true}}},
{"at": {"turn": "t110", "word": "Keep walking"}, "walk": [{"item": "k4", "to": "C", "overshoot": true}]},
{"at": {"turn": "t44", "word": "B dies"}, "hide": ["B"], "freeze": true}
```

The `count` value persists because "3 of 12 moved" stays true until a later `set` replaces it; the overshoot walk shows replicas on the next servers past the successor.

Split the moved items when the claim is about where they went. In the 2 Nov 2026 judge round, "most went between old servers" had no picture. Tint on that word (in a world; in a compare table use the panel step's `cellTint`, for example `{"warn": {"mod4": [3, 7, 11]}, "bad": {"mod4": [4, 5, 6, 8, 9, 10]}}`):

```json
{"at": {"turn": "t38", "word": "between old servers"}, "tint": {"warn": ["k3", "k7", "k11"], "bad": ["k4", "k5", "k6", "k8", "k9", "k10"]},
 "note": "gold: to D (3). red: old to old (6)"}
```

Virtual nodes are more owner nodes with the same label and `virtualOf` (`A1` at 1, `A2` at 9, both `"label": "A", "virtualOf": "A"`): they take A's colour and draw as A1 and A2, with the subscript at 28 px or more. Hide the plain owners and reveal the virtual ones in one step with `arcs: []`, so the reset shows no change band.

Two points per server at the moment the words need it (judge v6, seg08 t110: "skipping extra points of a server already picked" was said over a one-point ring, where the rule cannot be seen). Switch to the two-point ring on that word and walk one key whose copies meet a repeated server:

```json
{"at": {"turn": "t110", "word": "skipping extra points"},
 "hide": ["A", "B", "C", "D"], "reveal": ["A1", "A2", "B1", "B2", "C1", "C2"], "arcs": [], "focus": [],
 "walk": ["k2", {"item": "k2", "to": "C1", "overshoot": true}, {"item": "k2", "to": "A2", "overshoot": true}],
 "tint": {"bad": ["B2"]}, "note": "2 points each: key 2 skips B2, B has a copy",
 "set": {"count": {"label": "copies of key 2", "value": "B, C, A"}}}
```

With A at 1 and 9, B at 3 and 7, C at 5 and 11, key 2's walk meets B1, C1, B2, A2: B2 is a second point of B, so the third copy goes to A. The red outline on B2 is the skip. Size: 12 items and up to 10 owners fit (the schema allows 48 nodes in the world, hidden ones included; keep about 32 or fewer on screen at once); `r` 165 with items 72 units across keeps 86 units between item centres. Inside a compare panel the numerals and owner letters draw at 32 px or more (`PANEL_RING_TEXT_PX`), and the discs grow to hold them up to the slot spacing. A free node inside the ring (a "hash ring" label at the centre) is drawn in a panel only when its label fits inside the item circle at 28 px; otherwise it would cover the numerals, so the panel title carries the name.

Layout rules: 4 to 12 nodes. Leave 140 units between node edges so edge labels fit. Read left to right or top to bottom in the order the mechanism runs. Keep the top-left 900 x 90 free for notes. Keep camera zoom between 0.9 and 1.6; above 1.6 the frame loses context, below 0.9 text drops under 30 px.

## 4. The claim-to-visual rule

Every spoken claim gets a visible state change, at its word. "Spoken buttons must be pressed, spoken values must change, spoken relationships must become visible." Write each claim as input state, action, result. Then pick the step that shows the result:

| The host says | Show it with |
| --- | --- |
| names a part ("the hash function") | `reveal` it, or `focus` it if already there |
| A turns into B, A sends to B | `reveal` the edge, `flow` along it |
| a value changes ("it doubles", "7391 mod 8 is 7") | `set` the node value at the word that states the result |
| zoom into a detail | `camera` to the detail; return when the detail is done |
| two things are the same, or collide | `focus` both, `pulse` the shared node |
| a set splits by what happened ("3 went to D, 6 moved between old servers") | `tint` each group in its own colour on the word, plus a `note` or panel `stat` that names the colours and counts |
| The learner's wrong model | `note` with the wrong model, then a later step that breaks it (`set`, `reveal` the missing edge) |
| a definition or formula | cut to an `equation` scene; come back to the world after |
| real code | cut to a `code` scene with line reveals on the words |
| a process with many identical steps | a bespoke scene (section 7) |
| a key term the learner should keep | a chip overlay on the term's word |
| scores or weights between two sets of words (attention, a confusion matrix, a mask) | a `matrix` scene: word headers, values, heat, a highlight on the word |

Timing rules:

- Anchor the step to the word that carries the claim, not to the turn start. State changes fire 3 frames early automatically. Results fire with zero lead: a check-card answer, a compare verdict, a panel `stat`, a table row or `fill`, so they never show before their word.
- A number, result or answer appears only when it is spoken. Never earlier. This matters most in the misconception segment. Anchor a number to the turn that speaks it, never to a summary turn before it: `qc.py labels.early` warns with both turn ids and the lead time (W15, W16), and fails under `--final` (W18). When the picture is meant to lead (a cold-open prompt, a recap count, the same quantity in other words), mark the step, banner or chip `earlyOk: "<reason>"`.
- The picture never freezes while the voice runs. In any 6 s of speech, at least one step should fire.
- Do not start three unrelated changes on one frame. Two at most, and they must be about the same claim.
- Each `onScreen` term in the script must have a visual event within 1.5 s of its turn. `build_manifest.py` warns otherwise; `--auto-chips` adds a chip.

## 5. Scene-type catalogue

Cards (`title`, `recap`, `check`) are for framing only. Everything else should live in the world where it can.

### title: `TitleScene`

| Prop | Type | Notes |
| --- | --- | --- |
| `title` | string, 60 | 96 px |
| `subtitle` | string, 90 | |
| `kicker` | string, 40 | small caps line above the title |
| `question` | string, 90 | the opening puzzle, shown on `questionAt` (default 1.5 s in) |
| `questionAt` | anchor | |

### world: `WorldScene` (the main scene type)

| Prop | Type | Notes |
| --- | --- | --- |
| `steps` | array of steps (section 3) | at least one |

### diagram: `DiagramScene`

For a picture that is not part of the world: an analogy, a side example, a pre-drawn figure.

| Prop | Type | Notes |
| --- | --- | --- |
| `title` | string, 48 | heading |
| `viewBox` | string | default `"0 0 1728 600"`: one unit = one pixel under a heading |
| `elements` | array, 60 | data-only SVG: `{id, kind: rect, circle, ellipse, line, arrow, path, polygon, text, x, y, w, h, r, rx, ry, x2, y2, d, points, text, fill, stroke, strokeWidth, fontSize (min 28), anchor, draw, dashed}` |
| `svg` | `diagrams/<name>.svg` | alternative to `elements`, for example a Mermaid diagram exported to SVG; reveal and highlight by element id |
| `steps` | `[{at, reveal: [ids], hide: [ids], highlight: [ids]}]` | elements never revealed are visible from the start; `hide` fades an element out for good (to move a part, hide the old copy and reveal a new one at the new place); a later `reveal` of a hidden element never shows it, and `build_manifest.py` warns (W16). To keep an element hidden until a later word, give it only that `reveal` step: an element with a reveal step is hidden until it; `highlight` recolours its elements and dims the rest to 65 % opacity |

Text never renders under 28 px: the scene raises a text element's font to `28 / scale` viewBox units when the `viewBox` is larger than the stage (a 5184-wide viewBox draws a 28-unit label at 28 px, not 9). An `svg` file is drawn as exported, so check its smallest label in a still.

`draw: true` on a line, arrow or path draws the stroke on instead of fading it in. A `text` element is centred on its `x` by default (`anchor: "middle"`); set `anchor: "start"` when `x` is the left edge, or the label overlaps whatever sits left of it.

An `svg` file is checked twice. `build_manifest.py` refuses it with an error, and at render time `src/svgSanitize.ts` stops the render with the file name. Both reject a `<script>`, a `foreignObject` or other HTML, an `on*` event attribute, an `href` or `src` that is not `#id`, any `url()` except `url(#id)`, a DOCTYPE or ENTITY, and an `@import`. Editor metadata (`inkscape:*`, `sodipodi:*`, `<metadata>`) is dropped. Export Mermaid with `htmlLabels: false` so labels are `<text>`.

CSS rules (N07, W8b). CSS escapes (`u\72l(`, `@\69mport`) are decoded before any check, and any escape at all fails the file. A `<style>` element may hold only plain rules `selectors { declarations }`: no at-rule (`@import`, `@font-face`, `@media`), no `!important` (dropped). A selector may use SVG element names, `#id`, `.class`, `[attr]`, `:pseudo` and combinators; a selector that names a non-SVG element (`div`, `body`, `html`) fails. The renderer rewrites every selector under the diagram's own wrapper id, so a rule can never reach captions, chips or other scenes. In `<style>` and in `style=""` only SVG paint and text properties survive (`fill`, `stroke*`, `opacity`, `font*`, `text-anchor`, `marker*`, `display`, `visibility`, `transform` and similar; the list is `CSS_PROPERTIES` in `src/svgSanitize.ts`); others are dropped silently. Mermaid's default stylesheet passes these rules.

### code: `CodeScene`

| Prop | Type | Notes |
| --- | --- | --- |
| `code` | string | the snippet; at most 11 lines show at once, the panel scrolls to keep the newest line in view |
| `language` | string | prism-react-renderer id: `python` (default), `javascript`, `typescript`, `tsx`, `go`, `rust`, `sql`, `bash`, `json`, ... |
| `title`, `filename` | string | heading and a file tab |
| `steps` | `[{at, lines: "4-6", focus: "5"}]` | `lines` reveals (cumulative); lines no step names are visible from the start; `focus` highlights and dims the rest, inherited until changed |

30 px JetBrains Mono, about 60 columns fit. Cut the code to the lines the hosts talk about.

### equation: `EquationScene`

| Prop | Type | Notes |
| --- | --- | --- |
| `title` | string, 48 | |
| `lines` | 1 to 5 of `{tex or text, note, at}` | KaTeX display mode at 60 px; `text` is a plain mono fallback; `note` is a short gloss at the right; earlier lines fade to 60 % when a new one appears |

### recap: `RecapCard`

| Prop | Type | Notes |
| --- | --- | --- |
| `title` | string, default "Recap" | |
| `points` | 1 to 4 of `{text (70), at}` | numbered; each on its cue |

### check: `CheckYourselfCard`

| Prop | Type | Notes |
| --- | --- | --- |
| `question` | string, 120 | |
| `options` | up to 4 strings | lettered A to D |
| `correct` | 0-based index | turns green at the answer cue; others dim; needs `answerAt` |
| `answer` | string, 90 | shown at `answerAt`, zero lead; needs `answerAt` |
| `answerAt` | anchor | required with `answer` or `correct`; a thinking bar runs until then |

Two variants (`learning-design.md` J10). An answered retrieval card has `answer` and/or `correct` with `answerAt`; the answer lands on its word. A final self-test card has only `question` (and `options`): heading "Your turn: answer aloud", no thinking bar, nothing revealed; the answer lives in `learn/selftest.md`. There is no time-based default: an answer without a cue never shows.

### compare: `CompareScene`

Two panels side by side: wrong versus right (misconception refutation), naive versus improved, before versus after. The judge in the 2 Nov 2026 consistent-hashing run asked for exactly this: mod N drawn on the same ring as the hash ring looked the same. Draw each scheme in the form that shows its mechanism: a table for an assignment formula, a ring or graph for a structure.

| Prop | Type | Notes |
| --- | --- | --- |
| `title` | string, 48 | optional heading above both panels |
| `left`, `right` | panel | see below |
| `verdict` | banner: `{text (60), winner: left, right or none, labels?, persist?, claim?, at}` | badge under the winning panel on its word (zero lead); only then do the panels turn green (right) and red (wrong) with a tag. Before it, both look neutral, so the verdict is never given away. It ends at the next step of either panel (the panels turn neutral) unless `persist: true` |
| `banners` | up to 6 banners | each replaces the verdict or the banner before it on its word (zero lead), and each ends at the next panel step unless `persist`. Use one as soon as the verdict stops being true: new `text`, `winner: "none"` to make both panels neutral again, `text: ""` to hide the badge |

Panel fields:

| Field | Type | Notes |
| --- | --- | --- |
| `title`, `tag` | string 30, string 12 | header; `tag` is a small pill ("naive", "before") |
| `kind` | `world`, `table` or `text` | |
| `world` | `"shared"` or a world object | kind world. `"shared"` draws the episode world and its panel `steps` join the global timeline, so the change persists into later scenes. A world object is local to the panel (same fields as `world`, ring layout included) |
| `camera` | partial camera | kind world; default fits the ring (or every node) to the panel. Free nodes outside the ring are not drawn in a ring panel |
| `columns`, `rows`, `valueColors` | strings up to 12 characters (W16: a cell widens past its square side to hold its text; the 28 px rule still refuses what cannot fit), up to 14 columns; up to 6 rows `{id, label (16), cells, at?}`; cell text -> colour | kind table. A row with `at` appears on its word. `valueColors` fills a cell by its text (owner colours). Every row has exactly one cell per column; the layout must keep text at 28 px (table limits below). `build_manifest.py` and the renderer reject either problem with the numbers |
| `lines` | up to 6 `{text (40), at?}` | kind text |
| `steps` | `[{at, ...}]` | world step fields (kind world, `tint` included), plus `stat` (34 characters, a result line in a pill under the panel, zero lead, until the panel's next step; the object form `{text, persist?, claim?}` keeps it with `persist: true` and carries a count claim; `""` clears), `title` and `tag` (replace the panel header from the word on, zero lead, inherited; `tag: ""` hides the pill), `marks` (`{rowId: [columns]}` dashed outlines, inherited, `{}` clears), `fill` (`{rowId: [columns] or "all"}`: a row named in any `fill` shows `?` in each cell until filled, so the learner can compute before the answer appears), `cellTint` (`{colour: {rowId: [columns]}}`, table only: a solid outline in a theme colour or `#RRGGBB` that replaces the dashed mark, inherited, `{}` clears; the table twin of a world `tint`, for "3 went to D, 6 moved between old servers") |

A table row without `at` and without `fill` is a plain row: it shows its cells from the scene start (fixed in W8b, N02; it used to crash the render).

Table limits (W11b, R01). `tableLayout.ts` tries every band count and keeps the one with the largest text; text is at most 36 px, shrinks to fit the cell and the longest cell or header string, and must stay at 28 px or more. Before W11b a 14-column, 6-row table under a title drew 13 px cells with 36 px text. Largest column count that fits (computed 3 Nov 2026 with `compareBodySize` and `tableLayout`; the schema caps columns at 14; 0 means no count fits):

| Longest cell or header text | Scene title | 1 row | 2 rows | 3 rows | 4 rows | 5 rows | 6 rows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 character | no | 14 | 14 | 14 | 14 | 14 | 14 |
| 1 character | yes | 14 | 14 | 14 | 14 | 14 | 14 |
| 2 characters ("10") | no | 14 | 14 | 14 | 12 | 12 | 12 |
| 2 characters | yes | 14 | 14 | 12 | 12 | 12 | 0 |
| 4 characters | no | 14 | 14 | 14 | 7 | 7 | 7 |
| 4 characters | yes | 14 | 14 | 7 | 7 | 7 | 7 |
| 6 characters ("99.97%") | no | 14 | 14 | 10 | 5 | 5 | 5 |
| 6 characters | yes | 14 | 10 | 5 | 5 | 5 | 5 |
| 12 characters | no | 8 | 6 | 4 | 2 | 2 | 2 |
| 12 characters | yes | 6 | 4 | 2 | 2 | 2 | 2 |

Rows 2 to 6 above were recomputed 3 Nov 2026 (W16) with 8-character row labels and wide cells: a cell is square for short text and widens up to the column room for long text, so 4-character tables now fit more columns than before W16. For a grid of word-to-word scores, use the `matrix` scene instead: it has the whole stage.

A 12-column table with headers 0 to 11 and two rows draws as 2 bands of 6 with 61 px cells and 36 px text. The error names the cell size, the text size and the largest column count that fits.

Row labels (W13b, codex round 4 stumble 5). The row-label column is `min(320, max(180, ceil(chars x 0.62 x 36)))` px for the longest row label, so "Before change" (13 characters) gets a 291 px column at 36 px and the cells share the rest. The label text is `min(cell text, floor(column / (0.62 x chars)))` px; a label that would draw under 28 px (19 characters or more) is refused by `tableProblems` with the label, the width it needs and the 320 px cap. Labels of 8 characters or fewer keep the old 180 px column, so the table above does not change. `build_manifest.py` and `qc.py` port the same formula (`tableLabelW`, `TableLayout.labelFont`).

Count claims (R02). A stat, banner or chip can carry `claim: {kind: "count", value, of, scope, to?, side?}`. Write its numbers as placeholders so the text cannot disagree with the claim: `"text": "{value} of {of} move to {to}"` draws "2 of 4 move to D" (W13b, codex Q05). A written "N of M" that differs from the claim, a bare number that is not the value, "none" with a value above 0 or "all" with a value below `of` stops the render and `build_manifest.py`; so does a placeholder without a claim. `scope: "columns-changed"` counts the columns whose two rows differ; `"cells-changed-to"` counts the columns that differ and whose second-row cell is `to`. `qc.py labels.counts` checks the claim against the table on the frames where the label shows, whatever the wording, so "2 of 4 move to D" is `{"kind": "count", "value": 2, "of": 4, "scope": "cells-changed-to", "to": "D"}`. Keep counts out of panel titles and tags: they are labels too, and QC reads them.

Banner `labels` (`{left?, right?}`, 16 characters each) replace the RIGHT / WRONG pills. A scheme that is fine in its own setting must not stay labelled WRONG: the 2 Nov 2026 judge marked down a mod-N panel that said WRONG next to "fixed fleet: mod is fine". Prefer evidence over a verdict word: `{"winner": "none", "labels": {"left": "moves 9 of 12", "right": "moves 3 of 12"}}`.

Worked example (mod N versus the ring, after the learner guessed "a quarter move"):

```json
{"id": "sc04", "type": "compare", "anchor": {"from": {"turn": "t33"}, "to": {"turn": "t43", "edge": "end"}},
 "props": {
  "left": {"title": "hash mod N", "tag": "naive", "kind": "table",
           "columns": ["0","1","2","3","4","5","6","7","8","9","10","11"],
           "valueColors": {"A": "#5BD69A", "B": "#C792EA", "C": "#FF7A7A", "D": "#F2D16B"},
           "rows": [{"id": "mod3", "label": "k mod 3", "cells": ["A","B","C","A","B","C","A","B","C","A","B","C"], "at": {"turn": "t34", "word": "with mod"}},
                    {"id": "mod4", "label": "k mod 4", "cells": ["A","B","C","D","A","B","C","D","A","B","C","D"], "at": {"turn": "t34", "word": "And mod 4"}}],
           "steps": [{"at": {"turn": "t34", "word": "with mod"}, "fill": {"mod3": [], "mod4": []}},
                     {"at": {"turn": "t35", "word": "5 mod 4"}, "fill": {"mod3": [5], "mod4": [5]}, "marks": {"mod4": [5]}},
                     {"at": {"turn": "t37", "word": "6, 7, 8"}, "fill": {"mod3": "all", "mod4": "all"}, "marks": {"mod4": [3,4,5,6,7,8,9,10,11]}},
                     {"at": {"turn": "t38", "word": "9 of 12"}, "stat": "moved: 9 of 12"}]},
  "right": {"title": "hash ring", "tag": "ring", "kind": "world", "world": "shared",
            "steps": [{"at": {"turn": "t33", "word": "3 of 12"}, "arcs": [{"from": 7, "to": 9}], "stat": "moved: 3 of 12"}]},
  "verdict": {"text": "Ring: 3 of 12 move. Mod N: 9 of 12 move.", "winner": "right",
              "labels": {"left": "moves 9 of 12", "right": "moves 3 of 12"}, "at": {"turn": "t38", "word": "The ring moved 3"}}}}
```

A later compare in the same episode (the robot fleet, seg07) changes its banner when a step makes it false:

```json
"verdict": {"text": "Ring: one stretch moves, from one neighbour", "winner": "none",
            "labels": {"left": "moves 8 of 12", "right": "moves 2 of 12"}, "at": {"turn": "t63", "word": "one neighbour"}},
"banners": [{"text": "2 points: 2 stretches, from 2 neighbours", "winner": "none",
             "labels": {"left": "moves 8 of 12", "right": "moves 4 of 12"}, "at": {"turn": "t64", "word": "twice the points"}}]
```

The banner fixes the 2 Nov 2026 judge finding: "one stretch, from one neighbour" stayed up after the new robot got 2 points and took keys from 2 neighbours.

`build_manifest.py` checks panel worlds like the episode world, `fill` and `marks` rows and columns, and warns when the verdict lands before any `stat` (show the evidence first).

### matrix: `MatrixScene`

W16 (W14b D08): a grid of scores between two sets of words, on the whole stage. Before it, an attention matrix had to be a text panel (no fill, no marks) or a 38-element hand-placed diagram.

| Prop | Type | Notes |
| --- | --- | --- |
| `title` | string 48 | optional heading |
| `rows`, `columns` | 1 to 12 strings of up to 12 characters each | the words; a repeated header is fine, but a highlight must name it by index |
| `cells` | `[[string 12]]`, one row per row header, one entry per column | values such as "0.81" or "-inf"; `""` leaves a cell blank. Optional |
| `heat` | `[[0..1]]`, same shape | optional heatmap: the cell background mixes toward a deep blue by its intensity; white text keeps 5.6:1 or more |
| `rowAxis`, `colAxis` | string 24 | optional captions ("query", "key") beside and above the headers |
| `steps` | `[{at, highlight: [{row?, col?}], note?, persist?}]` | `row` and `col` are a header text or a 0-based index; `{row, col}` marks a cell, `{row}` a row, `{col}` a column. The step's highlight and `note` (60 characters, under the grid) last until the next step; `persist: true` keeps the highlight to the scene end. Unmarked cells dim to 65 % while a highlight shows |

Every header and cell draws at one size: the largest that fits the longest header or cell in its column and 60 % of the row height, at most 40 px. Under 28 px the matrix is refused by `build_manifest.py` (and the renderer) with the body size, the text size and the largest column count that fits. With 5-character words and a title plus both axis captions, 8 rows of 12 columns fit; without them, 11 rows. With 12-character cells, 6 columns fit. All values and headers show from the scene start, so the stage is never empty; anchor the scene to the turn that introduces the grid. `qc.py text.minsize` reads the same layout (`pe_common.matrix_layout`), and the coverage replay lists every header, cell and the current note. Sample: `templates/remotion/sample-inputs/matrix/`.

```json
{"id": "sc05", "type": "matrix", "anchor": {"from": {"turn": "t20"}},
 "props": {"title": "Example attention weights", "rowAxis": "query", "colAxis": "key",
           "rows": ["brick", "fell", "it", "cracked"], "columns": ["brick", "fell", "it", "cracked"],
           "cells": [["0.70","0.10","0.05","0.15"], ["0.30","0.55","0.05","0.10"], ["0.81","0.07","0.04","0.08"], ["0.40","0.10","0.30","0.20"]],
           "heat": [[0.7,0.1,0.05,0.15], [0.3,0.55,0.05,0.1], [0.81,0.07,0.04,0.08], [0.4,0.1,0.3,0.2]],
           "steps": [{"at": {"turn": "t21", "word": "brick"}, "highlight": [{"row": "it", "col": "brick"}], "note": "it to brick: 0.81 (example data)"}]}}
```

### custom

`{"type": "custom", "props": {"component": "BucketFill", ...}}` renders a registered bespoke component (section 6). `props.worldSteps` (world step objects) puts a custom scene on the persistent world's timeline (section 6, "Continue the world").

### Overlays: keyword chips

`overlays[]` of `{id, type: "chip", anchor, props: {text (32), color, persist?, claim?}}`. Top-right row, at most three visible, 36 px. Use one for a term the learner should keep, not for every noun. A chip ends at the next visual step after its start (at least 700 ms on screen), because a chip that states a value is a label for one state. A term chip that stays true across steps sets `persist: true`; then it runs to its anchor's end.

## 6. Write a bespoke scene

Test: if the learner needs to see how it moves, and the world cannot show it with focus, flow and values, write a component. Examples: a bucket array filling, a sorting pass, a pendulum, a growth curve, a packet crossing layers.

1. Create `explainers/remotion/src/scenes/custom/<Name>.tsx` exporting `const <Name>: React.FC<SceneProps<<Name>Props>>`.
2. Register it in `src/scenes/custom/index.ts` (`CUSTOM_SCENES`). A missing registration fails the render with the exact file to create.
3. Wrap the content in `<Stage enter={enter} heading={title}>` from `../common` so it stays inside the stage and fades in like the others.
4. Cue times: props anchored with `at` (or `fooAt`) arrive as `atMs`. Convert with `cueFrame(atMs, fallbackFrame, fromFrame, fps)` from `src/time.ts`; it returns the local frame, 3 frames early. Give every cue a fallback so placeholder builds still render.
5. Take colours, fonts and sizes from `src/theme.ts`. Minimum text 28 px as rendered: if the component scales a group (a `viewBox`, a `scale()`), raise the font to `type.min / scale`.
6. Use it in scenes.json, build, then render a still at the entry, the middle and the last cue, and read the images.

Rules (Remotion renders frames out of order, in parallel tabs):

- Derive all state from `useCurrentFrame()`. No `useState` for motion, no `setTimeout`, `setInterval`, `requestAnimationFrame`, CSS transitions or keyframes.
- No `Math.random()`. Use `random("seed-" + i)` from `remotion`.
- Heavy computation goes in `useMemo` or at module level, never per frame.
- Data comes from props, and numbers come from the script and facts. Never invent a value to make the animation look good.

`src/scenes/custom/BucketFill.tsx` is the worked example (paradigm 3 below).

Coverage (`qc.py coverage`, `build_manifest.py` onScreen check) reads what the props say is visible at the word (section 11): strings and, for custom scenes, numeric props, each gated by its own `at` (or a sibling `xAt`). A number the component computes (a count, a load) is drawn but not counted. Put the number the host says in a prop with its `at`, or in a world node `value` via `set`, so QC can see it.

### Continue the world (shared state)

A custom scene that shows the concept world must continue it, not draw a fresh copy: one persistent world per episode (`SKILL.md` rule 8). Two parts:

1. Steps: put them in `props.worldSteps` (same fields as world steps). They join the global world timeline with the world scenes and with compare panels set to `world: "shared"`, and `build_manifest.py` validates them and uses them for default reveal times. A server hidden in a custom scene stays hidden when the next world scene starts.
2. Drawing: `const shared = useSharedWorld(fromFrame)` (from `../world/WorldScene`) returns `{world, timeline, nowMs}`; draw it with `<WorldCanvas world timeline nowMs width height camera? only? />`. `fitCamera(world, w, h)` (from `../CompareScene`) fits a ring to a box, and `ringInsetFilter(world)` hides free nodes laid out for the full stage. For derived state use the pure functions in `world/worldState.ts`: `visibilityAt`, `ownershipAt` (owners, moved items, change arcs), `nodeOverrides`.

`src/scenes/custom/RingLoad.tsx` is the worked example: the shared ring on the left, one bar per visible owner with the items it owns now on the right. The template sample `sample-inputs/ring/` (episode `sample-ring`) uses it between a ring world scene and a compare scene.

## 7. Three simulation paradigms

From the knowledge-explainer skill's custom scenes. Each turns "how it moves" into a pure function of the frame.

**1. Precomputed simulation.** Integrate the system once for all frames, then index by frame. For physics, queues, diffusion, gradient descent.

```tsx
const states = useMemo(() => {
  const out = []; let s = initial;
  for (let f = 0; f < totalFrames; f++) { for (let k = 0; k < 8; k++) s = step(s, 1 / (fps * 8)); out.push(s); }
  return out;
}, [totalFrames, fps]);
const s = states[Math.min(frame, states.length - 1)];
```

**2. Log-scale magnitude.** Map an exponential quantity to a log axis with labelled milestones, and pick the unit as it grows. For "how big does it get" (doubling, compound growth, orders of magnitude).

```tsx
const n = interpolate(frame, [cue, cue + 6 * fps], [0, 42], clamp);    // e.g. folds
const metres = 0.0001 * 2 ** n;
const y = interpolate(Math.log10(metres), [-4, 9], [stageBottom, stageTop]);
```

**3. Discrete process timeline.** Build the state after every step outside the render (a pure `buildTimeline(input)`), then show the step whose cue has passed. For algorithms, protocols, state machines. Bind each step to the word that names it.

```tsx
const timeline = useMemo(() => buildTimeline(buckets, inserts), [buckets, inserts]);
const cues = inserts.map((ins, i) => cueFrame(ins.atMs, 15 + i * 30, fromFrame, fps));
const visible = timeline.filter((p) => frame >= cues[p.step]);
```

## 8. Density limits

| Limit | Value |
| --- | --- |
| Focal objects at one time | 1 (2 when the claim compares them) |
| World nodes on screen | 12 at most; zoom in for detail. Ring layout: up to 12 items plus up to 10 owners |
| New elements per step | 3 at most |
| Steps per 6 s of speech | at least 1, at most 4 |
| Text on a node | label 18, sublabel 22, value 14 characters |
| Note | 60 characters, one at a time |
| Code | about 11 visible lines, 60 columns |
| Equation | 5 lines |
| Recap | 4 points of 70 characters |
| Chips | 3 visible, 32 characters each |
| Compare table | every row one cell per column; text 28 to 36 px (table limits, section 5) |
| Labels | a chip, banner, stat or node value lasts until the next step unless `persist` (section 12) |
| Marks | a spotlight, arc, change band, tint or walk arrow lasts until the next step unless the step persists it (section 13) |
| Smallest text | 28 px at 1080p, after every scale. Text under 28 px is a bug. World text (node labels, sublabels, values, edge labels) is raised to 28 / zoom units when a compare panel or a low camera zoom would shrink it, and diagram text likewise; a custom component must do the same for its own scaling |

## 9. Captions over diagrams

Research summary (`explainer-pedagogy.md` V5): full written text added to a busy diagram hurts learning, while short key-term labels help. The default `karaoke` captions sit in their own band below the stage, so they never cover the diagram. Still:

- For a dense world step with many labels, set `"captions": "off"` on that scene, or set `captions.mode` to `"off"` for the episode and rely on the SRT sidecar.
- Prefer node labels and chips (1 to 5 words) to captions for the terms that matter.
- `pop` mode flashes 1 to 3 words; it suits a slow, punchy turn, not explanation.

## 10. What not to do

- A new slide per point. Unrelated slides reset the viewer; keep the world and change its state.
- Decoration: background motion, particles, stock icons, music under dense explanation. Every moving thing must show the point being spoken.
- Revealing the answer, the number or the conclusion before the host says it.
- A frozen picture during a long turn.
- Labels in a legend. Put the label on the part.
- Static host portraits as the main visual. The badges are enough.
- Invented data: illustrative values must say so ("say the hash is 7391"), and real numbers must come from `facts.json`.
- Three unrelated animations on one frame.
- Times typed into scenes.json. Anchor to turns and words.
- CSS animations, `Math.random()`, timers (section 6).
- `TransitionSeries` or per-scene audio.
- Camera moves that leave the focused node off-screen. Check a still after every `camera` step.
- Two schemes drawn on the same picture. A viewer cannot tell mod N from the ring when both colour the same clock; use a `compare` scene with the form that fits each scheme.
- A custom component that redraws the world from scratch in each segment. Use `worldSteps` and `useSharedWorld`.

## 11. Visible text: the function QC mirrors

`src/visibleText.ts` exports two pure functions (no React, no theme): `sceneTextsAt(manifest, scene, nowMs, timeline?)` returns the texts one scene draws at `nowMs`, and `visibleTextsAt(manifest, nowMs)` returns the texts of every active scene plus the keyword chips. They replay the renderer's own state, using the same modules the renderer draws from (`world/worldState.ts`, `scenes/compareState.ts`, `frames.ts`), so they cannot drift from the picture. `scripts/pe_common.py visible_text` (QC coverage and auto-chips) mirrors them line for line; change both together.

Labels expire as in section 12: a node value at the next step on its timeline, a stat at its panel's next step, a banner at either panel's next step, a chip at the next visual step, each unless `persist`. `labelSourcesAt(manifest, nowMs)` returns the labels on screen with their source (`chip`, `banner`, `pill`, `stat`, `title`, `tag`), scene, side and any `claim`, for `qc.py labels.counts`.

Node labels and sublabels never expire (codex Q03): they are structure. So a quantity must never sit in a base label ("4 keys per server"); put it in `value` or `set`. From W13b `labelSourcesAt` also returns the node texts of world scenes and compare world panels, `{text, source: "node-label" | "node-sublabel" | "node-value", nodeId, expires}`, with `expires: false` for a base label and sublabel, so `qc.py labels.stale` can check them. A virtual node's label reads with its point ("A1"). `marksAt(manifest, nowMs)` returns the marks a world scene draws (focus, focusEdges, speaksOf, arcs, tint, walks, change band) after expiry; marks are not text, so `visibleTextsAt` is unchanged by section 13.

Rules, per scene type. Times are on the renderer's frame clock (`msToFrame(nowMs) - msToFrame(scene.startMs)`). A state change (reveal, hide, set, recap point, equation line, code line, diagram reveal, title question) counts from its cue frame, 3 frames before its word. A result (check answer, verdict and banners, panel stat, title and tag, table row and fill, text-panel line) counts from its word, zero lead. A step without a cue uses the renderer's fallback frame (15 + 45 x i; recap 12 + 30 x i; title question 45). Fades are ignored: a text counts from its cue until its hide cue.

| Scene | Texts |
| --- | --- |
| `title` | kicker, title, subtitle; question from its cue |
| `world` | the shared world at `nowMs` + 100 ms: label (after `set`, with a virtual node's point: "A1"), sublabel and value (after `set`) of every visible node, label of every visible edge (`reveal`/`hide` replayed), and the current step's note |
| `compare` | title; the current banner text and the pill labels (banner `labels`, else `right`/`wrong` for the winner); per panel the current title, tag and stat; table: the columns and, for each visible row, its label and the cells at exactly the indexes the renderer draws (`tableLayout` bands, `?` until filled); text: visible lines; world: as `world`, with the panel's own timeline (local) or the shared one, the ring inset filter at the panel's scale, and notes from that scene only |
| `recap` | title (default "Recap") and points from their cues |
| `check` | heading ("Check yourself", or "Your turn: answer aloud" with no answer), question, options; `answer` from `answerAt` |
| `equation` | title; `tex` or `text` and `note` of each line from its cue |
| `code` | title, filename; each non-blank line once revealed (lines no step names are visible from the start) |
| `diagram` | title; `text` of each element once revealed (elements no step names are visible from the start). An `svg` file contributes nothing |
| `custom` | with `worldSteps`: the shared world as `world` (ring inset filter); then every string and number in the props (not `component`, `worldSteps` or keys ending in `Ms`), an object hidden while its `atMs` is later than `nowMs`, a key `x` hidden while its sibling `xAtMs` is later |

## 12. Stale labels: expiry, persist, migration

The judge found a stale chip or label in the v3, v4 and v5 runs: "keys per server: 4 each" stayed after D took keys, and "points per server: 100 to 200" stayed beside "back to 2 points each". A label states the world at one moment, so from W11b the renderer expires it at the next step by default:

| Label | Shows from | Ends at (unless `persist: true`) |
| --- | --- | --- |
| world node `value` | the node's reveal | the next step on its timeline |
| `set` value or label | its step | the next step on the same timeline; then no value and the node's own label, never an older value |
| world `note` | its step | the next step (always; `note` has no `persist`) |
| panel `stat` | its word | the next step of the same panel |
| `verdict`, `banners[]` | its word | the next step of either panel; the panels turn neutral |
| chip overlay | its anchor | the next visual step after it (any scene's step, or a scene start), at least 700 ms |

A step counts even when it only moves the camera or the focus: the rule is mechanical, so the author decides what stays. Set `persist: true` only on a label that stays true through every later step until something replaces it: a term chip, a running count that a later `set` updates, a verdict that no later step contradicts. Panel titles and tags, node labels and sublabels, and edge labels are structure, not state, and never expire.

Migrating a scenes.json written before W11b (the template samples and the 3 Nov 2026 v5 consistent-hashing run):

1. Build and render as usual. Nothing fails, but a label that used to stay now disappears at the next step.
2. For each chip, banner, stat and node value, ask: is it still true at every later step until it is replaced? If yes, add `persist: true` (node: on the node or the `set` patch; stat: `{"text": ..., "persist": true}`). If no, leave it: the expiry is the fix.
3. Give each walk that must end at a named owner the object form `{"item": "k4", "to": "B"}`; a walk that passes the successor on purpose adds `"overshoot": true`.
4. Make every compare table row one cell per column and check the table limits above.
5. Rebuild, then view a still just after each step that used to carry a stale label.

The template samples were migrated this way: in `sample` (hash map) the `key`, `hash` and `index` values and the "bob" `set` patches persist, and the four term chips persist; in `sample-ring` the mod-N stat carries a count claim. In the v5 consistent-hashing scenes.json, `persist` suits the four term chips, the ring stat "moved: 3 of 12", the first sc04 verdict (true of the example until the "In general" banner replaces it), the running "entries" count in sc05 and the closing sc07 banner. "keys per server: 4 each" after D joins and "points per server: 100 to 200" beside "back to 2 points each" now end at the next step, as the judge asked.


## 13. Marks expire too (W13b): spotlight, arcs, change band, tint, walk

The v6 judge (3 Nov 2026) found three marks that outlived their words: at seg06 t105 (09:14) the gold change band and moved outlines from an earlier step stayed while the sorted list was counted; at seg03 t20 key 11's walk arrow from t19 stayed into the next turn; at seg03 t23 (03:45) the words said "a key on A cannot move" while C and D were spotlit and A was dimmed. From W13b a mark ends like a label:

| Mark | Shows from | Ends at (unless the step persists it) |
| --- | --- | --- |
| `focus`, `focusEdges` (spotlight) | its step | the next step on its timeline |
| `arcs` | its step | the next step |
| change band and dashed moved outlines | the ownership change | the next step after the change; a step that sets `arcs` always clears them |
| `tint` | its step | the next step |
| walk arrow | its step | the next step or the end of its anchor turn (plus the hold), whichever is first, at least 1.5 s |

`persist` sits on the step that sets the mark: `true` keeps all of its marks, a list keeps the named kinds (`focus`, `focusEdges`, `arcs`, `change`, `tint`, `walk`). A persisted mark stays until a later step sets that kind again (`[]` or `{}` clears). The camera still inherits. A step that repeats a spotlight across several steps (the sorted-list count in seg06) keeps working: each step sets its own focus.

`speaksOf: [ids]` on a step marks the nodes its words are about; the renderer never dims them while the step is current. `build_manifest.py` warns (never fails) when: a walk's item or target is dimmed by the focus at the walk; a `speaksOf` node is hidden; or a turn's words name a visible node by its label (a label with a capital letter, whole word, case-sensitive; "A new server" at a sentence start is English) while the focus at that word dims it. Fix a warning with a step on the word: put the node in `focus` or `speaksOf`, or set `focus: []`. The pure check is `focusProblems(manifest)` in `world/worldState.ts`.

Migrating a scenes.json written before W13b: build and render as usual, nothing fails, but a spotlight, arc, band or tint that used to carry over now ends at the next step. Read the `build_manifest.py` warnings, then for each mark ask whether it is still true at every later step until it is replaced; if yes, add `persist` with that kind on the step that set it.

Migration of the v6 consistent-hashing scenes.json (computed 3 Nov 2026 by replaying the timeline with old and new rules; applied in the W13b scratch build `e2e-v7-w13b`):

| Step (scene, turn, word) | Under the old rules it stayed until | Action |
| --- | --- | --- |
| sc03 t18 "D takes": change band, moved 7, 8, 9 | sc03 t21 "from one server" | `persist: ["change"]`: the band is what t19 and t20 count |
| sc03 t22 "stretch right behind": `arcs` 7 to 9 | sc03 t102 "Here that's" | `persist: ["arcs"]`: still the only stretch that moved |
| sc04c t43 "belongs to the ring" (shared panel): `arcs` | sc04c t103 "about 1 in N moves" | `persist: ["arcs"]` |
| sc05 t46 "they hit D": change band, moved 3 to 6 | sc05 t49 "double that neighbour's load" | `persist: ["change"]`: the band is what t47 and t48 count |
| sc05 t53 "The load splits": change band | sc05 t57 "100 to 200 points" | none: expiry is the fix |
| sc05 t104 "huge number": change band (B's points back) | sc05 t105 "Two points each" | none: this is the judge's 09:14 finding |
| sc05 t105 "A third point": change band | sc05 t105 "more memory" | none |
| sc08 t68 "joins or leaves": `arcs` 7 to 9 | sc08 t71 "learn folder" | none: it ends at "mod N" |
| sc08 t110 "next two distinct": focus B, D, C | sc08 t110 "skipping extra points" | replaced by the two-point pattern (section 3) |
| sc03 t10, t11, t19: walks | the next step | none: they now end at their turn's end (t19 "Key 11" 3.2 s earlier, the judge's t20 finding) |

Warnings `focusProblems` gives on the v6 scenes.json, and their fixes: t21 names A and B under focus C (add `{"at": {"turn": "t21", "word": "A and B"}, "focus": ["A", "B"]}`); t23 names A under focus C, D (add `{"at": {"turn": "t23", "word": "a key on A"}, "focus": ["A", "k1"], "walk": ["k1"], "speaksOf": ["D"]}`); sc08 t68 "next server clockwise" and t110 "Keep walking" walk k4 under focus B (add `k4` to the focus). With these changes the warning list is empty and the stills at t20, t23, t105 and t110 show the fixes.
