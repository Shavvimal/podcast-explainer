import { evolvePath, getLength, getPointAtLength } from "@remotion/paths";
import { useMemo } from "react";
import { AbsoluteFill, Img, interpolate, interpolateColors, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { episodeFile, useEnterFrames, useEpisode } from "../../context";
import { colors, fonts, layout, motion, radius, type } from "../../theme";
import { clamp, easeOut } from "../../time";
import type { Camera, SceneProps, World, WorldEdge, WorldNode, WorldStep } from "../../types";
import {
  buildTimeline,
  changeVisible,
  CHAR_W,
  pointOf,
  nodeSize,
  RING_DEFAULTS,
  ringFaceRadius,
  initialCamera,
  lastIndexAtOrBefore,
  nodeOverrides,
  nodeTextAt,
  type OwnershipState,
  ownershipAt,
  placeNodes,
  posToAngle,
  type Resolved,
  type RingGeometry,
  resolveSteps,
  ringArcPath,
  ringGeometry,
  ringProblems,
  ringTracks,
  type TimedStep,
  type Vis,
  visibilityAt,
  WALK_MS,
  walkPlan,
  walkPoints,
  walkProblems,
  worldSize,
} from "./worldState";

export type WorldProps = { steps?: WorldStep[] };

export { nodeSize, ringFaceRadius } from "./worldState";

// The main scene type: ONE persistent concept diagram for the whole episode (manifest.world).
// Each step (anchored to a word or turn) sets focus nodes/edges, a camera, value changes,
// flows along edges and pulses. Nodes and edges appear at their resolved revealAtMs.
export const WorldScene: React.FC<SceneProps<WorldProps>> = ({ fromFrame, enter }) => {
  const frame = useCurrentFrame();
  const shared = useSharedWorld(fromFrame);
  if (!shared) {
    throw new Error("Scene type 'world' needs a top-level 'world' in scenes.json (nodes and edges).");
  }
  const enterFrames = useEnterFrames();
  const enterP = enter ? interpolate(frame, [0, enterFrames], [0, 1], { ...clamp, easing: easeOut }) : 1;
  const { w: SW, h: SH } = layout.stage;
  return (
    <AbsoluteFill style={{ opacity: enterP }}>
      <div
        style={{
          position: "absolute",
          left: layout.stage.x,
          top: layout.stage.y,
          width: SW,
          height: SH,
          overflow: "hidden",
          borderRadius: radius.card,
        }}
      >
        <WorldCanvas world={shared.world} timeline={shared.timeline} nowMs={shared.nowMs} width={SW} height={SH} />
      </div>
    </AbsoluteFill>
  );
};

// The persistent world and its global timeline, for any scene that wants to continue it
// (WorldScene, a compare panel with world "shared", or a custom scene that draws the world inset).
// Returns null when the episode has no world.
export const useSharedWorld = (fromFrame: number) => {
  const { manifest } = useEpisode();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeline = useMemo(() => buildTimeline(manifest), [manifest]);
  if (!manifest.world) return null;
  const nowMs = ((fromFrame + frame) / fps) * 1000;
  return { world: manifest.world, timeline, nowMs };
};

// Draws a world (the episode world or a compare panel's local world) at nowMs inside a box of
// width x height pixels. `camera` fixes the view (compare panels); without it the camera follows
// the steps' camera moves. Pure function of its props and the frame clock.
export const WorldCanvas: React.FC<{
  world: World;
  timeline: TimedStep[];
  nowMs: number;
  width: number;
  height: number;
  camera?: Camera;
  idPrefix?: string;
  only?: (n: WorldNode) => boolean; // draw only these nodes (a compare panel hides off-ring nodes)
  noteScene?: string; // show notes only from steps of this scene (a panel never shows another scene's note)
  ringTextPx?: number; // smallest rendered size of ring numerals and owner letters (compare panels: 32)
}> = ({ world, timeline, nowMs, width: SW, height: SH, camera: fixedCamera, idPrefix = "w", only, noteScene, ringTextPx = type.min }) => {
  const { fps } = useVideoConfig();
  // W11b: a ring whose roles do not sit on one circle, or a walk that ends anywhere but its
  // successor (without overshoot), stops the render with the reason (build_manifest.py checks it first).
  useMemo(() => {
    const bad = [...ringProblems(world), ...walkProblems(world, timeline)];
    if (bad.length) throw new Error(`World ${idPrefix}: ${bad.join("; ")}`);
  }, [world, timeline, idPrefix]);
  const resolved = useMemo(() => resolveSteps(timeline, world), [timeline, world]);
  const idx = lastIndexAtOrBefore(resolved, nowMs);
  const cur = resolved[idx];
  const prev = resolved[idx - 1];
  const leadMs = (motion.leadFrames / fps) * 1000;

  // Focus blends from the previous step's focus over motion.focusMs.
  const fp = cur ? interpolate(nowMs - cur.t, [0, motion.focusMs], [0, 1], { ...clamp, easing: easeOut }) : 1;
  const focusOf = (id: string, edge = false) => {
    // W13b: a node the current step speaks of is never dimmed (it counts as focused).
    const has = (r: typeof cur | undefined) => !!r && (edge ? r.focusEdges.has(id) : r.focus.has(id) || r.speaksOf.has(id));
    const a = has(prev) ? 1 : 0;
    const b = has(cur) ? 1 : 0;
    return a + (b - a) * fp;
  };
  const anyFocus = (r: typeof cur | undefined) => (r && (r.focus.size > 0 || r.focusEdges.size > 0) ? 1 : 0);
  const dim = anyFocus(prev) + (anyFocus(cur) - anyFocus(prev)) * fp;

  const camera = fixedCamera ?? cameraAt(resolved, world, nowMs);
  // Values and labels land LEAD_FRAMES early, like every state change, and expire on the same clock.
  const overrides = nodeOverrides(timeline, nowMs + leadMs);
  const nodes = useMemo(() => placeNodes(world), [world]);
  const nodesById = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);
  const vis = visibilityAt(world, timeline, nowMs);
  const ring = ringGeometry(world);
  const own = ring ? ownershipAt(world, nodes, timeline, nowMs) : null;

  const { W, H } = worldSize(world);
  const fit = Math.min(SW / W, SH / H);
  const s = fit * camera.zoom;
  // Judge rule: no text under type.min (28 px) at 1080p. World text is drawn in world units and
  // scaled by s, so a small panel or a low zoom would shrink it; raise every font to 28 / s units.
  const minFont = type.min / s;
  const ringFont = Math.max(type.min, ringTextPx) / s;
  // Ring discs grow to hold their label at ringFont, capped below the slot spacing on their track.
  const tracks = ring ? ringTracks(world) : null;
  const ringDisc = (n: WorldNode, label: string) => {
    const base = nodeSize(n).w;
    if (!ring || !n.role) return base;
    const track = (n.role === "owner" ? tracks?.owner : tracks?.item) ?? ring.r;
    const slot = (2 * Math.PI * track) / ring.positions - 6;
    const need = Math.max(type.label + 12, ringFont) * CHAR_W * Math.max(1, label.length) + 14;
    return Math.max(base, Math.min(need, Math.max(base, slot)));
  };

  // Fade in from the reveal (3 frames early, like every cue), fade out from a hide.
  const appear = (id: string, frames = 14) => {
    const v = vis[id];
    if (!v) return 0;
    if (v.since === -Infinity) return v.on ? 1 : 0;
    const p = interpolate(nowMs - (v.since - leadMs), [0, (frames / fps) * 1000], [0, 1], { ...clamp, easing: easeOut });
    return v.on ? p : 1 - p;
  };

  // Ring ownership colour: blends from the owner before the last change to the owner now.
  const changeP = own && own.changedAt > -Infinity
    ? interpolate(nowMs - (own.changedAt - leadMs), [0, 400], [0, 1], { ...clamp, easing: easeOut })
    : 1;
  const ownerColor = (id: string | null | undefined) => (id ? (overrides[id]?.color ?? nodesById[id]?.color ?? colors.accent) : null);
  const itemFill = (id: string) => {
    if (!own) return null;
    const from = own.colouredFrom[id] ?? -Infinity;
    if (from > nowMs) return colors.surfaceRaised;
    const b = ownerColor(own.owners[id]) ?? colors.surfaceRaised;
    if (from > own.changedAt) {
      // first colouring (ownershipAt or the end of a walk): grey -> owner colour
      const p = interpolate(nowMs - from, [0, 400], [0, 1], { ...clamp, easing: easeOut });
      return interpolateColors(p, [0, 1], [colors.surfaceRaised, b]);
    }
    const a = ownerColor(own.before[id]) ?? colors.surfaceRaised;
    return a === b ? b : interpolateColors(changeP, [0, 1], [a, b]);
  };
  // W13b: the automatic change arc and moved outlines show until the next step after the change,
  // unless the step that caused it persists "change"; a step that sets `arcs` clears them.
  // A first reveal of owners (nothing had an owner before) moves nothing, so it shows no change arc.
  const showChange = changeVisible(own, timeline, cur, nowMs);

  return (
    <>
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: W,
        height: H,
        transformOrigin: "0 0",
        transform: `translate(${SW / 2}px, ${SH / 2}px) scale(${s}) translate(${-camera.x}px, ${-camera.y}px)`,
      }}
    >
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <defs>
          <marker id={`${idPrefix}-arrow-idle`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill={colors.line} />
          </marker>
          <marker id={`${idPrefix}-arrow-focus`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill={colors.accent} />
          </marker>
        </defs>
        {ring ? (
          <RingLayer
            world={world}
            timeline={timeline}
            ring={ring}
            cur={cur}
            nowMs={nowMs}
            fps={fps}
            nodes={nodes}
            vis={vis}
            own={own}
            showChange={showChange}
            changeP={changeP}
            idPrefix={idPrefix}
          />
        ) : null}
        {world.edges.map((e) => {
          const a = nodesById[e.from];
          const b = nodesById[e.to];
          if (!a || !b) return null;
          const reveal = appear(e.id, 18);
          if (reveal <= 0) return null;
          const f = focusOf(e.id, true);
          const op = 1 - 0.6 * dim * (1 - f);
          return (
            <EdgeView
              key={e.id}
              edge={e}
              a={a}
              b={b}
              reveal={reveal}
              focus={f}
              opacity={op}
              flowing={cur?.flow.has(e.id) ? nowMs - cur.t : null}
              idPrefix={idPrefix}
              minFont={minFont}
            />
          );
        })}
      </svg>
      {nodes.map((n) => {
        if (only && !only(n)) return null;
        const reveal = appear(n.id);
        if (reveal <= 0) return null;
        const f = focusOf(n.id);
        const o = overrides[n.id];
        const txt = nodeTextAt(n, vis[n.id], o, timeline, nowMs + leadMs);
        const pulseT = cur?.pulse.has(n.id) ? nowMs - cur.t : null;
        const changePop =
          o && Number.isFinite(o.changedAt) && o.changedAt <= nowMs + leadMs
            ? spring({ frame: Math.round(((nowMs - o.changedAt) / 1000) * fps) + motion.leadFrames, fps, config: { damping: 12 }, durationInFrames: 18 })
            : 1;
        const isRing = ring && (n.role === "owner" || n.role === "item");
        const point = pointOf(n, nodes);
        const fill = n.role === "item" ? itemFill(n.id) : n.role === "owner" && ring ? (o?.color ?? n.color ?? colors.accent) : null;
        return (
          <NodeView
            key={n.id}
            node={{ ...n, color: o?.color ?? n.color, label: txt.label, value: txt.value }}
            hasValue={n.value !== undefined || timeline.some((s) => s.set?.[n.id]?.value !== undefined)}
            disc={isRing ? ringDisc(n, point === undefined ? txt.label : `${txt.label}${point}`) : undefined}
            point={point}
            labelFont={isRing ? ringFont : undefined}
            reveal={reveal}
            focus={f}
            dim={dim}
            pulseMs={pulseT}
            changePop={o && Number.isFinite(o.changedAt) ? changePop : 1}
            fill={isRing ? fill : null}
            moved={showChange && own!.moved.has(n.id) && !cur?.tint.has(n.id)}
            tint={cur?.tint.has(n.id) ? tintColor(cur.tint.get(n.id)!) : null}
            minFont={minFont}
          />
        );
      })}
    </div>
    {cur?.note && (!noteScene || cur.sceneId === noteScene) ? <Note text={cur.note} t={nowMs - cur.t} maxWidth={Math.min(900, SW - 48)} /> : null}
    </>
  );
};

