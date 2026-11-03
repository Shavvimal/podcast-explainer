import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { useEpisode } from "../context";
import { colors, fonts, layout, type } from "../theme";
import { clamp, msToFrame } from "../time";

// Top-left chapter marker: the current segment's title, when the segment has one.
// Hidden on title, recap and check cards, which carry their own heading.
export const ChapterLabel: React.FC = () => {
  const { manifest } = useEpisode();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const nowMs = (frame / fps) * 1000;

  const scene = manifest.scenes.find((s) => s.startMs <= nowMs && nowMs < s.endMs);
  if (scene && (scene.type === "title" || scene.type === "recap" || scene.type === "check")) return null;

  const idx = manifest.segments.findIndex((s) => s.startMs <= nowMs && nowMs < s.endMs);
  const seg = manifest.segments[idx];
  if (!seg?.title) return null;
  const s = msToFrame(seg.startMs, fps);
  const opacity = interpolate(frame, [s, s + 12], [0, 1], clamp);

  return (
    <div
      style={{
        position: "absolute",
        left: layout.chapter.left,
        top: layout.chapter.top,
        display: "flex",
        alignItems: "center",
        gap: 14,
        opacity,
        fontFamily: fonts.sans,
        fontSize: type.body, // R01: chrome text at the 36 px phone size
        fontWeight: 700,
        color: colors.muted,
      }}
    >
      <span style={{ color: colors.accent }}>{String(idx + 1).padStart(2, "0")}</span>
      <span>{seg.title}</span>
    </div>
  );
};
