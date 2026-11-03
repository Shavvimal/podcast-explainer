// B06: the texts a scene draws at a time, from its props alone. Pure (no React, no theme), so QC
// can mirror it line for line (scripts/pe_common.py visible_text) and node tests can run it.
// It replays the renderer's own state: reveal and hide steps, set (label and value changes), table
// fill ("?" until filled), rows and lines on their cues, banners, panel title and tag changes,
// stat lines, check-card answers. Timing is the renderer's: a state change shows from its cue
// frame (LEAD_FRAMES early), a result (answer, verdict or banner, stat, row, fill, panel title)
// from its word with zero lead. Fades are ignored: a text counts from its cue frame until its hide
// cue frame. Steps without a cue use the renderer's fallback frames.
// W11b: labels expire like the renderer's: a node value (own or `set`) at the next step on its
// timeline, a panel stat at its panel's next step, a banner at either panel's next step, a chip at
// the next visual step (overlayState.ts), each unless persist. Table cells are the band indexes the
// renderer draws (tableLayout.ts). labelSourcesAt() returns the same labels with their source and
// any count claim, for qc.py labels.counts.
// W13b: node labels and sublabels never expire (structure, not state); labelSourcesAt() returns them
// too, with source "node-label" or "node-sublabel" and expires: false, so qc.py labels.stale can
// check a quantity in a permanent label. A virtual node's label reads with its point ("A1").
// marksAt() returns the marks a world draws (focus, arcs, tint, walks, change band) after expiry.
import { answerFrame, cueFrame, msToFrame, parseLines } from "./frames";
import { LEAD_FRAMES, STEP_FALLBACK_FRAMES, STEP_FALLBACK_START } from "./motionConstants";
import { chipFrames, visualStepTimes } from "./overlayState";
import { bannerAt, type CompareProps, panelStateAt } from "./scenes/compareState";
import { compareBodySize, panelTableLayout } from "./scenes/tableLayout";
import { type MatrixProps, matrixTextsAt } from "./scenes/matrixLayout";
import {
  buildTimeline,
  fitCamera,
  lastIndexAtOrBefore,
  labelWithPoint,
  localTimeline,
  nodeOverrides,
  nodeTextAt,
  placeNodes,
  turnEnds,
  type WorldMarks,
  worldMarksAt,
  ringInsetFilter,
  type TimedStep,
  viewScale,
  visibilityAt,
} from "./scenes/world/worldState";
import type { CountClaim, Manifest, Scene, World, WorldNode } from "./types";
import { claimText } from "./scenes/compareState";

type Opts = { only?: (n: WorldNode) => boolean; noteScene?: string };

// World texts at nowMs: visible node labels, sublabels and values (after `set`), visible edge
// labels, and the current step's note.
export const worldTextsAt = (world: World, timeline: TimedStep[], nowMs: number, fps: number, opts: Opts = {}): string[] => {
  const t = nowMs + (LEAD_FRAMES / fps) * 1000; // reveals, hides and sets land LEAD_FRAMES early
  const vis = visibilityAt(world, timeline, t);
  const over = nodeOverrides(timeline, t);
  const out: string[] = [];
  const placed = placeNodes(world);
  for (const n of world.nodes) {
    if (!vis[n.id]?.on) continue;
    if (opts.only && !opts.only(n)) continue;
    const txt = nodeTextAt(n, vis[n.id], over[n.id], timeline, t);
    out.push(labelWithPoint(txt.label, n, placed));
    if (n.sublabel) out.push(n.sublabel);
    if (txt.value !== undefined) out.push(txt.value);
  }
  for (const e of world.edges) if (vis[e.id]?.on && e.label) out.push(e.label);
  const idx = lastIndexAtOrBefore(timeline, nowMs);
  const cur = timeline[idx];
  if (cur?.note && (!opts.noteScene || cur.sceneId === opts.noteScene)) out.push(cur.note);
  return out;
};

