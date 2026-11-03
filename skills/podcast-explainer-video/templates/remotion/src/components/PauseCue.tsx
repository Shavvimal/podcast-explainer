import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { useEpisode } from "../context";
import { colors, fonts, layout, radius, type } from "../theme";
import { clamp, easeOut, msToFrame } from "../time";
import type { PauseKind } from "../types";

// Pause-and-think cue (references/learning-design.md L10, L11). During a hold (the silence that
// tts.py inserts after a turn with holdAfterMs) it dims the stage and shows the prompt with a
// countdown ring. It never shows an answer: the answer is the next spoken turn, after the ring.
// Only holds that carry a pause kind and prompt get a cue. The card stays inside the stage, so it
// never covers the caption band (no one speaks during a hold, so the band is empty anyway).

const LABEL: Record<PauseKind, string> = {
  predict: "Predict",
  retrieve: "Recall",
  "explain-back": "Explain it back",
};

const FADE = 8; // frames

export const CARD = { w: 1240, h: 380 }; // centred in layout.stage; qc.py reads these numbers from this file

export const PauseCue: React.FC = () => {
  const { manifest } = useEpisode();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const nowMs = (frame / fps) * 1000;
  const hold = (manifest.holds ?? []).find(
    (h) => h.kind && h.prompt && h.startMs <= nowMs && nowMs < h.endMs,
  );
  if (!hold || !hold.kind || !hold.prompt) return null;

  const s = msToFrame(hold.startMs, fps);
  const e = msToFrame(hold.endMs, fps);
  const appear = interpolate(frame, [s, s + FADE, e - FADE, e], [0, 1, 1, 0], { ...clamp, easing: easeOut });
  const progress = interpolate(frame, [s, e], [0, 1], clamp); // 0 -> 1 over the hold
  const secondsLeft = Math.max(0, Math.ceil((hold.endMs - nowMs) / 1000));

  const R = 74;
  const C = 2 * Math.PI * R;
  const { stage } = layout;
  const left = stage.x + (stage.w - CARD.w) / 2;
  const top = stage.y + (stage.h - CARD.h) / 2;

  return (
    <>
      <div
        style={{
          position: "absolute",
          left: stage.x,
          top: stage.y,
          width: stage.w,
          height: stage.h,
          background: colors.bg,
          opacity: 0.62 * appear,
        }}
      />
      <div
        style={{
          position: "absolute",
          left,
          top,
          width: CARD.w,
          height: CARD.h,
          boxSizing: "border-box",
          padding: "40px 56px",
          display: "flex",
          alignItems: "center",
          gap: 52,
          borderRadius: radius.card,
          background: colors.surfaceRaised,
          border: `3px solid ${colors.warn}`,
          fontFamily: fonts.sans,
          opacity: appear,
          translate: `0px ${(1 - appear) * 24}px`,
        }}
      >
        <svg width={2 * R + 24} height={2 * R + 24} viewBox={`0 0 ${2 * R + 24} ${2 * R + 24}`} style={{ flexShrink: 0 }}>
          <circle cx={R + 12} cy={R + 12} r={R} fill="none" stroke={colors.line} strokeWidth={14} />
          <circle
            cx={R + 12}
            cy={R + 12}
            r={R}
            fill="none"
            stroke={colors.warn}
            strokeWidth={14}
            strokeLinecap="round"
            strokeDasharray={C}
            strokeDashoffset={C * progress}
            transform={`rotate(-90 ${R + 12} ${R + 12})`}
          />
          <text
            x={R + 12}
            y={R + 12}
            textAnchor="middle"
            dominantBaseline="central"
            fill={colors.text}
            style={{ fontFamily: fonts.sans, fontSize: type.heading, fontWeight: 800 }}
          >
            {secondsLeft}
          </text>
        </svg>
        <div style={{ display: "flex", flexDirection: "column", gap: 18, minWidth: 0 }}>
          <div style={{ fontSize: type.body, fontWeight: 800, color: colors.warn, letterSpacing: 2, textTransform: "uppercase" }}>
            Pause and think · {LABEL[hold.kind]}
          </div>
          <div style={{ fontSize: type.heading - 4, fontWeight: 700, color: colors.text, lineHeight: 1.2 }}>{hold.prompt}</div>
        </div>
      </div>
    </>
  );
};
