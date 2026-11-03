import { getWaveformPortion, useWindowedAudioData } from "@remotion/media-utils";
import { Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { episodeFile, useEpisode } from "../context";
import { colors, fonts, layout, type } from "../theme";
import { clamp, msToFrame } from "../time";
import type { Speaker, Turn } from "../types";

const BADGE = 92;

// Two speaker badges in the bottom band (left and right of the captions).
// The active speaker comes from the manifest turn times, not from the audio.
export const SpeakerRail: React.FC = () => {
  const { manifest } = useEpisode();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const showWave = manifest.rail.waveform && manifest.audio.src !== null;

  return (
    <>
      {manifest.speakers.map((s) => {
        const on = activeAmount(manifest.turns, s.id, frame, fps);
        return <Badge key={s.id} speaker={s} on={on} />;
      })}
      {showWave ? <RailWaveform /> : null}
    </>
  );
};

// 0 (idle) .. 1 (speaking). Springs up at the turn start, fades over 6 frames after the turn end.
const activeAmount = (turns: Turn[], speakerId: string, frame: number, fps: number) => {
  let best = 0;
  for (const t of turns) {
    if (t.speaker !== speakerId) continue;
    const s = msToFrame(t.startMs, fps);
    const e = msToFrame(t.endMs, fps);
    if (frame < s || frame > e + 6) continue;
    const up = spring({ frame: frame - s, fps, config: { damping: 200 }, durationInFrames: 8 });
    const down = interpolate(frame, [e, e + 6], [1, 0], clamp);
    best = Math.max(best, Math.min(up, down));
  }
  return best;
};

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .map((p) => p[0]!.toUpperCase())
    .slice(0, 2)
    .join("");

const Badge: React.FC<{ speaker: Speaker; on: number }> = ({ speaker, on }) => {
  const { slug } = useEpisode();
  const isLeft = speaker.side === "left";
  return (
    <div
      style={{
        position: "absolute",
        top: layout.band.y + (layout.band.h - BADGE - 44) / 2,
        [isLeft ? "left" : "right"]: layout.stage.x,
        width: 180,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 6,
        opacity: interpolate(on, [0, 1], [0.55, 1]),
        scale: String(interpolate(on, [0, 1], [0.9, 1])),
      }}
    >
      <div
        style={{
          width: BADGE,
          height: BADGE,
          borderRadius: 999,
          background: colors.surfaceRaised,
          outline: `${interpolate(on, [0, 1], [2, 6])}px solid ${speaker.color}`,
          outlineOffset: 3,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          fontFamily: fonts.sans,
          fontWeight: 800,
          fontSize: 38,
          color: speaker.color,
        }}
      >
        {speaker.avatar ? (
          <Img src={episodeFile(slug, speaker.avatar)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          initials(speaker.name)
        )}
      </div>
      <div style={{ fontFamily: fonts.sans, fontSize: type.body, fontWeight: 700, color: colors.text, lineHeight: 1.1 }}>
        {speaker.name}
      </div>
    </div>
  );
};

// Optional level meter under the active badge. One mixed track, so the level is gated by the
// active speaker from the manifest. Uses windowed audio data so long episodes load in pieces.
const RailWaveform: React.FC = () => {
  const { manifest, slug } = useEpisode();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const src = episodeFile(slug, manifest.audio.src!);
  const { audioData, dataOffsetInSeconds } = useWindowedAudioData({ src, frame, fps, windowInSeconds: 30 });
  const nowMs = (frame / fps) * 1000;
  const turn = manifest.turns.find((t) => t.startMs <= nowMs && nowMs < t.endMs);
  if (!audioData || !turn) return null;
  const speaker = manifest.speakers.find((s) => s.id === turn.speaker);
  if (!speaker) return null;
  const bars = getWaveformPortion({
    audioData,
    startTimeInSeconds: frame / fps,
    durationInSeconds: 0.25,
    numberOfSamples: 7,
    dataOffsetInSeconds,
  });
  const isLeft = speaker.side === "left";
  return (
    <div
      style={{
        position: "absolute",
        top: layout.band.y + 8,
        [isLeft ? "left" : "right"]: layout.stage.x + 180 + 4,
        height: BADGE,
        display: "flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      {bars.map((b) => (
        <div
          key={b.index}
          style={{ width: 6, height: 8 + b.amplitude * 70, borderRadius: 3, background: speaker.color }}
        />
      ))}
    </div>
  );
};
