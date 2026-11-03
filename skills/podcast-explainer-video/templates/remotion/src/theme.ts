// Design tokens for every scene. Change the look here, not inside components.
// Contrast: every text colour below reaches at least 4.5:1 on `bg` and on `surface`
// (WCAG relative-luminance formula, computed 2 Nov 2026). Speaker colours come from script.json:
// the defaults #4F8CFF (5.9:1) and #FFB020 (10.3:1) pass; check any new one. Opacity dimming of
// non-focus content lowers contrast on purpose; focused content always stays at full contrast.
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";
import { ENTRANCE_FRAMES, LEAD_FRAMES, MIN_TEXT_PX } from "./motionConstants";
import { GRID_TEXT_PX } from "./scenes/tableLayout";

const inter = loadInter("normal", {
  weights: ["400", "600", "700", "800"],
  subsets: ["latin"],
});
const mono = loadMono("normal", { weights: ["400", "700"], subsets: ["latin"] });

export const fonts = {
  sans: inter.fontFamily,
  mono: mono.fontFamily,
};

export const colors = {
  bg: "#0E1117", // page background
  surface: "#171C26", // cards, nodes, code panel
  surfaceRaised: "#202736",
  line: "#3A4356", // borders and idle edges (non-text, 3:1 is enough)
  text: "#F2F4F8", // 17.2:1 on bg, 15.5:1 on surface
  muted: "#A9B1C2", // 8.8:1 on bg, 7.9:1 on surface
  dim: "#8E97AA", // unspoken caption words: 6.4:1 on bg
  accent: "#7CC4FF", // focus ring, highlights: 10.1:1 on bg
  good: "#5BD69A", // correct answer: 10.4:1 on bg
  warn: "#FFB020", // 10.3:1 on bg
  bad: "#FF7A7A", // 7.5:1 on bg
  captionPanel: "rgba(14,17,23,0.88)",
};

// Type scale in px at 1920x1080. Nothing renders below `min`.
export const type = {
  min: MIN_TEXT_PX,
  label: 30,
  grid: GRID_TEXT_PX, // 36: compare table cells, headers and row labels (readable at phone width)
  body: 36,
  caption: 46,
  heading: 56,
  title: 96,
  code: 30,
  equation: 60,
};

// Safe areas at 1920x1080: action-safe 5 %, title-safe 10 %.
export const safe = {
  actionX: 96,
  actionY: 54,
  titleX: 192,
  titleY: 108,
};

// Screen regions. Scenes draw inside `stage`; captions and the speaker rail own `band`.
export const layout = {
  width: 1920,
  height: 1080,
  stage: { x: 96, y: 124, w: 1728, h: 712 },
  band: { y: 852, h: 174 }, // 852..1026, bottom edge inside action-safe
  chips: { right: 96, top: 54 },
  chapter: { left: 96, top: 54 },
};

// Timing constants live in motionConstants.ts (no imports, so pure modules and tests can use them).
export { ENTRANCE_FRAMES, ENTRANCE_MS, LEAD_FRAMES, MIN_TEXT_PX } from "./motionConstants";

export const motion = {
  // A visual change lands on or just before the word: cues start this many frames early.
  leadFrames: LEAD_FRAMES,
  enterFrames: ENTRANCE_FRAMES, // A09: 7 frames = 233 ms, at or below the default 250 ms gap
  cameraMs: 800,
  focusMs: 300,
};

export const radius = { card: 20, chip: 999, node: 18 };