// Generic props walk for custom scenes (mirrors pe_common._strings_at with numbers on): strings
// and numbers, an object with atMs later than now hidden, a key x hidden until its sibling xAtMs.
const SKIP = new Set(["component", "language", "svg", "viewBox", "worldSteps"]);
const propsTexts = (obj: unknown, nowMs: number, key = ""): string[] => {
  if (typeof obj === "string") return [obj];
  if (typeof obj === "number") return key.endsWith("Ms") ? [] : [String(obj)];
  if (Array.isArray(obj)) return obj.flatMap((v) => propsTexts(v, nowMs, key));
  if (obj && typeof obj === "object") {
    const o = obj as Record<string, unknown>;
    if (typeof o.atMs === "number" && o.atMs > nowMs) return [];
    return Object.entries(o).flatMap(([k, v]) => {
      if (SKIP.has(k)) return [];
      const gate = o[`${k}AtMs`];
      if (typeof gate === "number" && gate > nowMs) return [];
      return propsTexts(v, nowMs, k);
    });
  }
  return [];
};

const fallback = (i: number) => STEP_FALLBACK_START + i * STEP_FALLBACK_FRAMES;

// Texts drawn by one scene at nowMs (absolute episode time). `timeline` is the shared world
// timeline (buildTimeline(manifest)); pass it in when calling for many scenes or times.
export const sceneTextsAt = (manifest: Manifest, scene: Scene, nowMs: number, timeline: TimedStep[] = buildTimeline(manifest)): string[] => {
  const fps = manifest.video.fps;
  const fromFrame = msToFrame(scene.startMs, fps);
  const frame = msToFrame(nowMs, fps) - fromFrame;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p = scene.props as Record<string, any>;
  const out: string[] = [];
  const push = (...xs: (string | undefined | null)[]) => xs.forEach((x) => x && out.push(x));
  switch (scene.type) {
    case "title":
      push(p.kicker, p.title, p.subtitle);
      if (p.question && frame >= cueFrame(p.questionAtMs, 45, fromFrame, fps)) push(p.question);
      break;
    case "world":
      if (manifest.world) out.push(...worldTextsAt(manifest.world, timeline, nowMs, fps));
      break;
    case "recap":
      push(p.title ?? "Recap");
      (p.points ?? []).slice(0, 4).forEach((pt: { text: string; atMs?: number }, i: number) => {
        if (frame >= cueFrame(pt.atMs, 12 + i * 30, fromFrame, fps)) push(pt.text);
      });
      break;
    case "check": {
      const answered = p.answer !== undefined || p.correct !== undefined;
      push(answered ? "Check yourself" : "Your turn: answer aloud", p.question, ...(p.options ?? []));
      const a = answered ? answerFrame(p.answerAtMs, fromFrame, fps) : null;
      if (a !== null && frame >= a) push(p.answer);
      break;
    }
    case "equation":
      push(p.title);
      (p.lines ?? []).forEach((l: { tex?: string; text?: string; note?: string; atMs?: number }, i: number) => {
        if (frame >= cueFrame(l.atMs, fallback(i), fromFrame, fps)) push(l.tex ?? l.text, l.note);
      });
      break;
    case "code": {
      push(p.title, p.filename);
      const steps = (p.steps ?? []) as { atMs?: number; lines?: string | number[] }[];
      const revealAt: Record<number, number> = {};
      steps.forEach((s, i) => parseLines(s.lines).forEach((ln) => (revealAt[ln] ??= cueFrame(s.atMs, fallback(i), fromFrame, fps))));
      String(p.code ?? "")
        .replace(/\n+$/, "")
        .split("\n")
        .forEach((line, i) => {
          const at = revealAt[i + 1];
          if ((at === undefined || frame >= at) && line.trim()) push(line);
        });
      break;
    }
    case "diagram": {
      push(p.title);
      const steps = (p.steps ?? []) as { atMs?: number; reveal?: string[]; hide?: string[] }[];
      const revealAt: Record<string, number> = {};
      const hideAt: Record<string, number> = {};
      steps.forEach((s, i) => (s.reveal ?? []).forEach((id) => (revealAt[id] ??= cueFrame(s.atMs, fallback(i), fromFrame, fps))));
      steps.forEach((s, i) => (s.hide ?? []).forEach((id) => (hideAt[id] ??= cueFrame(s.atMs, fallback(i), fromFrame, fps))));
      for (const el of (p.elements ?? []) as { id: string; text?: string }[]) {
        const at = revealAt[el.id];
        const off = hideAt[el.id];
        if (el.text && (at === undefined || frame >= at) && (off === undefined || frame < off)) push(el.text);
      }
      break;
    }
    case "compare": {
      const c = p as unknown as CompareProps;
      push(c.title);
      const banner = bannerAt(c, fromFrame, fps, frame);
      const hasTitle = !!c.title;
      if (banner) push(banner.text);
      for (const side of ["left", "right"] as const) {
        const panel = c[side];
        if (!panel) continue;
        const st = panelStateAt(panel, fromFrame, fps, frame);
        push(st.title, st.tag);
        if (banner) push(banner.labels[side] ?? (banner.winner === "none" ? null : banner.winner === side ? "right" : "wrong"));
        if (st.stat) push(st.stat.text);
        if (panel.kind === "table") {
          const idx = panelTableLayout(panel, hasTitle).bands.flat(); // exactly the cells the renderer draws
          out.push(...idx.map((i) => panel.columns?.[i]).filter((x): x is string => x !== undefined));
          for (const r of st.rows) if (r.visible) push(r.label, ...idx.map((i) => r.cells[i]?.text));
        } else if (panel.kind === "text") {
          for (const l of st.lines) if (l.visible) push(l.text);
        } else if (panel.kind === "world") {
          const shared = panel.world === "shared";
          const world = shared ? manifest.world : (panel.world as World | undefined);
          if (!world) continue;
          const sceneId = `${scene.id}-${side}`;
          const tl = shared ? timeline : localTimeline(panel.steps ?? [], sceneId, scene.startMs, turnEnds(manifest));
          const body = compareBodySize(hasTitle);
          const cam = { ...fitCamera(world, body.w, body.h), ...(panel.camera ?? {}) };
          const only = ringInsetFilter(world, viewScale(world, body.w, body.h, cam));
          out.push(...worldTextsAt(world, tl, nowMs, fps, { only, noteScene: shared ? scene.id : sceneId }));
        }
      }
      break;
    }
    case "matrix":
      out.push(...matrixTextsAt(p as unknown as MatrixProps, fromFrame, fps, frame));
      break;
    case "custom":
      if (Array.isArray(p.worldSteps) && manifest.world) {
        out.push(...worldTextsAt(manifest.world, timeline, nowMs, fps, { only: ringInsetFilter(manifest.world) }));
      }
      out.push(...propsTexts(p, nowMs));
      break;
  }
  return out;
};

