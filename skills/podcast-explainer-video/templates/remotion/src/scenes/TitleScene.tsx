import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts, layout, type } from "../theme";
import { clamp, cueFrame, easeOut } from "../time";
import type { SceneProps } from "../types";

export type TitleProps = {
  title: string;
  subtitle?: string;
  kicker?: string; // small line above the title, e.g. the series name
  question?: string; // the opening puzzle; appears on its cue
  questionAtMs?: number;
};

// Opening card: kicker, title, subtitle, then the puzzle question on its cue.
export const TitleScene: React.FC<SceneProps<TitleProps>> = ({
  title,
  subtitle,
  kicker,
  question,
  questionAtMs,
  fromFrame,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 20 });
  const sub = interpolate(frame, [12, 30], [0, 1], { ...clamp, easing: easeOut });
  const qStart = cueFrame(questionAtMs, 45, fromFrame, fps);
  const q = interpolate(frame, [qStart, qStart + 12], [0, 1], { ...clamp, easing: easeOut });
  const { x, y, w, h } = layout.stage;

  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: x + 96,
          top: y,
          width: w - 192,
          height: h,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          fontFamily: fonts.sans,
        }}
      >
        {kicker ? (
          <div style={{ fontSize: type.label, fontWeight: 700, color: colors.accent, letterSpacing: "0.08em", textTransform: "uppercase", opacity: t }}>
            {kicker}
          </div>
        ) : null}
        <div
          style={{
            fontSize: type.title,
            fontWeight: 800,
            lineHeight: 1.05,
            letterSpacing: "-0.03em",
            color: colors.text,
            marginTop: 16,
            opacity: t,
            translate: `0px ${(1 - t) * 30}px`,
          }}
        >
          {title}
        </div>
        {subtitle ? (
          <div style={{ fontSize: type.heading - 12, fontWeight: 600, color: colors.muted, marginTop: 20, opacity: sub }}>
            {subtitle}
          </div>
        ) : null}
        {question ? (
          <div
            style={{
              marginTop: 56,
              padding: "24px 32px",
              borderRadius: 20,
              background: colors.surface,
              borderLeft: `8px solid ${colors.warn}`,
              fontSize: type.body + 4,
              fontWeight: 700,
              color: colors.text,
              opacity: q,
              translate: `${(1 - q) * -30}px 0px`,
              alignSelf: "flex-start",
              maxWidth: w - 192,
            }}
          >
            {question}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
