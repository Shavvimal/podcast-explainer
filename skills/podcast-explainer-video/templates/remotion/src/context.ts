import { createContext, useContext } from "react";
import { staticFile } from "remotion";
import { ENTRANCE_FRAMES } from "./motionConstants";
import type { Manifest } from "./types";

export type EpisodeContextValue = { manifest: Manifest; slug: string };

export const EpisodeContext = createContext<EpisodeContextValue | null>(null);

export const useEpisode = (): EpisodeContextValue => {
  const ctx = useContext(EpisodeContext);
  if (!ctx) throw new Error("useEpisode() must be used inside <Episode>.");
  return ctx;
};

// A09: the entrance length of the scene being drawn, in frames. Episode sets it per scene from
// episode.json scenes[].enterMs (build_manifest.py shortens an entrance to the silence before its
// turn, 0 = cut) and falls back to ENTRANCE_FRAMES. Stage, WorldScene and CompareScene read it.
export const EnterFramesContext = createContext<number>(ENTRANCE_FRAMES);
export const useEnterFrames = () => useContext(EnterFramesContext);

// Files in the manifest (audio, diagrams, avatars) are relative to public/episodes/<slug>/.
export const episodeFile = (slug: string, rel: string) =>
  staticFile(`episodes/${slug}/${rel.replace(/^\.?\//, "")}`);
