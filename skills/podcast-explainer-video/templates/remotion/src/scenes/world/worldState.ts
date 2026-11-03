// Pure functions that turn world steps into the world's state at a given time.
// The episode world is ONE persistent diagram: steps from every world scene, from custom scenes'
// `worldSteps` and from compare panels with `world: "shared"` form one global timeline, so a node
// revealed in scene s03 is still there when scene s07 returns to the world.
// A compare panel with its own local world uses the same functions on its own steps.
import type { Camera, Manifest, MarkKind, RingArc, Scene, WalkSpec, World, WorldNode, WorldStep } from "../../types";

// turnEndMs: end of the step's anchor turn plus its hold (walk arrows end there), when known.
export type TimedStep = WorldStep & { t: number; sceneId: string; turnEndMs?: number };

export const DEFAULT_W = 1728;
export const DEFAULT_H = 712;
const STEP_FALLBACK_MS = 1500;

export const worldSize = (world: World) => ({
  W: world.width ?? DEFAULT_W,
  H: world.height ?? DEFAULT_H,
});

// A03: a schema-valid partial camera ({"zoom": 1.2}) keeps the default centre.
export const initialCamera = (world: World): Camera => {
  const { W, H } = worldSize(world);
  return { x: W / 2, y: H / 2, zoom: 1, ...(world.camera ?? {}) };
};

// ------------------------------------------------------------------------------------ ring layout

export type RingGeometry = { cx: number; cy: number; r: number; positions: number };

export const ringGeometry = (world: World): RingGeometry | null => {
  if (world.layout !== "ring" || !world.ring) return null;
  const { W, H } = worldSize(world);
  return {
    cx: world.ring.cx ?? W / 2,
    cy: world.ring.cy ?? H / 2,
    r: world.ring.r ?? Math.round(0.31 * Math.min(W, H)),
    positions: world.ring.positions,
  };
};

// Degrees clockwise from 12 o'clock.
export const posToAngle = (pos: number, g: RingGeometry) => (pos * 360) / g.positions;

export const nodeAngle = (n: WorldNode, g: RingGeometry): number | null =>
  n.angle !== undefined ? n.angle : n.pos !== undefined ? posToAngle(n.pos, g) : null;

export const pointOnRing = (angleDeg: number, radius: number, g: RingGeometry) => {
  const a = (angleDeg * Math.PI) / 180;
  return { x: g.cx + radius * Math.sin(a), y: g.cy - radius * Math.cos(a) };
};

// Ring nodes get x, y from pos or angle (build_manifest.py writes the same numbers for QC).
export const placeNodes = (world: World): WorldNode[] => {
  const g = ringGeometry(world);
  // W13b: a virtual node takes the colour of the node it is a point of, unless it has its own.
  const byId = Object.fromEntries(world.nodes.map((n) => [n.id, n]));
  const nodes = world.nodes.map((n) =>
    n.virtualOf !== undefined && n.color === undefined && byId[n.virtualOf]?.color ? { ...n, color: byId[n.virtualOf].color } : n,
  );
  if (!g) return nodes;
  return nodes.map((n) => {
    const a = nodeAngle(n, g);
    if (a === null) return n;
    const p = pointOnRing(a, g.r + (n.ringOffset ?? 0), g);
    return { ...n, x: p.x, y: p.y };
  });
};

// In an inset view of a ring world (compare panel, custom scene), draw the ring nodes and anything
// inside the ring; free nodes laid out for the full stage would show clipped at the inset edge.
// W11b: with `scale` (px per world unit), a free node inside the ring is drawn only when its label
// fits inside the item ring at 28 px or more; otherwise it would cover the ring numerals.
export const ringInsetFilter = (world: World, scale?: number): ((n: WorldNode) => boolean) | undefined => {
  const g = ringGeometry(world);
  if (!g) return undefined;
  const inner = (() => {
    const item = world.nodes.find((x) => x.role === "item");
    const t = ringTracks(world).item ?? g.r;
    return 2 * (t - (item ? nodeSize(item).w / 2 : 0)) - 16;
  })();
  return (n: WorldNode) => {
    if (n.pos !== undefined || n.angle !== undefined) return true;
    if (Math.hypot(n.x - g.cx, n.y - g.cy) >= g.r) return false;
    if (scale === undefined) return true;
    const font = Math.max(34, 28 / scale);
    return Math.max(nodeSize(n).w, n.label.length * font * CHAR_W + 32) <= inner;
  };
};

// SVG arc along the ring from angle a0 to a1, clockwise.
export const ringArcPath = (a0: number, a1: number, radius: number, g: RingGeometry) => {
  let sweep = (((a1 - a0) % 360) + 360) % 360;
  if (sweep < 0.01) sweep = 359.99;
  const p0 = pointOnRing(a0, radius, g);
  const p1 = pointOnRing(a0 + sweep, radius, g);
  return `M ${p0.x} ${p0.y} A ${radius} ${radius} 0 ${sweep > 180 ? 1 : 0} 1 ${p1.x} ${p1.y}`;
};

