// Animation helpers. Milliseconds become frames only in frames.ts (re-exported here).
import { Easing, interpolate } from "remotion";
import { motion } from "./theme";

export { answerFrame, cueFrame, frameToMs, msToFrame, parseLines } from "./frames";

export const clamp = {
  extrapolateLeft: "clamp",
  extrapolateRight: "clamp",
} as const;

export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

// 0 -> 1 progress of an entrance that starts at `start` and lasts `frames`.
export const enterProgress = (frame: number, start: number, frames = motion.enterFrames) =>
  interpolate(frame, [start, start + frames], [0, 1], { ...clamp, easing: easeOut });