// Clock face, ring line, highlighted arcs (explicit `arcs` and the automatic change arc), and walk
// arrows. Every ring node sits at pos x 360 / positions degrees (or its angle) on its role's track.
const RingLayer: React.FC<{
  world: World;
  timeline: TimedStep[];
  ring: RingGeometry;
  cur: Resolved | undefined;
  nowMs: number;
  fps: number;
  nodes: WorldNode[];
  vis: Record<string, Vis>;
  own: OwnershipState | null;
  showChange: boolean;
  changeP: number;
  idPrefix: string;
}> = ({ world, timeline, ring, cur, nowMs, nodes, vis, own, showChange, changeP, idPrefix }) => {
  const step = 360 / ring.positions;
  const half = step / 2;
  const arcs = cur?.arcs ?? [];
  // Highlighted ranges are a band behind the item discs, as wide as a disc plus a margin.
  const bandW = RING_DEFAULTS.item + 28;
  const tracks = ringTracks(world);
  const faceR = ringFaceRadius(world) ?? ring.r + 60;
  const ownerOn = nodes.some((n) => n.role === "owner" && vis[n.id]?.on);
  // W13b: the walk of the current step, or a persisted earlier walk (planned at its own step), until
  // its end (next step, or the end of its anchor turn).
  const plans = useMemo(() => (cur && cur.walk.length ? walkPlan(world, nodes, timeline, { t: cur.walkAt, walk: cur.walk }) : []), [world, nodes, timeline, cur]);
  const walkOn = !!cur && nowMs < cur.walkUntil;
  return (
    <g>
      <defs>
        <marker id={`${idPrefix}-walk-head`} viewBox="0 0 10 10" refX="6" refY="5" markerWidth="4" markerHeight="4" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill={colors.accent} />
        </marker>
        <marker id={`${idPrefix}-walk-over`} viewBox="0 0 10 10" refX="6" refY="5" markerWidth="4" markerHeight="4" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill={colors.bad} />
        </marker>
      </defs>
      {/* clock face: owners sit on its rim like hour marks, items on the ring line inside */}
      <circle cx={ring.cx} cy={ring.cy} r={faceR} fill={colors.surface} fillOpacity={0.7} stroke={colors.line} strokeWidth={ownerOn ? 4 : 2} />
      <circle cx={ring.cx} cy={ring.cy} r={ring.r} fill="none" stroke={colors.line} strokeWidth={6} />
      {arcs.map((a, i) => (
        <path
          key={`arc${i}`}
          d={ringArcPath(posToAngle(a.from, ring) - half, posToAngle(a.to, ring) + half, ring.r, ring)}
          fill="none"
          stroke={a.color ?? colors.accent}
          strokeWidth={bandW}
          opacity={0.35 * interpolate(nowMs - (cur?.arcsSetAt ?? 0), [0, 300], [0, 1], clamp)}
        />
      ))}
      {showChange && own
        ? own.changeArcs.map((a, i) => (
            <path
              key={`chg${i}`}
              d={ringArcPath(a.a0 + half, a.a1 + half, ring.r, ring)}
              fill="none"
              stroke={colors.warn}
              strokeWidth={bandW}
              opacity={0.35 * changeP}
            />
          ))
        : null}
      {cur && walkOn
        ? plans.map((plan, wi) => {
            if (!vis[plan.item]?.on || !plan.target) return null;
            const pts = walkPoints(plan, nodes, ring, tracks);
            if (!pts) return null;
            const p = interpolate(nowMs - cur.walkAt, [0, WALK_MS], [0, 1], { ...clamp, easing: easeOut });
            const d = partialPolyline(pts, p);
            if (!d) return null;
            const over = plan.overshoot && plan.target !== plan.successor;
            return (
              <path
                key={`walk-${wi}-${plan.item}`}
                d={d}
                fill="none"
                stroke={over ? colors.bad : colors.accent}
                strokeWidth={10}
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray={over ? "22 16" : undefined}
                markerEnd={p > 0.98 ? `url(#${idPrefix}-${over ? "walk-over" : "walk-head"})` : undefined}
              />
            );
          })
        : null}
    </g>
  );
};

