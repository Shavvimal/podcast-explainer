// Register bespoke scene components here. scenes.json selects one with
// { "type": "custom", "props": { "component": "BucketFill", ... } }.
// See references/visuals.md, "Write a bespoke scene", for the rules.
import type React from "react";
import type { SceneProps } from "../../types";
import { BucketFill } from "./BucketFill";
import { RingLoad } from "./RingLoad";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const CUSTOM_SCENES: Record<string, React.FC<SceneProps<any>>> = {
  BucketFill,
  RingLoad,
};