// ------------------------------------------------------------------------------------ timelines

const stepsOf = (scene: Scene): { steps: WorldStep[]; local: boolean }[] => {
  const p = scene.props as Record<string, unknown>;
  if (scene.type === "world") return [{ steps: (p.steps as WorldStep[]) ?? [], local: false }];
  if (scene.type === "custom" && Array.isArray(p.worldSteps)) return [{ steps: p.worldSteps as WorldStep[], local: false }];
  if (scene.type === "compare") {
    return (["left", "right"] as const)
      .map((side) => p[side] as { kind?: string; world?: unknown; steps?: WorldStep[] } | undefined)
      .filter((panel) => panel && panel.kind === "world" && panel.world === "shared")
      .map((panel) => ({ steps: panel!.steps ?? [], local: false }));
  }
  return [];
};

// End of each turn's speech plus its pause-and-think hold, by turn id (walk arrows end there).
export type TurnEnds = Record<string, number>;
export const turnEnds = (manifest: Pick<Manifest, "turns">): TurnEnds =>
  Object.fromEntries((manifest.turns ?? []).map((t) => [t.id, t.endMs + (t.holdAfterMs ?? 0)]));

const timed = (s: WorldStep, i: number, sceneId: string, sceneStartMs: number, ends?: TurnEnds): TimedStep => {
  const turn = s.at?.turn;
  const end = turn && ends ? ends[turn] : undefined;
  return { ...s, t: s.atMs ?? sceneStartMs + i * STEP_FALLBACK_MS, sceneId, ...(end !== undefined ? { turnEndMs: end } : {}) };
};

// Every step that acts on the episode world, in time order. Steps without atMs (placeholder
// timing) fall back to the scene start plus 1.5 s per step.
export const buildTimeline = (manifest: Manifest): TimedStep[] => {
  const out: TimedStep[] = [];
  const ends = turnEnds(manifest);
  for (const scene of manifest.scenes) {
    for (const { steps } of stepsOf(scene)) {
      steps.forEach((s, i) => out.push(timed(s, i, scene.id, scene.startMs, ends)));
    }
  }
  return out.sort((a, b) => a.t - b.t);
};

// A local timeline (compare panel with its own world).
export const localTimeline = (steps: WorldStep[], sceneId: string, sceneStartMs: number, ends?: TurnEnds): TimedStep[] =>
  steps.map((s, i) => timed(s, i, sceneId, sceneStartMs, ends)).sort((a, b) => a.t - b.t);

// W13b: does this step keep a mark of this kind past the next step?
export const persists = (s: { persist?: boolean | MarkKind[] } | undefined, kind: MarkKind): boolean =>
  !!s && (s.persist === true || (Array.isArray(s.persist) && s.persist.includes(kind)));

// Shortest time a walk arrow stays, so it always finishes drawing and can be read.
export const WALK_MIN_MS = 1500;

// W13b, marks expire. focus, focusEdges, arcs and tint are a mark for one step: a step that omits
// one shows none (the mark ended at this step), unless the step that set it has persist (true, or a
// list naming the kind); then it stays until a later step sets that kind again. An empty array (or
// {} for tint) always clears. camera always inherits. flow, pulse and note belong to their own step.
// A walk arrow is drawn from its step until the next step or the end of its anchor turn (plus the
// hold), whichever is first, but at least WALK_MIN_MS; with persist it stays until a later step walks.
export type Resolved = {
  t: number;
  sceneId: string;
  focus: Set<string>;
  focusEdges: Set<string>;
  camera: Camera;
  flow: Set<string>;
  pulse: Set<string>;
  walk: WalkSpec[];
  walkAt: number; // time of the step that set `walk` (the arrow animates from it)
  walkUntil: number; // the arrow is hidden from this time (Infinity: until the next step)
  arcs: RingArc[];
  arcsSetAt: number; // time of the last step that set `arcs` (clears an automatic change arc)
  tint: Map<string, string>; // node id -> colour class (theme name or #hex)
  speaksOf: Set<string>; // never dimmed while this step is current
  note?: string;
};