// SVG path of the first fraction p (0..1) of a polyline, by length.
const partialPolyline = (pts: { x: number; y: number }[], p: number): string | null => {
  if (pts.length < 2 || p <= 0) return null;
  const seg = pts.slice(1).map((q, i) => Math.hypot(q.x - pts[i].x, q.y - pts[i].y));
  const total = seg.reduce((a, b) => a + b, 0);
  let left = total * p;
  const out = [`M ${pts[0].x} ${pts[0].y}`];
  for (let i = 0; i < seg.length; i++) {
    if (left >= seg[i]) {
      out.push(`L ${pts[i + 1].x} ${pts[i + 1].y}`);
      left -= seg[i];
      continue;
    }
    const f = seg[i] > 0 ? left / seg[i] : 0;
    out.push(`L ${pts[i].x + (pts[i + 1].x - pts[i].x) * f} ${pts[i].y + (pts[i + 1].y - pts[i].y) * f}`);
    break;
  }
  return out.length > 1 ? out.join(" ") : null;
};

// Camera transitions chain: each new camera starts from wherever the previous move had got to.
const cameraAt = (resolved: ReturnType<typeof resolveSteps>, world: World, nowMs: number): Camera => {
  const lerp = (a: Camera, b: Camera, p: number): Camera => ({
    x: a.x + (b.x - a.x) * p,
    y: a.y + (b.y - a.y) * p,
    zoom: a.zoom + (b.zoom - a.zoom) * p,
  });
  const prog = (t0: number, t: number) =>
    interpolate(t - t0, [0, motion.cameraMs], [0, 1], { ...clamp, easing: easeOut });
  let from = initialCamera(world);
  let to = from;
  let t0 = 0;
  for (const r of resolved) {
    if (r.t > nowMs) break;
    const here = lerp(from, to, prog(t0, r.t));
    from = here;
    to = r.camera;
    t0 = r.t;
  }
  return lerp(from, to, prog(t0, nowMs));
};