// Chips on screen at nowMs (renderer frame clock, chip expiry applied).
const chipsAt = (manifest: Manifest, nowMs: number) => {
  const fps = manifest.video.fps;
  const f = msToFrame(nowMs, fps);
  const times = visualStepTimes(manifest);
  return (manifest.overlays ?? []).filter((o) => {
    if (o.type !== "chip") return false;
    const w = chipFrames(o, times, fps);
    return w.start <= f && f < w.end;
  });
};

// Every text on screen at nowMs: the active scene(s) plus keyword chips.
export const visibleTextsAt = (manifest: Manifest, nowMs: number): string[] => {
  const timeline = buildTimeline(manifest);
  const out: string[] = [];
  for (const sc of manifest.scenes) if (sc.startMs <= nowMs && nowMs < sc.endMs) out.push(...sceneTextsAt(manifest, sc, nowMs, timeline));
  for (const o of chipsAt(manifest, nowMs)) out.push(claimText(o.props.text, o.props.claim));
  return out;
};

// W13b: marks of the episode world at nowMs, when a world scene is on screen (null otherwise).
export const marksAt = (manifest: Manifest, nowMs: number): WorldMarks | null => {
  if (!manifest.world) return null;
  if (!manifest.scenes.some((sc) => sc.type === "world" && sc.startMs <= nowMs && nowMs < sc.endMs)) return null;
  return worldMarksAt(manifest.world, buildTimeline(manifest), nowMs);
};

// One label on screen with where it comes from (R02): qc.py labels.counts checks a `claim` when
// present and the text otherwise. Sources: chip, banner, pill (banner label per side), stat, title,
// tag (panel header). sceneId and side say which compare scene and panel it belongs to.
export type LabelSource = {
  text: string;
  source: "chip" | "banner" | "pill" | "stat" | "title" | "tag" | "node-label" | "node-sublabel" | "node-value";
  sceneId?: string;
  side?: "left" | "right";
  claim?: CountClaim;
  nodeId?: string; // node sources
  expires?: boolean; // node sources: false for labels and sublabels (never expire), true for a value without persist
};