export const resolveSteps = (timeline: TimedStep[], world: World): Resolved[] => {
  let focus = { v: new Set<string>(), keep: false };
  let focusEdges = { v: new Set<string>(), keep: false };
  let camera = initialCamera(world);
  let arcs = { v: [] as RingArc[], keep: false };
  let arcsSetAt = -Infinity;
  let tint = { v: new Map<string, string>(), keep: false };
  let walk = { v: [] as WalkSpec[], keep: false, at: -Infinity, until: Infinity };
  return timeline.map((s) => {
    if (s.tint) {
      const m = new Map<string, string>();
      for (const [cls, ids] of Object.entries(s.tint)) for (const id of ids) m.set(id, cls);
      tint = { v: m, keep: persists(s, "tint") };
    } else if (!tint.keep) tint = { v: new Map(), keep: false };
    if (s.focus) focus = { v: new Set(s.focus), keep: persists(s, "focus") };
    else if (!focus.keep) focus = { v: new Set(), keep: false };
    if (s.focusEdges) focusEdges = { v: new Set(s.focusEdges), keep: persists(s, "focusEdges") };
    else if (!focusEdges.keep) focusEdges = { v: new Set(), keep: false };
    if (s.camera) camera = { ...camera, ...s.camera };
    if (s.arcs) {
      arcs = { v: s.arcs, keep: persists(s, "arcs") };
      arcsSetAt = s.t;
    } else if (!arcs.keep) arcs = { v: [], keep: false };
    if (s.walk) {
      const keep = persists(s, "walk");
      const until = keep || s.turnEndMs === undefined ? Infinity : Math.max(s.turnEndMs, s.t + WALK_MIN_MS);
      walk = { v: s.walk, keep, at: s.t, until };
    } else if (!walk.keep) walk = { v: [], keep: false, at: -Infinity, until: Infinity };
    return {
      t: s.t,
      sceneId: s.sceneId,
      focus: focus.v,
      focusEdges: focusEdges.v,
      camera,
      flow: new Set(s.flow ?? []),
      pulse: new Set(s.pulse ?? []),
      walk: walk.v,
      walkAt: walk.at,
      walkUntil: walk.until,
      arcs: arcs.v,
      arcsSetAt,
      tint: tint.v,
      speaksOf: new Set(s.speaksOf ?? []),
      note: s.note,
    };
  });
};

// W13b: the automatic change band and the moved outlines show from the ownership change until the
// next step after it, unless the step at the change (the reveal, hide or freeze: false step) has
// persist "change" (or true); a later step that sets `arcs` always clears them.
export const changeVisible = (own: OwnershipState | null, timeline: TimedStep[], cur: Resolved | undefined, nowMs: number): boolean => {
  if (!own || own.changedAt === -Infinity || own.moved.size === 0) return false;
  if (cur && own.changedAt <= cur.arcsSetAt) return false;
  const causer = timeline.find((s) => s.t === own.changedAt);
  if (persists(causer, "change")) return true;
  return nextStepAfter(timeline, own.changedAt) > nowMs;
};

export const lastIndexAtOrBefore = (timeline: { t: number }[], nowMs: number) => {
  let idx = -1;
  for (let i = 0; i < timeline.length; i++) {
    if (timeline[i].t <= nowMs) idx = i;
    else break;
  }
  return idx;
};

// Time of the first step on the timeline strictly after t (Infinity if none).
export const nextStepAfter = (timeline: { t: number }[], t: number): number => {
  for (const s of timeline) if (s.t > t) return s.t;
  return Infinity;
};

// W11b, stale labels: node values, labels and colours after every `set` up to nowMs, with the time
// of the last text change. A patch's value and label are text for one state: they show from their
// step until the next step on the same timeline, unless the patch has persist: true. The latest
// patch that sets a value (or label) wins; once it expires the node shows no value (its own label),
// never an older value, which the newer one replaced. color is not text and stays.
export type NodeOverride = { value?: string; label?: string; color?: string; valueSet?: boolean; labelSet?: boolean; changedAt: number };

export const nodeOverrides = (timeline: TimedStep[], nowMs: number) => {
  const out: Record<string, NodeOverride> = {};
  for (const s of timeline) {
    if (s.t > nowMs) break;
    const live = nextStepAfter(timeline, s.t) > nowMs;
    for (const [id, patch] of Object.entries(s.set ?? {})) {
      const o = (out[id] ??= { changedAt: -Infinity });
      if (patch.color !== undefined) o.color = patch.color;
      const keep = live || !!patch.persist;
      if (patch.value !== undefined) {
        o.valueSet = true;
        o.value = keep ? patch.value : undefined;
      }
      if (patch.label !== undefined) {
        o.labelSet = true;
        o.label = keep ? patch.label : undefined;
      }
      if (keep && (patch.value !== undefined || patch.label !== undefined)) o.changedAt = s.t;
    }
  }
  return out;
};

// The label and value a visible node draws at nowMs. The node's own `value` is a label for the
// state at its reveal: it shows until the next step after the reveal unless the node has
// persist: true, and never after a `set` gave the node a value.
export const nodeTextAt = (
  n: WorldNode,
  vis: Vis | undefined,
  over: NodeOverride | undefined,
  timeline: { t: number }[],
  nowMs: number,
): { label: string; value: string | undefined } => {
  const label = over?.labelSet ? (over.label ?? n.label) : n.label;
  if (over?.valueSet) return { label, value: over.value };
  if (n.value === undefined) return { label, value: undefined };
  const since = vis?.on ? vis.since : -Infinity;
  const own = n.persist || nextStepAfter(timeline, since) > nowMs;
  return { label, value: own ? n.value : undefined };
};

// ------------------------------------------------------------------------------------ visibility

