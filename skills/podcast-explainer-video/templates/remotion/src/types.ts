// Types for public/episodes/<slug>/episode.json. The JSON Schema lives in the skill at
// schemas/episode.schema.json; build_manifest.py validates against it before sync.
// All times are integer milliseconds from the start of the episode audio.

export type WordSource = "asr" | "interpolated" | "estimated";

export type Word = {
  text: string;
  startMs: number;
  endMs: number;
  source: WordSource;
};

export type Speaker = {
  id: string;
  name: string;
  voice?: string;
  color: string;
  side: "left" | "right";
  role?: string;
  avatar?: string | null; // path relative to the episode folder; initials badge when absent
};

export type Turn = {
  id: string;
  speaker: string;
  segment: string;
  text: string;
  startMs: number;
  endMs: number;
  onScreen?: string[];
  holdAfterMs?: number; // silence inserted after the turn (pause-and-think hold)
  words: Word[];
};

export type PauseKind = "predict" | "retrieve" | "explain-back";

// One pause-and-think hold: the silence after a turn with holdAfterMs. The PauseCue shows the
// prompt card with a countdown ring from startMs to endMs when kind and prompt are set.
export type Hold = {
  turn: string;
  segment: string;
  holdMs: number;
  startMs: number;
  endMs: number;
  kind: PauseKind | null;
  prompt: string | null;
};

export type Segment = {
  id: string;
  role: string;
  title?: string;
  startMs: number;
  endMs: number;
};

export type SceneType =
  | "title"
  | "world"
  | "diagram"
  | "code"
  | "equation"
  | "recap"
  | "check"
  | "compare" // two panels side by side: wrong versus right, before versus after
  | "matrix" // W16: a score or weight grid between two sets of words (matrixLayout.ts)
  | "custom"; // props.component names a component in src/scenes/custom/index.ts

export type Scene = {
  id: string;
  type: SceneType;
  startMs: number;
  endMs: number;
  captions?: "on" | "off";
  enterLeadMs?: number; // build_manifest.py: the scene starts this much before its anchor (silence)
  enterMs?: number; // build_manifest.py: entrance fade length; 0 = cut; absent = ENTRANCE_MS
  props: Record<string, unknown>;
};

// W11b (R02): a structured count claim on a label (chip, banner or panel stat), the shape qc.py
// labels.counts reads (agreed with W11a). It counts columns of a compare table's two rows over the
// columns filled in both: "columns-changed" counts columns whose cells differ; "cells-changed-to"
// counts columns whose cells differ and whose second-row cell is `to`. `value` is the count the label
// states, `of` the denominator it states, `side` the table panel (default: a stat's own panel, else
// the only table panel). countClaim() in scenes/compareState.ts evaluates it.
export type CountClaim = {
  kind: "count";
  value: number;
  of: number;
  scope: "columns-changed" | "cells-changed-to";
  to?: string;
  side?: "left" | "right";
};

// A chip expires at the next visual step after it (chipFrames in overlayState.ts) unless persist.
export type Overlay = {
  id: string;
  type: "chip";
  startMs: number;
  endMs: number;
  props: { text: string; color?: string; persist?: boolean; claim?: CountClaim };
};

export type Camera = { x: number; y: number; zoom: number };

export type WorldNode = {
  id: string;
  label: string;
  sublabel?: string;
  value?: string;
  x: number; // centre, world units (build_manifest.py fills it for a ring node from pos or angle)
  y: number;
  pos?: number; // ring layout: position 0..positions-1 on the ring (fractions allowed)
  angle?: number; // ring layout: degrees clockwise from 12 o'clock (instead of pos)
  ringOffset?: number; // ring layout: radial offset from the ring line, world units (+ = outside)
  role?: "owner" | "item"; // ring layout: an item takes the colour of the next owner clockwise
  w?: number;
  h?: number;
  shape?: "box" | "pill" | "circle";
  color?: string;
  revealAtMs?: number;
  // W11b: `value` is a label for one state. It shows from the node's reveal until the next step on
  // its timeline, unless persist is true (then until a `set` changes it).
  persist?: boolean;
  anchorImage?: string; // glyph in the node corner (route station anchor), path under the episode folder
  // W13b, virtual nodes: an owner that is one of several points of one server. `virtualOf` names the
  // server (any id, usually the plain owner's); `point` is the subscript drawn after the label (A1,
  // A2), default the node's 1-based index among nodes with the same virtualOf. Colour defaults to
  // the named node's colour.
  virtualOf?: string;
  point?: number;
};

