// Example bespoke scene, paradigm "discrete process timeline": build the per-step state once,
// outside the render path, then index it by the current time. No useState, no timers,
// no Math.random() (use random("seed") from remotion when you need noise).
import { useMemo } from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts, radius, type } from "../../theme";
import { clamp, cueFrame } from "../../time";
import type { SceneProps } from "../../types";
import { Stage } from "../common";

export type BucketFillProps = {
  title?: string;
  buckets: number; // 4 to 8 fit the stage
  inserts: { key: string; hash: number; atMs?: number }[]; // hash given by the script, never invented
};

type Placed = { key: string; bucket: number; slot: number; step: number };

// Pure: the state after every insert. Collisions chain downwards in the bucket.
const buildTimeline = (buckets: number, inserts: BucketFillProps["inserts"]): Placed[] => {
  const depth = new Array(buckets).fill(0);
  return inserts.map((ins, step) => {
    const bucket = ((ins.hash % buckets) + buckets) % buckets;
    const slot = depth[bucket]++;
    return { key: ins.key, bucket, slot, step };
  });
};

export const BucketFill: React.FC<SceneProps<BucketFillProps>> = ({ title, buckets, inserts, fromFrame, enter }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const placed = useMemo(() => buildTimeline(buckets, inserts), [buckets, inserts]);
  const cues = inserts.map((ins, i) => cueFrame(ins.atMs, 15 + i * 30, fromFrame, fps));

  const colW = Math.min(200, Math.floor(1600 / buckets));
  return (
    <Stage enter={enter} heading={title}>
      <div style={{ position: "absolute", inset: 0, display: "flex", justifyContent: "center", gap: 20, fontFamily: fonts.sans }}>
        {Array.from({ length: buckets }, (_, b) => {
          const here = placed.filter((p) => p.bucket === b);
          const hot = here.some((p) => frame >= cues[p.step] && frame < cues[p.step] + 20);
          return (
            <div key={b} style={{ width: colW, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
              <div style={{ fontFamily: fonts.mono, fontSize: type.label, color: hot ? colors.accent : colors.muted, fontWeight: 700 }}>
                [{b}]
              </div>
              <div
                style={{
                  width: colW,
                  height: 440,
                  borderRadius: radius.card,
                  border: `3px solid ${hot ? colors.accent : colors.line}`,
                  background: colors.surface,
                  position: "relative",
                }}
              >
                {here.map((p) => {
                  const s = spring({ frame: frame - cues[p.step], fps, config: { damping: 14 }, durationInFrames: 20 });
                  if (frame < cues[p.step]) return null;
                  return (
                    <div
                      key={p.key}
                      style={{
                        position: "absolute",
                        left: 12,
                        right: 12,
                        top: 12 + p.slot * 84,
                        height: 72,
                        borderRadius: 14,
                        background: colors.surfaceRaised,
                        border: `3px solid ${p.slot > 0 ? colors.warn : colors.accent}`,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: type.label,
                        fontWeight: 700,
                        color: colors.text,
                        opacity: interpolate(s, [0, 0.3], [0, 1], clamp),
                        translate: `0px ${(1 - s) * -120}px`,
                      }}
                    >
                      {p.key}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </Stage>
  );
};