// Visibility of every node and edge at nowMs: shown from revealAtMs, then `hide` and `reveal`
// steps toggle it. `since` is the time of the last toggle (drives the fade in or out).
export type Vis = { on: boolean; since: number };

export const visibilityAt = (world: World, timeline: TimedStep[], nowMs: number): Record<string, Vis> => {
  const out: Record<string, Vis> = {};
  const items = [...world.nodes, ...world.edges];
  for (const x of items) out[x.id] = { on: false, since: -Infinity };
  // Initial reveals and step toggles as one event list.
  const events: { t: number; id: string; on: boolean }[] = [];
  for (const x of items) events.push({ t: x.revealAtMs ?? -Infinity, id: x.id, on: true });
  for (const s of timeline) {
    for (const id of s.hide ?? []) events.push({ t: s.t, id, on: false });
    for (const id of s.reveal ?? []) events.push({ t: s.t, id, on: true });
  }
  events.sort((a, b) => a.t - b.t || Number(a.on) - Number(b.on));
  for (const e of events) {
    if (e.t > nowMs) break;
    if (!(e.id in out)) continue;
    // A step reveal before the item's own revealAtMs is the same reveal; keep the earliest.
    if (e.on && out[e.id].on) continue;
    out[e.id] = { on: e.on, since: e.t };
  }
  return out;
};

// ------------------------------------------------------------------------------------ ownership

// Each visible item belongs to the first visible owner at or clockwise after it.
export const ownersAt = (nodes: WorldNode[], g: RingGeometry, vis: Record<string, Vis>): Record<string, string | null> => {
  const owners = nodes
    .filter((n) => n.role === "owner" && vis[n.id]?.on)
    .map((n) => ({ id: n.id, a: nodeAngle(n, g) }))
    .filter((o): o is { id: string; a: number } => o.a !== null);
  const out: Record<string, string | null> = {};
  for (const n of nodes) {
    if (n.role !== "item") continue;
    const a = nodeAngle(n, g);
    if (a === null || owners.length === 0) {
      out[n.id] = null;
      continue;
    }
    let best: { id: string; d: number } | null = null;
    for (const o of owners) {
      const d = (((o.a - a) % 360) + 360) % 360;
      if (best === null || d < best.d - 1e-9) best = { id: o.id, d };
    }
    out[n.id] = best!.id;
  }
  return out;
};

// Freeze intervals [start, end) from steps with freeze true / false, in time order.
export const freezeIntervals = (timeline: TimedStep[]): [number, number][] => {
  const out: [number, number][] = [];
  let open: number | null = null;
  for (const s of timeline) {
    if (s.freeze === true && open === null) open = s.t;
    if (s.freeze === false && open !== null) {
      out.push([open, s.t]);
      open = null;
    }
  }
  if (open !== null) out.push([open, Infinity]);
  return out;
};

// Ownership is computed at an effective time: inside a freeze it stays at the moment before the
// freeze began, so a server can appear while the learner predicts which keys move.
const effective = (t: number, freezes: [number, number][]) => {
  for (const [a, b] of freezes) if (t >= a && t < b) return a - 0.5;
  return t;
};

// Times at which ownership visibly changed, up to nowMs: owner reveals and hides outside a freeze,
// and the end of every freeze that held a change.
export const ownerChangeTimes = (world: World, timeline: TimedStep[], nowMs: number, freezes: [number, number][]): number[] => {
  const ownerIds = new Set(world.nodes.filter((n) => n.role === "owner").map((n) => n.id));
  const raw: number[] = [];
  for (const n of world.nodes) if (ownerIds.has(n.id) && n.revealAtMs !== undefined) raw.push(n.revealAtMs);
  for (const s of timeline) {
    if ([...(s.hide ?? []), ...(s.reveal ?? [])].some((id) => ownerIds.has(id))) raw.push(s.t);
  }
  const ts = new Set<number>();
  for (const t of raw) {
    const f = freezes.find(([a, b]) => t >= a && t < b);
    const at = f ? f[1] : t;
    if (at <= nowMs) ts.add(at);
  }
  return [...ts].sort((a, b) => a - b);
};

export type OwnershipState = {
  owners: Record<string, string | null>; // shown now (frozen inside a freeze)
  live: Record<string, string | null>; // the rule applied to the ring as drawn now (walks use this)
  before: Record<string, string | null>; // just before the last ownership change
  changedAt: number; // time of the last ownership change (-Infinity if none)
  moved: Set<string>; // items whose owner changed at changedAt (had an owner before)
  changeArcs: { a0: number; a1: number }[]; // (previous owner, changed owner] for each changed owner
  colouredFrom: Record<string, number>; // an item is grey before this time
};

