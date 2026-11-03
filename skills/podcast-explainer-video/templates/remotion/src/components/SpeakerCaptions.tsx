import { useMemo } from "react";
import { Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useEpisode } from "../context";
import { colors, fonts, layout, type } from "../theme";
import { msToFrame } from "../time";
import type { Word } from "../types";
import { buildCaptionPages } from "./captionPages";

// Speaker-coloured captions in the bottom band.
// karaoke: a 3-7 word page; spoken words turn white, the current word takes the speaker colour.
// pop: 1-3 words; each word springs in on its start frame.
// A word lights on the frame its startMs maps to (msToFrame), never earlier.
// Pages never start inside a pause-and-think hold that comes before their words (N05).
export const SpeakerCaptions: React.FC = () => {
  const { manifest } = useEpisode();
  const { fps } = useVideoConfig();
  const { mode, maxCharsPerSecond, minPageMs } = manifest.captions;

  const pages = useMemo(
    () => (mode === "off" ? [] : buildCaptionPages(manifest.turns, mode, maxCharsPerSecond, minPageMs, manifest.holds ?? [])),
    [manifest.turns, mode, maxCharsPerSecond, minPageMs, manifest.holds],
  );
  const speakers = useMemo(
    () => Object.fromEntries(manifest.speakers.map((s) => [s.id, s])),
    [manifest.speakers],
  );

  if (mode === "off") return null;

  return (
    <>
      {pages.map((p) => {
        const from = msToFrame(p.startMs, fps);
        const dur = Math.max(1, msToFrame(p.endMs, fps) - from);
        return (
          <Sequence key={p.key} name={`caption ${p.key}`} from={from} durationInFrames={dur} layout="none">
            <CaptionPageView
              words={p.words}
              fromFrame={from}
              color={speakers[p.speaker]?.color ?? colors.accent}
              mode={mode}
            />
          </Sequence>
        );
      })}
    </>
  );
};

const CaptionPageView: React.FC<{
  words: Word[];
  fromFrame: number;
  color: string;
  mode: "karaoke" | "pop";
}> = ({ words, fromFrame, color, mode }) => {
  const local = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { manifest } = useEpisode();
  const abs = fromFrame + local;

  // Hide captions while the active scene asks for none (for example a dense diagram).
  const nowMs = (abs / fps) * 1000;
  const scene = manifest.scenes.find((s) => s.startMs <= nowMs && nowMs < s.endMs);
  if (scene?.captions === "off") return null;
  // N05 second layer: inside a hold, a page whose speech starts after the hold is never drawn,
  // so the pause card never sits above the answer.
  const firstWordMs = words[0]?.startMs ?? 0;
  if ((manifest.holds ?? []).some((h) => h.startMs <= nowMs && nowMs < h.endMs && firstWordMs >= h.endMs)) return null;

  const starts = words.map((w) => msToFrame(w.startMs, fps));
  let current = -1;
  starts.forEach((s, i) => {
    if (abs >= s) current = i;
  });

  return (
    <div
      style={{
        position: "absolute",
        left: 300,
        width: 1320,
        top: layout.band.y,
        height: layout.band.h,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          maxWidth: 1320,
          padding: "14px 30px",
          borderRadius: 18,
          background: colors.captionPanel,
          borderLeft: `8px solid ${color}`,
          fontFamily: fonts.sans,
          fontSize: type.caption,
          fontWeight: 700,
          lineHeight: 1.25,
          textAlign: "center",
          letterSpacing: "-0.01em",
        }}
      >
        {words.map((w, i) => {
          const spoken = i <= current;
          const isCurrent = i === current;
          if (mode === "pop") {
            // Unspoken words keep their space (opacity 0) so the line does not jump.
            const pop = spoken
              ? spring({ frame: abs - starts[i], fps, config: { damping: 200 }, durationInFrames: 8 })
              : 0;
            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  marginRight: "0.28em",
                  color: isCurrent ? color : colors.text,
                  scale: String(0.85 + 0.15 * pop),
                  opacity: pop,
                }}
              >
                {w.text}
              </span>
            );
          }
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                marginRight: "0.28em",
                color: isCurrent ? color : spoken ? colors.text : colors.dim,
              }}
            >
              {w.text}
            </span>
          );
        })}
      </div>
    </div>
  );
};
