import type React from "react";
import type { Scene, SceneProps } from "../types";
import { CheckYourselfCard } from "./CheckYourselfCard";
import { CodeScene } from "./CodeScene";
import { CompareScene } from "./CompareScene";
import { CUSTOM_SCENES } from "./custom";
import { DiagramScene } from "./DiagramScene";
import { EquationScene } from "./EquationScene";
import { MatrixScene } from "./MatrixScene";
import { RecapCard } from "./RecapCard";
import { TitleScene } from "./TitleScene";
import { WorldScene } from "./world/WorldScene";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyScene = React.FC<SceneProps<any>>;

export const SCENES: Record<string, AnyScene> = {
  title: TitleScene,
  world: WorldScene,
  diagram: DiagramScene,
  code: CodeScene,
  equation: EquationScene,
  recap: RecapCard,
  check: CheckYourselfCard,
  compare: CompareScene,
  matrix: MatrixScene,
};

// type "custom" picks a bespoke component by props.component from src/scenes/custom/index.ts.
export const resolveScene = (scene: Scene): AnyScene => {
  if (scene.type === "custom") {
    const name = String((scene.props as { component?: string }).component ?? "");
    const C = CUSTOM_SCENES[name];
    if (!C) {
      throw new Error(
        `Scene ${scene.id}: custom component "${name}" is not registered. Create src/scenes/custom/${name}.tsx ` +
          `exporting a React.FC<SceneProps<...>>, then add it to CUSTOM_SCENES in src/scenes/custom/index.ts.`,
      );
    }
    return C;
  }
  const C = SCENES[scene.type];
  if (!C) {
    throw new Error(
      `Scene ${scene.id}: unknown type "${scene.type}". Use one of ${Object.keys(SCENES).join(", ")}, or "custom".`,
    );
  }
  return C;
};