export const ownershipAt = (world: World, nodes: WorldNode[], timeline: TimedStep[], nowMs: number): OwnershipState | null => {
  const g = ringGeometry(world);
  if (!g || world.ring?.ownership === "none" || !nodes.some((n) => n.role === "owner")) return null;
  const freezes = freezeIntervals(timeline);
  const visLive = visibilityAt(world, timeline, nowMs);
  const visNow = visibilityAt(world, timeline, effective(nowMs, freezes));
  const live = ownersAt(nodes, g, visLive);
  const owners = ownersAt(nodes, g, visNow);
  // Colouring starts at ownershipAtMs; an item walked earlier colours when its walk ends.
  const startAll = world.ring?.ownershipAtMs ?? -Infinity;
  const colouredFrom: Record<string, number> = {};
  for (const n of nodes) if (n.role === "item") colouredFrom[n.id] = startAll;
  for (const s of timeline) {
    for (const w of s.walk ?? []) {
      const id = walkItem(w);
      if (id in colouredFrom) colouredFrom[id] = Math.min(colouredFrom[id], s.t + WALK_MS);
    }
  }
  // Changes before colouring starts are not shown (the items were grey then).
  const changes = ownerChangeTimes(world, timeline, nowMs, freezes).filter((t) => t >= startAll);
  const changedAt = changes.length ? changes[changes.length - 1] : -Infinity;
  if (changedAt === -Infinity) return { owners, live, before: owners, changedAt, moved: new Set(), changeArcs: [], colouredFrom };
  const visBefore = visibilityAt(world, timeline, effective(changedAt - 0.5, freezes));
  const visAfter = visibilityAt(world, timeline, effective(changedAt, freezes));
  const before = ownersAt(nodes, g, visBefore);
  const moved = new Set(
    Object.keys(owners).filter((id) => before[id] !== null && before[id] !== owners[id] && colouredFrom[id] <= changedAt),
  );
  // Arcs: for every owner that appeared, (its predecessor in the new set, it]; for every owner that
  // disappeared, (its predecessor in the old set, it].
  const ownerNodes = nodes.filter((n) => n.role === "owner");
  const angleOf = (id: string) => nodeAngle(ownerNodes.find((n) => n.id === id)!, g) ?? 0;
  const changeArcs: { a0: number; a1: number }[] = [];
  for (const n of ownerNodes) {
    const was = visBefore[n.id]?.on ?? false;
    const is = visAfter[n.id]?.on ?? false;
    if (was === is) continue;
    const set = is ? visAfter : visBefore;
    const others = ownerNodes.filter((o) => o.id !== n.id && set[o.id]?.on);
    const a1 = angleOf(n.id);
    if (others.length === 0) {
      changeArcs.push({ a0: a1, a1 });
      continue;
    }
    let pred = others[0];
    let bestD = Infinity;
    for (const o of others) {
      const d = (((a1 - angleOf(o.id)) % 360) + 360) % 360;
      if (d > 1e-9 && d < bestD) {
        bestD = d;
        pred = o;
      }
    }
    changeArcs.push({ a0: angleOf(pred.id), a1 });
  }
  return { owners, live, before, changedAt, moved, changeArcs, colouredFrom };
};

export const WALK_MS = 900;

// ------------------------------------------------------------------------------------ walks

export const walkItem = (w: WalkSpec): string => (typeof w === "string" ? w : w.item);

export type WalkPlan = { item: string; successor: string | null; target: string | null; overshoot: boolean; ok: boolean };

// W11b, walk arrows: each walk ends at a named owner. The successor is the next visible owner
// clockwise on the ring as drawn at the step (live ownership, so a walk inside a freeze already
// sees a new owner). The arrow ends at `to` when given, else at the successor; `to` other than the
// successor is an error unless overshoot is true. The renderer draws the arrow to `target` and
// throws on !ok; build_manifest.py runs the same check before render.
export const walkPlan = (world: World, nodes: WorldNode[], timeline: TimedStep[], step: { t: number; walk?: WalkSpec[] }): WalkPlan[] => {
  const g = ringGeometry(world);
  if (!g || !step.walk?.length) return [];
  const live = ownersAt(nodes, g, visibilityAt(world, timeline, step.t));
  return step.walk.map((w) => {
    const item = walkItem(w);
    const successor = live[item] ?? null;
    const to = typeof w === "string" ? undefined : w.to;
    const overshoot = typeof w !== "string" && !!w.overshoot;
    const target = to ?? successor;
    return { item, successor, target, overshoot, ok: target !== null && (target === successor || overshoot) };
  });
};

// Every walk on a timeline whose arrow would end at a node other than the successor without
// overshoot, or with no owner at all, as messages (empty when all are fine).
export const walkProblems = (world: World, timeline: TimedStep[]): string[] => {
  const nodes = placeNodes(world);
  const out: string[] = [];
  for (const s of timeline) {
    for (const p of walkPlan(world, nodes, timeline, s)) {
      if (p.ok) continue;
      out.push(
        p.successor === null
          ? `walk of ${p.item} at ${Math.round(s.t)} ms (scene ${s.sceneId}): no visible owner on the ring, so the arrow has no end`
          : `walk of ${p.item} at ${Math.round(s.t)} ms (scene ${s.sceneId}) ends at ${p.target}, but its successor is ${p.successor}; ` +
            `point it at ${p.successor}, or set "overshoot": true if the walk passes ${p.successor} on purpose`,
      );
    }
  }
  return out;
};