// Node labels, sublabels and values a world draws at nowMs, as label sources.
const worldLabelSources = (world: World, timeline: TimedStep[], nowMs: number, fps: number, sceneId: string, only?: (n: WorldNode) => boolean, side?: "left" | "right"): LabelSource[] => {
  const t = nowMs + (LEAD_FRAMES / fps) * 1000;
  const vis = visibilityAt(world, timeline, t);
  const over = nodeOverrides(timeline, t);
  const placed = placeNodes(world);
  const out: LabelSource[] = [];
  for (const n of world.nodes) {
    if (!vis[n.id]?.on || (only && !only(n))) continue;
    const txt = nodeTextAt(n, vis[n.id], over[n.id], timeline, t);
    const base = { sceneId, nodeId: n.id, ...(side ? { side } : {}) };
    const labelPersists = !over[n.id]?.labelSet || txt.label === n.label;
    out.push({ text: labelWithPoint(txt.label, n, placed), source: "node-label", expires: !labelPersists, ...base });
    if (n.sublabel) out.push({ text: n.sublabel, source: "node-sublabel", expires: false, ...base });
    if (txt.value !== undefined) {
      const fromSet = !!over[n.id]?.valueSet;
      const lasts = fromSet ? timeline.some((s) => s.t <= t && s.set?.[n.id]?.value === txt.value && !!s.set?.[n.id]?.persist) : !!n.persist;
      out.push({ text: txt.value, source: "node-value", expires: !lasts, ...base });
    }
  }
  return out;
};

export const labelSourcesAt = (manifest: Manifest, nowMs: number): LabelSource[] => {
  const fps = manifest.video.fps;
  const out: LabelSource[] = [];
  const timeline = buildTimeline(manifest);
  for (const sc of manifest.scenes) {
    if (!(sc.startMs <= nowMs && nowMs < sc.endMs)) continue;
    if (sc.type === "world" && manifest.world) out.push(...worldLabelSources(manifest.world, timeline, nowMs, fps, sc.id));
    if (sc.type !== "compare") continue;
    const c = sc.props as unknown as CompareProps;
    const fromFrame = msToFrame(sc.startMs, fps);
    const frame = msToFrame(nowMs, fps) - fromFrame;
    const banner = bannerAt(c, fromFrame, fps, frame);
    if (banner?.text) out.push({ text: banner.text, source: "banner", sceneId: sc.id, ...(banner.claim ? { claim: banner.claim } : {}) });
    for (const side of ["left", "right"] as const) {
      const panel = c[side];
      if (!panel) continue;
      const st = panelStateAt(panel, fromFrame, fps, frame);
      if (st.title) out.push({ text: st.title, source: "title", sceneId: sc.id, side });
      if (st.tag) out.push({ text: st.tag, source: "tag", sceneId: sc.id, side });
      const pill = banner ? (banner.labels[side] ?? (banner.winner === "none" ? null : banner.winner === side ? "right" : "wrong")) : null;
      if (pill) out.push({ text: pill, source: "pill", sceneId: sc.id, side });
      if (st.stat) out.push({ text: st.stat.text, source: "stat", sceneId: sc.id, side, ...(st.stat.claim ? { claim: st.stat.claim } : {}) });
      if (panel.kind === "world") {
        const shared = panel.world === "shared";
        const world = shared ? manifest.world : (panel.world as World | undefined);
        if (!world) continue;
        const tl = shared ? timeline : localTimeline(panel.steps ?? [], `${sc.id}-${side}`, sc.startMs, turnEnds(manifest));
        const body = compareBodySize(!!c.title);
        const cam = { ...fitCamera(world, body.w, body.h), ...(panel.camera ?? {}) };
        out.push(...worldLabelSources(world, tl, nowMs, fps, sc.id, ringInsetFilter(world, viewScale(world, body.w, body.h, cam)), side));
      }
    }
  }
  for (const o of chipsAt(manifest, nowMs)) out.push({ text: claimText(o.props.text, o.props.claim), source: "chip", ...(o.props.claim ? { claim: o.props.claim } : {}) });
  return out;
};
