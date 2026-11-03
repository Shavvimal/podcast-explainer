// W11b, stale chips (judge v3 to v5): a keyword chip is a label for one state. It shows from its
// start until the next visual step after it, unless its props say persist: true. Pure (no React),
// so KeywordChips, visibleText.ts and qc.py (pe_common.chip_frames) share one rule.
import { msToFrame } from "./frames";
import { LEAD_FRAMES } from "./motionConstants";
import type { Manifest, Overlay } from "./types";

// A chip stays at least this long, so a step right after its word cannot flash it.
export const CHIP_MIN_MS = 700;

type StepLike = { atMs?: number };
type PanelLike = { steps?: StepLike[] };

// Every visual step time in the episode, sorted, unique: each scene start (a cut changes the
// picture), every step with a cue in any scene (world, diagram, code, compare panels, custom
// worldSteps). Steps without a cue (placeholder builds) do not count.
export const visualStepTimes = (manifest: Manifest): number[] => {
  const ts = new Set<number>();
  for (const sc of manifest.scenes) {
    ts.add(sc.startMs);
    const p = sc.props as { steps?: StepLike[]; worldSteps?: StepLike[]; left?: PanelLike; right?: PanelLike };
    for (const s of [...(p.steps ?? []), ...(p.worldSteps ?? []), ...(p.left?.steps ?? []), ...(p.right?.steps ?? [])]) {
      if (typeof s.atMs === "number") ts.add(s.atMs);
    }
  }
  return [...ts].sort((a, b) => a - b);
};

// The frames a chip is drawn on: [start, end). end is the overlay's own end, or the cue frame of the
// next visual step after its start (LEAD_FRAMES before the step's word, when the new state lands),
// whichever is earlier, but never under CHIP_MIN_MS; persist keeps the overlay's own end.
export const chipFrames = (o: Overlay, times: number[], fps: number): { start: number; end: number; expiredBy: number | null } => {
  const start = msToFrame(o.startMs, fps);
  const own = msToFrame(o.endMs, fps);
  if (o.props.persist) return { start, end: own, expiredBy: null };
  const next = times.find((t) => t > o.startMs);
  if (next === undefined) return { start, end: own, expiredBy: null };
  const cut = Math.max(msToFrame(next, fps) - LEAD_FRAMES, msToFrame(o.startMs + CHIP_MIN_MS, fps));
  return cut < own ? { start, end: cut, expiredBy: next } : { start, end: own, expiredBy: null };
};