// ------------------------------------------------------------------------------------ node geometry

export const NODE_DEFAULTS = {
  box: { w: 280, h: 120 },
  pill: { w: 260, h: 88 },
  circle: { w: 160, h: 160 },
} as const;
// Ring roles default to compact discs: owners 96, items 72 world units across, labels 42 units.
export const RING_DEFAULTS = { owner: 96, item: 72 } as const;

// Ring face: the clock-face disc behind a ring. Its rim is the owner track (owners sit on it like
// hour marks), or just outside the items when the world has no owner track.
export const ringFaceRadius = (world: World): number | null => {
  const g = ringGeometry(world);
  if (!g) return null;
  const t = ringTracks(world);
  const item = world.nodes.find((x) => x.role === "item");
  const itemEdge = (t.item ?? g.r) + (item ? nodeSize(item).w / 2 : 0) + 20;
  return t.owner !== null && t.owner > itemEdge - 20 ? t.owner : Math.max(g.r + 20, itemEdge);
};

// Approximate advance width of bold Inter or JetBrains Mono text, in font units per character.
export const CHAR_W = 0.62;

export const nodeSize = (n: WorldNode) => {
  if (n.role && n.shape === undefined) {
    const d = n.w ?? RING_DEFAULTS[n.role];
    return { w: d, h: d, shape: "circle" as const };
  }
  const shape = n.shape ?? "box";
  const d = NODE_DEFAULTS[shape];
  // A value line grows a box to 160 and a pill to 128; a pill with a sublabel AND a value grows to 160
  // (W16, W14b D15: at 88 the value drew over the sublabel and spilled out of the pill).
  const grow = n.value === undefined || shape === "circle" ? 0 : shape === "pill" ? (n.sublabel ? 160 - d.h : 40) : 40;
  const h = n.h ?? d.h + grow;
  return { w: n.w ?? d.w, h: shape === "circle" ? (n.w ?? d.w) : h, shape };
};

// Fit the ring (ring layout) or every node into the panel, so a shared 1728-wide world still
// draws at a readable size. A panel camera overrides any field.
export const fitCamera = (world: World, w: number, h: number, pad = 24): Camera => {
  const nodes = placeNodes(world);
  const ring = ringGeometry(world);
  const pick = ring ? nodes.filter((n) => n.pos !== undefined || n.angle !== undefined) : nodes;
  const list = pick.length ? pick : nodes;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const n of list) {
    const s = nodeSize(n);
    x0 = Math.min(x0, n.x - s.w / 2 - 14);
    x1 = Math.max(x1, n.x + s.w / 2 + 14);
    y0 = Math.min(y0, n.y - s.h / 2 - 14);
    y1 = Math.max(y1, n.y + s.h / 2 + 14);
  }
  if (ring) {
    // the clock face is the ring's outline: fit it whole
    const face = (ringFaceRadius(world) ?? ring.r) + 4;
    x0 = Math.min(x0, ring.cx - face);
    x1 = Math.max(x1, ring.cx + face);
    y0 = Math.min(y0, ring.cy - face);
    y1 = Math.max(y1, ring.cy + face);
  }
  const { W, H } = worldSize(world);
  const fit = Math.min(w / W, h / H);
  const scale = Math.min((w - 2 * pad) / (x1 - x0), (h - 2 * pad) / (y1 - y0));
  return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, zoom: scale / fit };
};

// Scale (rendered px per world unit) of a world drawn in a w x h box with this camera.
export const viewScale = (world: World, w: number, h: number, camera: Camera) => {
  const { W, H } = worldSize(world);
  return Math.min(w / W, h / H) * camera.zoom;
};

