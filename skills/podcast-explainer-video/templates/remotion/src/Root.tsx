import { CalculateMetadataFunction, Composition, staticFile } from "remotion";
import { Episode, type EpisodeProps } from "./Episode";
import type { Manifest } from "./types";

// Reads public/episodes/<slug>/episode.json (written by scripts/build_manifest.py) and sizes
// the composition from the audio: durationInFrames = ceil((audio.durationMs + video.tailMs) * fps).
const calculateMetadata: CalculateMetadataFunction<EpisodeProps> = async ({
  props,
  abortSignal,
}) => {
  const path = `episodes/${props.slug}/episode.json`;
  const res = await fetch(staticFile(path), { signal: abortSignal });
  if (!res.ok) {
    throw new Error(
      `Cannot load public/${path} (HTTP ${res.status}). Run build_manifest.py --slug ${props.slug} first.`,
    );
  }
  const manifest = (await res.json()) as Manifest;
  if (manifest.version !== 1 || !manifest.video || !manifest.audio) {
    throw new Error(`public/${path} is not an episode manifest (version 1 with video and audio).`);
  }
  const { fps, width, height, tailMs } = manifest.video;
  return {
    fps,
    width,
    height,
    durationInFrames: Math.max(1, Math.ceil(((manifest.audio.durationMs + tailMs) / 1000) * fps)),
    props: { ...props, manifest },
    defaultOutName: manifest.id,
  };
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Episode"
    component={Episode}
    durationInFrames={300}
    fps={30}
    width={1920}
    height={1080}
    defaultProps={{ slug: "sample", manifest: null } satisfies EpisodeProps}
    calculateMetadata={calculateMetadata}
  />
);
