// The only place milliseconds become frames. No imports beyond constants, so the pure state
// modules (compareState, visibleText) and node-run tests share the exact renderer arithmetic.
// time.ts re-exports everything here.
import { ENTRANCE_FRAMES, LEAD_FRAMES } from "./motionConstants";

export const msToFrame = (ms: number, fps: number) => Math.round((ms / 1000) * fps);
export const frameToMs = (frame: number, fps: number) => (frame / fps) * 1000;

// Local frame (inside a scene's <Sequence>) at which a cue fires, `leadFrames` before the word.
// The lead is for state changes that should land with the word (a node lights as it is named).
// Pass lead 0 for anything that gives away an answer or a result: use answerFrame().
export const cueFrame = (
  atMs: number | undefined,
  fallbackLocalFrame: number,
  fromFrame: number,
  fps: number,
  lead: number = LEAD_FRAMES,
) => (atMs === undefined ? fallbackLocalFrame : msToFrame(atMs, fps) - fromFrame - lead);

// Local frame of an answer, verdict or result cue: zero lead, so it never shows before its word.
// Returns null without a cue: an answer with no cue is never shown (no time-based default).
export const answerFrame = (atMs: number | undefined, fromFrame: number, fps: number): number | null =>
  atMs === undefined ? null : msToFrame(atMs, fps) - fromFrame;

// A09 (W11b): the entrance length of a scene in frames, computed on the frame clock so rounding
// can never push the fade into speech. The fade runs over local frames [0, n] and is complete on
// absolute frame from + n, which shows time (from + n) / fps; that must be at or before the next
// speech start S, so from + n <= floor(S * fps / 1000). A scene that starts inside a turn's speech
// cuts (0). Fewer than 2 frames of room also cuts. `enterMs` (build_manifest.py) caps the length,
// never above ENTRANCE_FRAMES;
// absent means ENTRANCE_FRAMES. build_manifest.py and qc.py mirror this function.
export type SpeechSpan = { startMs: number; endMs: number; words?: { startMs: number }[] };
export const entranceFrames = (startMs: number, enterMs: number | undefined, turns: SpeechSpan[], fps: number): number => {
  const from = msToFrame(startMs, fps);
  const want = enterMs === undefined ? ENTRANCE_FRAMES : Math.min(ENTRANCE_FRAMES, Math.max(0, Math.round((enterMs * fps) / 1000)));
  if (want === 0) return 0;
  let next = Infinity;
  for (const t of turns) {
    const s = Math.min(t.startMs, t.words?.[0]?.startMs ?? t.startMs);
    if (s <= startMs && startMs < t.endMs) return 0; // inside speech: cut
    if (s >= startMs) next = Math.min(next, s);
  }
  const room = next === Infinity ? want : Math.floor((next * fps) / 1000) - from;
  const n = Math.min(want, room);
  return n < 2 ? 0 : n;
};

// Parse "1-3,5" or [1,2,3] into a set of 1-based line numbers.
export const parseLines = (spec: string | number[] | undefined): Set<number> => {
  const out = new Set<number>();
  if (spec === undefined) return out;
  if (Array.isArray(spec)) {
    spec.forEach((n) => out.add(n));
    return out;
  }
  for (const part of String(spec).split(",")) {
    const [a, b] = part.split("-").map((s) => parseInt(s.trim(), 10));
    if (Number.isNaN(a)) continue;
    const end = Number.isNaN(b) || b === undefined ? a : b;
    for (let i = a; i <= end; i++) out.add(i);
  }
  return out;
};
