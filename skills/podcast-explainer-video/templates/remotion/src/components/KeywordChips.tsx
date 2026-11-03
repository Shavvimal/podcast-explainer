import { useMemo } from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useEpisode } from "../context";
import { chipFrames, visualStepTimes } from "../overlayState";
import { claimText, claimTextProblems } from "../scenes/compareState";
import { colors, fonts, layout, type } from "../theme";
import { clamp } from "../time";

const MAX_VISIBLE = 3;

// Keyword chips (manifest.overlays, type "chip") sit in one row in the top-right corner,
// above the stage, in start order from the right. At most three show at once.
// A chip springs in on its start frame and fades out over 8 frames at its end. W11b: the end is the
// next visual step after the chip (overlayState.ts chipFrames) unless the chip has persist: true.
export const KeywordChips: React.FC = () => {
  const { manifest } = useEpisode();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const times = useMemo(() => visualStepTimes(manifest), [manifest]);
  // W13b (Q05): a chip whose written count disagrees with its claim stops the render.
  useMemo(() => {
    const bad = manifest.overlays.filter((o) => o.type === "chip").flatMap((o) => claimTextProblems(o.props.text, o.props.claim).map((m) => `chip ${o.id}: ${m}`));
    if (bad.length) throw new Error(bad.join("; "));
  }, [manifest]);
  const live = manifest.overlays
    .filter((o) => o.type === "chip")
    .map((o) => {
      const w = chipFrames(o, times, fps);
      return { o, s: w.start, e: w.end };
    })
    .filter(({ s, e }) => frame >= s && frame < e + 8)
    .slice(-MAX_VISIBLE);

  return (
    <div
      style={{
        position: "absolute",
        top: layout.chips.top,
        right: layout.chips.right,
        display: "flex",
        flexDirection: "row-reverse",
        alignItems: "center",
        gap: 12,
      }}
    >
      {live.map(({ o, s, e }) => {
        const inP = spring({ frame: frame - s, fps, config: { damping: 200 }, durationInFrames: 10 });
        const outP = interpolate(frame, [e, e + 8], [1, 0], clamp);
        const color = o.props.color ?? colors.accent;
        return (
          <div
            key={o.id}
            style={{
              opacity: Math.min(inP, outP),
              translate: `${(1 - inP) * 40}px 0px`,
              padding: "3px 20px",
              borderRadius: 999,
              background: colors.surfaceRaised,
              border: `3px solid ${color}`,
              color: colors.text,
              fontFamily: fonts.sans,
              fontWeight: 700,
              fontSize: type.body, // R01: 36 px, readable at phone width
              whiteSpace: "nowrap",
            }}
          >
            {claimText(o.props.text, o.props.claim)}
          </div>
        );
      })}
    </div>
  );
};
