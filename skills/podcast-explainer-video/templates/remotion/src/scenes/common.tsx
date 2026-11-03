import type { ReactNode } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { useEnterFrames } from "../context";
import { colors, fonts, layout, type } from "../theme";
import { clamp, easeOut } from "../time";

// Stage wrapper used by every scene: fades in over the scene's entrance (useEnterFrames: episode.json
// enterMs, else ENTRANCE_FRAMES) unless `enter` is false,
// and confines content to the stage rectangle so nothing reaches the caption band.
export const Stage: React.FC<{ enter: boolean; children: ReactNode; heading?: string }> = ({
  enter,
  children,
  heading,
}) => {
  const frame = useCurrentFrame();
  const enterFrames = useEnterFrames();
  const p = enter ? interpolate(frame, [0, enterFrames], [0, 1], { ...clamp, easing: easeOut }) : 1;
  const { x, y, w, h } = layout.stage;
  return (
    <AbsoluteFill style={{ opacity: p }}>
      <div
        style={{
          position: "absolute",
          left: x,
          top: y,
          width: w,
          height: h,
          display: "flex",
          flexDirection: "column",
          translate: `0px ${(1 - p) * 16}px`,
        }}
      >
        {heading ? <Heading text={heading} /> : null}
        <div style={{ position: "relative", flex: 1, minHeight: 0 }}>{children}</div>
      </div>
    </AbsoluteFill>
  );
};

export const Heading: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      fontFamily: fonts.sans,
      fontSize: type.heading,
      fontWeight: 800,
      color: colors.text,
      letterSpacing: "-0.02em",
      marginBottom: 24,
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis",
    }}
  >
    {text}
  </div>
);

// Shared prop shape for anything revealed on a cue. `atMs` comes from build_manifest.py.
export type Cued = { atMs?: number };