// W11b: the points of a walk arrow, from the item's edge to the target owner's edge. With owners on
// an outer track (ringOffset), the arrow leaves the item outward, follows the owner track clockwise
// (no other visible owner lies between an item and its successor, so it crosses none) and stops at
// the target disc. With owners on the ring line, it runs inside the ring and turns out to the owner.
export const walkPoints = (
  plan: WalkPlan,
  nodes: WorldNode[],
  ring: RingGeometry,
  tracks: { owner: number | null; item: number | null },
): { x: number; y: number }[] | null => {
  const item = nodes.find((n) => n.id === plan.item);
  const owner = nodes.find((n) => n.id === plan.target);
  if (!item || !owner) return null;
  const a0 = nodeAngle(item, ring);
  let a1 = nodeAngle(owner, ring);
  if (a0 === null || a1 === null) return null;
  while (a1 < a0 - 1e-6) a1 += 360;
  const itemR = tracks.item ?? ring.r;
  const ownerR = tracks.owner ?? ring.r;
  const ih = nodeSize(item).w / 2;
  const oh = nodeSize(owner).w / 2;
  const pts: { x: number; y: number }[] = [];
  const arc = (from: number, to: number, r: number) => {
    const n = Math.max(1, Math.ceil(Math.abs(to - from) / 3));
    for (let k = 0; k <= n; k++) pts.push(pointOnRing(from + ((to - from) * k) / n, r, ring));
  };
  if (ownerR - itemR >= ih + oh - 10) {
    const stop = (Math.asin(Math.min(1, (oh + 12) / ownerR)) * 180) / Math.PI;
    const end = a1 - stop;
    if (end <= a0 + 0.5) {
      // owner on (or next to) the item's own slot: one radial arrow from the item to the owner
      pts.push(pointOnRing(a0, itemR + ih + 4, ring), pointOnRing(a1, ownerR - oh - 8, ring));
      return pts;
    }
    pts.push(pointOnRing(a0, itemR + ih + 4, ring));
    arc(a0, end, ownerR);
    return pts;
  }
  const inner = itemR - ih - 18;
  pts.push(pointOnRing(a0, itemR - ih - 4, ring));
  arc(a0, a1, inner);
  pts.push(pointOnRing(a1, ownerR - oh - 8, ring));
  return pts;
};

// ------------------------------------------------------------------------------------ ring checks

// W11b, true circle: ring nodes sit at angle pos x 360 / positions (or their declared angle) on
// one circle per role, so every owner shares one ringOffset and every item shares one. Mixed
// offsets bend the ring (the v5 "heart"). Returns messages; the renderer throws on any.
export const ringProblems = (world: World): string[] => {
  if (!ringGeometry(world)) return [];
  const out: string[] = [];
  for (const role of ["owner", "item"] as const) {
    const offs = new Set(world.nodes.filter((n) => n.role === role && (n.pos !== undefined || n.angle !== undefined)).map((n) => n.ringOffset ?? 0));
    if (offs.size > 1) out.push(`ring ${role} nodes use ringOffset ${[...offs].join(", ")}; give every ${role} the same ringOffset so they sit on one circle`);
  }
  return out;
};

// Radius of each role's track (the circle its nodes sit on); null when the world has none of it.
export const ringTracks = (world: World): { owner: number | null; item: number | null } => {
  const g = ringGeometry(world);
  const of = (role: "owner" | "item") => {
    const n = world.nodes.find((x) => x.role === role && (x.pos !== undefined || x.angle !== undefined));
    return g && n ? g.r + (n.ringOffset ?? 0) : null;
  };
  return { owner: of("owner"), item: of("item") };
};

// ------------------------------------------------------------------------------------ virtual nodes

// W13b: the subscript point number of a virtual node (A1, A2): its own `point`, else its 1-based
// index among the nodes with the same virtualOf, in world order; undefined for a plain node.
export const pointOf = (n: WorldNode, nodes: WorldNode[]): number | undefined => {
  if (n.point !== undefined) return n.point;
  if (n.virtualOf === undefined) return undefined;
  return nodes.filter((x) => x.virtualOf === n.virtualOf).findIndex((x) => x.id === n.id) + 1;
};

// The text a node's label line shows: the label plus the point subscript ("A" + "1" reads "A1").
export const labelWithPoint = (label: string, n: WorldNode, nodes: WorldNode[]) => {
  const p = pointOf(n, nodes);
  return p === undefined ? label : `${label}${p}`;
};

// ------------------------------------------------------------------------------------ marks for QC

// W13b: the marks a world draws at nowMs, after expiry (what the renderer shows; QC mirrors it).
export type WorldMarks = {
  focus: string[];
  focusEdges: string[];
  speaksOf: string[];
  arcs: RingArc[];
  tint: Record<string, string>;
  walks: { item: string; target: string | null }[];
  change: { moved: string[]; arcs: { a0: number; a1: number }[] } | null;
};

export const worldMarksAt = (world: World, timeline: TimedStep[], nowMs: number): WorldMarks => {
  const resolved = resolveSteps(timeline, world);
  const cur = resolved[lastIndexAtOrBefore(resolved, nowMs)];
  const nodes = placeNodes(world);
  const own = ringGeometry(world) ? ownershipAt(world, nodes, timeline, nowMs) : null;
  const walkLive = !!cur && cur.walk.length > 0 && nowMs < cur.walkUntil;
  const walks = walkLive ? walkPlan(world, nodes, timeline, { t: cur!.walkAt, walk: cur!.walk }).map((p) => ({ item: p.item, target: p.target })) : [];
  const change = changeVisible(own, timeline, cur, nowMs) ? { moved: [...own!.moved].sort(), arcs: own!.changeArcs } : null;
  return {
    focus: [...(cur?.focus ?? [])],
    focusEdges: [...(cur?.focusEdges ?? [])],
    speaksOf: [...(cur?.speaksOf ?? [])],
    arcs: cur?.arcs ?? [],
    tint: Object.fromEntries(cur?.tint ?? []),
    walks,
    change,
  };
};