export type WorldEdge = {
  id: string;
  from: string;
  to: string;
  label?: string;
  dashed?: boolean;
  directed?: boolean;
  bend?: number; // perpendicular offset of the curve midpoint, world units
  revealAtMs?: number;
};

export type RingArc = { from: number; to: number; color?: string };

// A walk entry: an item id walks to its successor (the next visible owner clockwise on the ring as
// drawn now). The object form names the target; `to` must be the successor unless overshoot is
// true (a walk that passes the successor on purpose, drawn dashed), see walkPlan in worldState.ts.
export type WalkSpec = string | { item: string; to?: string; overshoot?: boolean };

// A set patch. value and label are text for one state: they expire at the next step on the same
// timeline unless persist is true. color is not text and stays.
export type SetPatch = { value?: string; label?: string; color?: string; persist?: boolean };

// W13b: marks a step draws (spotlight, highlighted arcs, the automatic change band with its moved
// outlines, tints, walk arrows). Each ends at the next step on its timeline unless the step that set
// it persists it; walk arrows also end at the end of their anchor turn.
export type MarkKind = "focus" | "focusEdges" | "arcs" | "change" | "tint" | "walk";
export const MARK_KINDS: MarkKind[] = ["focus", "focusEdges", "arcs", "change", "tint", "walk"];

export type WorldStep = {
  atMs?: number;
  at?: { turn: string; word?: string | null }; // the anchor as written (build_manifest.py keeps it)
  // W13b: true keeps every mark this step sets until a later step sets that mark again; a list keeps
  // only those kinds. Default: each mark ends at the next step.
  persist?: boolean | MarkKind[];
  // W13b: nodes the words of this step talk about. The renderer never dims them, and
  // focusProblems() warns when a focus would.
  speaksOf?: string[];
  focus?: string[];
  focusEdges?: string[];
  reveal?: string[];
  hide?: string[]; // nodes or edges fade out and stay hidden until a later reveal
  walk?: WalkSpec[]; // ring layout: an arrow walks clockwise from each item to its owner (until the next step or its turn's end)
  arcs?: RingArc[]; // ring layout: highlighted ranges in positions, inclusive; until the next step unless persist, [] clears
  freeze?: boolean; // ring layout: true holds item colours; false recolours (change arc, outlines)
  flow?: string[];
  pulse?: string[];
  set?: Record<string, SetPatch>;
  // Colour classes: {"warn": ["k3", "k7"], "bad": ["k4"]} draws a solid outline in that colour
  // (theme name accent, good, warn, bad, muted, text, or a #hex) around each node. Until the next
  // step unless persist; {} clears. Use it to split a set of items by what happened to them (moved to D vs between old servers).
  tint?: Record<string, string[]>;
  camera?: Partial<Camera>;
  note?: string;
};

export type RingSpec = {
  positions: number; // slots on the ring, e.g. 12 hash positions
  cx?: number; // centre, world units; default the world centre
  cy?: number;
  r?: number; // radius of the ring line; default 0.31 x min(width, height)
  ownership?: "clockwise" | "none"; // default "clockwise" when any node has role "owner"
  ownershipAtMs?: number; // items stay grey before this (resolved from ownershipAt); a walked item colours early
};

export type World = {
  width?: number;
  height?: number;
  layout?: "free" | "ring";
  ring?: RingSpec;
  camera?: Partial<Camera>; // partial cameras merge with the default {x: W/2, y: H/2, zoom: 1}
  nodes: WorldNode[];
  edges: WorldEdge[];
  route?: { station: number; nodes: string[]; segment: string; anchor?: string; item: string }[];
};

export type CaptionMode = "karaoke" | "pop" | "off";

export type Manifest = {
  version: 1;
  id: string;
  title: string;
  video: { fps: number; width: number; height: number; tailMs: number };
  audio: { src: string | null; durationMs: number; sampleRate?: number };
  speakers: Speaker[];
  segments: Segment[];
  turns: Turn[];
  holds?: Hold[]; // absent in manifests built before holds existed
  scenes: Scene[];
  overlays: Overlay[];
  world?: World | null;
  captions: { mode: CaptionMode; maxCharsPerSecond: number; minPageMs: number };
  rail: { waveform: boolean };
};

export type SceneProps<P> = P & {
  sceneId: string;
  sceneStartMs: number;
  sceneEndMs: number;
  fromFrame: number; // absolute frame where this scene's <Sequence> starts
  enter: boolean; // false when the previous scene shares this scene's visual (world -> world)
};