// A tint class is a theme colour name or a #hex value.
const TINTS: Record<string, string> = {
  accent: colors.accent,
  good: colors.good,
  warn: colors.warn,
  bad: colors.bad,
  muted: colors.muted,
  text: colors.text,
};
export const tintColor = (cls: string) => TINTS[cls] ?? (/^#[0-9a-fA-F]{3,8}$/.test(cls) ? cls : colors.warn);

const NodeView: React.FC<{
  node: WorldNode;
  reveal: number;
  focus: number;
  dim: number;
  pulseMs: number | null;
  changePop: number;
  fill?: string | null; // ring roles: the disc colour (owner colour); null keeps the surface
  moved?: boolean; // ring items whose owner just changed: dashed outline
  tint?: string | null; // step `tint`: solid outline in this colour (replaces the moved outline)
  minFont?: number; // smallest font in world units that still renders at type.min px
  hasValue?: boolean; // keep the value line's height when the value has expired (no layout jump)
  disc?: number; // ring roles: disc diameter, grown to hold the label (compare panels)
  labelFont?: number; // ring roles: label size in world units
  point?: number; // W13b virtual node: subscript after the label (A1, A2), at least type.min px
}> = ({ node, reveal, focus, dim, pulseMs, changePop, fill = null, moved = false, tint = null, minFont = type.min, hasValue = false, disc, labelFont, point }) => {
  const { slug } = useEpisode();
  const base = nodeSize({ ...node, value: hasValue ? (node.value ?? "") : node.value });
  const shape = base.shape;
  const ringRoleSized = node.role !== undefined && disc !== undefined;
  const titleFont = ringRoleSized ? Math.max(type.label + 12, labelFont ?? minFont) : Math.max(node.role !== undefined ? type.label + 12 : type.label + 4, minFont);
  // A raised font widens a box or pill to fit its text (a panel scales the world down), never narrows it.
  const textW = Math.max(node.label.length * titleFont, (node.sublabel?.length ?? 0) * Math.max(type.min, minFont), (node.value?.length ?? 0) * Math.max(type.body + 2, minFont)) * CHAR_W + 32;
  const h = ringRoleSized ? disc! : base.h;
  // W16: a pill's rounded ends take h / 2 of width at the top and bottom lines, so a pill widens by
  // that much more than a box for the same text (a 160-tall pill with a value no longer clips it).
  const w = ringRoleSized ? disc! : node.role !== undefined ? base.w : Math.max(base.w, textW + (shape === "pill" ? h / 2 : 0));
  const accent = node.color ?? colors.accent;
  const opacity = reveal * (1 - 0.55 * dim * (1 - focus));
  const ringRole = node.role !== undefined;
  const filled = ringRole && fill !== null && fill !== colors.surfaceRaised;
  const borderColor = focus > 0.01 ? (ringRole ? colors.text : accent) : ringRole ? (filled ? colors.bg : colors.line) : colors.line;
  const pulse = pulseMs === null ? 0 : interpolate(pulseMs, [0, 700], [0, 1], clamp);
  return (
    <div
      style={{
        position: "absolute",
        left: node.x - w / 2,
        top: node.y - h / 2,
        width: w,
        height: h,
        opacity,
        scale: String((0.85 + 0.15 * reveal) * (1 + 0.06 * focus)),
      }}
    >
      {moved ? (
        <div style={{ position: "absolute", inset: -12, borderRadius: 999, border: `5px dashed ${colors.text}` }} />
      ) : null}
      {tint ? (
        <div style={{ position: "absolute", inset: -14, borderRadius: shape === "box" ? radius.node + 12 : 999, border: `8px solid ${tint}` }} />
      ) : null}
      {pulseMs !== null && pulse < 1 ? (
        <div
          style={{
            position: "absolute",
            inset: -10 - 40 * pulse,
            borderRadius: shape === "box" ? radius.node + 20 : 999,
            border: `4px solid ${accent}`,
            opacity: 1 - pulse,
          }}
        />
      ) : null}
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: shape === "box" ? radius.node : 999,
          background: ringRole ? (fill ?? colors.surfaceRaised) : colors.surface,
          border: `${3 + 3 * focus}px solid ${borderColor}`,
          boxShadow: focus > 0.01 ? `0 0 ${36 * focus}px ${accent}55` : "none",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          padding: ringRole ? 0 : "6px 14px",
          fontFamily: fonts.sans,
          overflow: "hidden",
        }}
      >
        <div style={{ fontSize: titleFont, fontWeight: 800, color: filled ? colors.bg : colors.text, lineHeight: 1.1, whiteSpace: "nowrap" }}>
          {node.label}
          {point !== undefined ? <span style={{ fontSize: Math.max(minFont, titleFont * 0.7), fontWeight: 800, marginLeft: 1 }}>{point}</span> : null}
        </div>
        {node.sublabel ? (
          <div style={{ fontSize: Math.max(type.min, minFont), fontWeight: 600, color: colors.muted, marginTop: 4, lineHeight: 1.1 }}>
            {node.sublabel}
          </div>
        ) : null}
        {node.anchorImage ? (
          <Img
            src={episodeFile(slug, node.anchorImage)}
            style={{ position: "absolute", top: 8, right: 10, width: 44, height: 44, objectFit: "contain" }}
          />
        ) : null}
        {node.value !== undefined ? (
          <div
            style={{
              fontFamily: fonts.mono,
              fontSize: Math.max(type.body + 2, minFont),
              fontWeight: 700,
              color: accent,
              marginTop: 6,
              scale: String(changePop),
            }}
          >
            {node.value}
          </div>
        ) : null}
      </div>
    </div>
  );
};