// ------------------------------------------------------------------------------------ focus check

// W13b (judge v6, seg03 t23): a spotlight must not dim the node the words are about. Warnings, not
// errors (build_manifest.py prints them; the render does not stop):
// 1. a walk whose item or target is dimmed by the focus current at the walk's step;
// 2. a step's speaksOf node that is hidden (the words name something not on screen);
// 3. a turn whose words name a visible node (by its label) while the focus current at that word,
//    inside a world scene, dims it and the step does not list it in speaksOf.
// Label matching: whole words, case-sensitive, only labels with a capital letter (names such as A,
// B, "Owner rule"; a common noun like "key" is too frequent to be a reliable signal, so name it in
// speaksOf). Numeric labels and ring items are skipped. "A" or "I" at a sentence start before a
// lowercase word is read as English ("A new server").
const tokenise = (s: string) => s.replace(/[^A-Za-z0-9'\-\s]/g, " ").split(/\s+/).filter(Boolean);
const STOP_AFTER_A = new Set(["and", "or"]);

export const namesInWords = (words: string[], label: string): number[] => {
  const want = tokenise(label);
  if (want.length === 0 || /^\d+$/.test(label.trim())) return [];
  const clean = words.map((w) => w.replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9']+$/g, "").replace(/'s$/, ""));
  const single = want.length === 1 && want[0].length === 1;
  const out: number[] = [];
  for (let i = 0; i + want.length <= clean.length; i++) {
    const ok = want.every((w, k) => clean[i + k] === w);
    if (!ok) continue;
    if (single && (want[0] === "A" || want[0] === "I")) {
      const start = i === 0 || /[.?!:]["')]*$/.test(words[i - 1]);
      const next = clean[i + 1];
      if (start && next && /^[a-z]/.test(next) && !STOP_AFTER_A.has(next)) continue;
    }
    out.push(i);
  }
  return out;
};

export const focusProblems = (manifest: Manifest): string[] => {
  const world = manifest.world;
  if (!world) return [];
  const timeline = buildTimeline(manifest);
  const resolved = resolveSteps(timeline, world);
  const nodes = placeNodes(world);
  const out: string[] = [];
  const where = (s: TimedStep) => `${Math.round(s.t)} ms (scene ${s.sceneId}${s.at ? `, ${s.at.turn}${s.at.word ? ` "${s.at.word}"` : ""}` : ""})`;
  resolved.forEach((r, i) => {
    const s = timeline[i];
    const vis = visibilityAt(world, timeline, s.t);
    for (const id of s.speaksOf ?? []) {
      if (!vis[id]?.on) out.push(`step at ${where(s)}: speaksOf names ${id}, which is not visible then; reveal it or drop it from speaksOf`);
    }
    if (!s.walk?.length || r.focus.size === 0) return;
    const dim = new Set<string>();
    for (const p of walkPlan(world, nodes, timeline, s)) {
      for (const id of [p.item, p.target]) if (id && !r.focus.has(id) && !r.speaksOf.has(id)) dim.add(id);
    }
    if (dim.size) {
      out.push(`step at ${where(s)}: the walk names ${[...dim].join(", ")} but focus [${[...r.focus].join(", ")}] dims ${dim.size > 1 ? "them" : "it"}; add ${dim.size > 1 ? "them" : "it"} to focus or speaksOf, or set "focus": []`);
    }
  });
  const worldScenes = manifest.scenes.filter((sc) => sc.type === "world");
  const named = world.nodes.filter((n) => n.role !== "item" && /[A-Z]/.test(n.label) && !/^\d+$/.test(n.label.trim()));
  const labels = [...new Set(named.map((n) => n.label))];
  const seen = new Set<string>();
  for (const turn of manifest.turns ?? []) {
    const words = turn.words?.length ? turn.words : null;
    const texts = words ? words.map((w) => w.text) : turn.text.split(/\s+/);
    for (const label of labels) {
      for (const i of namesInWords(texts, label)) {
        const at = words ? words[i].startMs : turn.startMs;
        if (!worldScenes.some((sc) => sc.startMs <= at && at < sc.endMs)) continue;
        const idx = lastIndexAtOrBefore(resolved, at + 100);
        const r = resolved[idx];
        if (!r || r.focus.size === 0) continue;
        const vis = visibilityAt(world, timeline, at);
        const ids = named.filter((n) => n.label === label && vis[n.id]?.on).map((n) => n.id);
        if (ids.length === 0 || ids.some((id) => r.focus.has(id) || r.speaksOf.has(id))) continue;
        const key = `${turn.id}:${label}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(
          `turn ${turn.id} names "${label}" at ${Math.round(at)} ms while the focus from the step at ${where(timeline[idx])} ` +
            `[${[...r.focus].join(", ")}] dims ${ids.join(", ")}; add a step on that word with focus including ${ids[0]} or "speaksOf": ["${ids[0]}"], or "focus": []`,
        );
      }
    }
  }
  return out;
};
