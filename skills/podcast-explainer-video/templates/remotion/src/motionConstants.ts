// Timing constants with no imports, so pure modules (worldState, compareState, visibleText,
// captionPages) and node-run tests can use them without loading fonts or React.
// theme.ts re-exports them; change them here only.

// A visual state change lands on or just before its word: cues start this many frames early.
export const LEAD_FRAMES = 3;

// A09: the one entrance duration. Every scene fade-in (Stage, WorldScene, CompareScene) lasts
// ENTRANCE_FRAMES at 30 fps = ENTRANCE_MS. Keep it at or below the default 250 ms gap between turns
// (tts.py --gap-ms), so build_manifest.py ENTER_MS (must equal ENTRANCE_MS) can start the fade in
// the silence before the anchor word and the fade never overlaps speech. Change both together.
export const ENTRANCE_FRAMES = 7;
export const ENTRANCE_MS = 233; // round(7 * 1000 / 30)

// Steps without a cue (placeholder builds) fall back to the scene start plus this many frames
// for step i: STEP_FALLBACK_START + i * STEP_FALLBACK_FRAMES.
export const STEP_FALLBACK_START = 15;
export const STEP_FALLBACK_FRAMES = 45;

// Smallest rendered text at 1920x1080, in pixels. Anything smaller is a bug.
export const MIN_TEXT_PX = 28;
