import { Audio } from "@remotion/media";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { ChapterLabel } from "./components/ChapterLabel";
import { KeywordChips } from "./components/KeywordChips";
import { PauseCue } from "./components/PauseCue";
import { SpeakerCaptions } from "./components/SpeakerCaptions";
import { SpeakerRail } from "./components/SpeakerRail";
import { EnterFramesContext, EpisodeContext, episodeFile } from "./context";
import { resolveScene } from "./scenes";
import { entranceFrames } from "./frames";
import { colors, fonts } from "./theme";
import { msToFrame } from "./time";
import type { Manifest } from "./types";

export type EpisodeProps = { slug: string; manifest: Manifest | null };

// One master <Audio>, one <Sequence> per scene at manifest times. Never TransitionSeries:
// transitions would overlap scenes and shorten the timeline, and the audio clock must not move.
export const Episode: React.FC<EpisodeProps> = ({ slug, manifest }) => {
  const { fps, durationInFrames } = useVideoConfig();
  if (!manifest) return <AbsoluteFill style={{ backgroundColor: colors.bg }} />;

  return (
    <EpisodeContext.Provider value={{ manifest, slug }}>
      <AbsoluteFill style={{ backgroundColor: colors.bg, fontFamily: fonts.sans, color: colors.text }}>
        {manifest.audio.src ? <Audio src={episodeFile(slug, manifest.audio.src)} /> : null}

        {manifest.scenes.map((scene, i) => {
          const from = msToFrame(scene.startMs, fps);
          const isLast = i === manifest.scenes.length - 1;
          const end = isLast ? durationInFrames : msToFrame(scene.endMs, fps);
          const prev = manifest.scenes[i - 1];
          const Component = resolveScene(scene);
          // A09: build_manifest.py sets enterMs; entranceFrames() then fits the fade in whole frames
          // before the next speech start (a scene that starts inside speech cuts), so no word falls inside it.
          const enterFrames = entranceFrames(scene.startMs, scene.enterMs, manifest.turns, fps);
          const shared = prev && prev.type === "world" && scene.type === "world";
          return (
            <Sequence
              key={scene.id}
              name={`${scene.id} ${scene.type}`}
              from={from}
              durationInFrames={Math.max(1, end - from)}
              premountFor={fps}
            >
              <EnterFramesContext.Provider value={Math.max(1, enterFrames)}>
                <Component
                  {...scene.props}
                  sceneId={scene.id}
                  sceneStartMs={scene.startMs}
                  sceneEndMs={scene.endMs}
                  fromFrame={from}
                  enter={!shared && enterFrames > 0}
                />
              </EnterFramesContext.Provider>
            </Sequence>
          );
        })}

        <PauseCue />
        <ChapterLabel />
        <KeywordChips />
        <SpeakerRail />
        <SpeakerCaptions />
      </AbsoluteFill>
    </EpisodeContext.Provider>
  );
};