// Point where the segment from the node centre towards (tx, ty) leaves the node outline.
const exitPoint = (n: WorldNode, tx: number, ty: number) => {
  const { w, h, shape } = nodeSize(n);
  const dx = tx - n.x;
  const dy = ty - n.y;
  const len = Math.hypot(dx, dy) || 1;
  const pad = 10;
  if (shape === "circle") {
    const r = w / 2 + pad;
    return { x: n.x + (dx / len) * r, y: n.y + (dy / len) * r };
  }
  const hw = w / 2 + pad;
  const hh = h / 2 + pad;
  const k = Math.min(hw / Math.abs(dx || 1e-6), hh / Math.abs(dy || 1e-6));
  return { x: n.x + dx * k, y: n.y + dy * k };
};

const EdgeView: React.FC<{
  edge: WorldEdge;
  a: WorldNode;
  b: WorldNode;
  reveal: number;
  focus: number;
  opacity: number;
  flowing: number | null;
  idPrefix: string;
  minFont?: number;
}> = ({ edge, a, b, reveal, focus, opacity, flowing, idPrefix, minFont = type.min }) => {
  const labelFont = Math.max(type.min, minFont);
  const bend = edge.bend ?? 0;
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
  const cx = mx + (-(b.y - a.y) / len) * bend;
  const cy = my + ((b.x - a.x) / len) * bend;
  const p0 = exitPoint(a, cx, cy);
  const p1 = exitPoint(b, cx, cy);
  const d = `M ${p0.x} ${p0.y} Q ${cx} ${cy} ${p1.x} ${p1.y}`;
  const evolved = evolvePath(reveal, d);
  const color = focus > 0.5 ? colors.accent : colors.line;
  const directed = edge.directed ?? true;
  const total = getLength(d);
  const mid = getPointAtLength(d, total / 2) ?? { x: cx, y: cy };
  // The label sits beside the edge (above a horizontal edge, right of a vertical one), never on it,
  // so short edges keep their line and arrowhead visible.
  let nx = -(p1.y - p0.y);
  let ny = p1.x - p0.x;
  const nl = Math.hypot(nx, ny) || 1;
  nx /= nl;
  ny /= nl;
  if (ny > 0 || (Math.abs(ny) < 1e-6 && nx < 0)) {
    nx = -nx;
    ny = -ny;
  }
  if (Math.abs(ny) < 0.3) {
    // near-vertical edge: put the label to the right
    nx = Math.abs(nx);
    ny = 0;
  }
  const labelW = (edge.label?.length ?? 0) * labelFont * 0.57 + 28;
  const off = Math.abs(ny) >= 0.3 ? 36 : labelW / 2 + 16;
  const labelPt = { x: mid.x + nx * off, y: mid.y + ny * off };

  return (
    <g opacity={opacity}>
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={4 + 3 * focus}
        strokeLinecap="round"
        strokeDasharray={edge.dashed && reveal >= 1 ? "14 12" : evolved.strokeDasharray}
        strokeDashoffset={edge.dashed && reveal >= 1 ? 0 : evolved.strokeDashoffset}
        markerEnd={directed && reveal > 0.95 ? `url(#${idPrefix}-${focus > 0.5 ? "arrow-focus" : "arrow-idle"})` : undefined}
      />
      {flowing !== null
        ? [0, 1, 2].map((k) => {
            const phase = ((flowing / 1400 + k / 3) % 1 + 1) % 1;
            const pt = getPointAtLength(d, total * phase);
            if (!pt) return null;
            return <circle key={k} cx={pt.x} cy={pt.y} r={9} fill={colors.accent} />;
          })
        : null}
      {edge.label && reveal > 0.6 ? (
        <g opacity={interpolate(reveal, [0.6, 1], [0, 1], clamp)}>
          <rect
            x={labelPt.x - labelW / 2}
            y={labelPt.y - labelFont * 0.86}
            width={labelW}
            height={labelFont * 1.72}
            rx={12}
            fill={colors.bg}
            stroke={color}
            strokeWidth={2}
          />
          <text
            x={labelPt.x}
            y={labelPt.y + labelFont * 0.36}
            textAnchor="middle"
            fontFamily={fonts.sans}
            fontWeight={700}
            fontSize={labelFont}
            fill={colors.text}
          >
            {edge.label}
          </text>
        </g>
      ) : null}
    </g>
  );
};

const Note: React.FC<{ text: string; t: number; maxWidth: number }> = ({ text, t, maxWidth }) => {
  const p = interpolate(t, [0, 300], [0, 1], { ...clamp, easing: easeOut });
  return (
    <div
      style={{
        position: "absolute",
        left: 24,
        top: 24,
        maxWidth,
        padding: "14px 24px",
        borderRadius: 16,
        background: colors.surfaceRaised,
        borderLeft: `6px solid ${colors.warn}`,
        fontFamily: fonts.sans,
        fontSize: type.body - 4,
        fontWeight: 700,
        color: colors.text,
        opacity: p,
        translate: `0px ${(1 - p) * -12}px`,
      }}
    >
      {text}
    </div>
  );
};
