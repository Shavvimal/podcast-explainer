import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts, radius, type } from "../theme";
import { clamp, cueFrame, easeOut } from "../time";
import type { SceneProps } from "../types";
import { Stage } from "./common";

export type RecapPoint = { text: string; atMs?: number };
export type RecapProps = { title?: string; points: RecapPoint[] };

const STEP_FALLBACK_FRAMES = 30;

// Recap card: up to four numbered points, each on its cue (or staggered when uncued).
export const RecapCard: React.FC<SceneProps<RecapProps>> = ({ title = "Recap", points, fromFrame, enter }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <Stage enter={enter} heading={title}>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 22, paddingBottom: 40 }}>
        {points.slice(0, 4).map((pt, i) => {
          const c = cueFrame(pt.atMs, 12 + i * STEP_FALLBACK_FRAMES, fromFrame, fps);
          const p = interpolate(frame, [c, c + 12], [0, 1], { ...clamp, easing: easeOut });
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 28,
                padding: "22px 30px",
                borderRadius: radius.card,
                background: colors.surface,
                opacity: p,
                translate: `${(1 - p) * -40}px 0px`,
                fontFamily: fonts.sans,
              }}
            >
              <div
                style={{
                  width: 64,
                  height: 64,
                  flexShrink: 0,
                  borderRadius: 999,
                  background: colors.accent,
                  color: colors.bg,
                  fontWeight: 800,
                  fontSize: type.body,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {i + 1}
              </div>
              <div style={{ fontSize: type.body + 2, fontWeight: 600, color: colors.text, lineHeight: 1.25 }}>{pt.text}</div>
            </div>
          );
        })}
      </div>
    </Stage>
  );
};
