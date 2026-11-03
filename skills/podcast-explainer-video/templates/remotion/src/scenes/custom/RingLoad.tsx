// Example of a custom scene that CONTINUES the persistent world instead of starting a fresh one.
// Its props.worldSteps join the episode's world timeline (build_manifest.py validates them like
// world steps), so whatever it reveals or hides is still true when a later world scene returns.
// It draws the shared world on the left with WorldCanvas and, on the right, one bar per visible
// owner with the number of items it owns now (computed from the same ownership state).
import { useMemo } from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { colors, fonts, type } from "../../theme";
import { clamp } from "../../time";
import type { SceneProps, WorldStep } from "../../types";
import { fitCamera } from "../CompareScene";
import { Stage } from "../common";
import { useSharedWorld, WorldCanvas } from "../world/WorldScene";
import { ownershipAt, placeNodes, ringInsetFilter, visibilityAt } from "../world/worldState";

export type RingLoadProps = {
  title?: string;
  worldSteps?: WorldStep[]; // shared-timeline steps (atMs resolved by build_manifest.py)
};

export const RingLoad: React.FC<SceneProps<RingLoadProps>> = ({ title, fromFrame, enter }) => {
  const shared = useSharedWorld(fromFrame);
  const frame = useCurrentFrame();
  if (!shared) throw new Error("RingLoad needs a top-level ring world in scenes.json.");
  const { world, timeline, nowMs } = shared;
  const nodes = useMemo(() => placeNodes(world), [world]);
  const leftW = 900;
  const h = title ? 712 - 80 : 712;
  const camera = useMemo(() => fitCamera(world, leftW, h), [world, h]);
  const own = ownershipAt(world, nodes, timeline, nowMs);
  const vis = visibilityAt(world, timeline, nowMs);
  // Bars count only coloured items, so they never state a result before the ring shows it.
  const owners = nodes.filter((n) => n.role === "owner" && vis[n.id]?.on);
  const counts: Record<string, number> = {};
  for (const n of nodes) {
    if (n.role !== "item" || !vis[n.id]?.on || !own) continue;
    const o = own.owners[n.id];
    if (o && (own.colouredFrom[n.id] ?? -Infinity) <= nowMs) counts[o] = (counts[o] ?? 0) + 1;
  }
  const max = Math.max(1, ...Object.values(counts));
  const grow = interpolate(frame, [0, 12], [0, 1], clamp);
  return (
    <Stage enter={enter} heading={title}>
      <div style={{ position: "absolute", left: 0, top: 0, width: leftW, height: h, overflow: "hidden" }}>
        <WorldCanvas world={world} timeline={timeline} nowMs={nowMs} width={leftW} height={h} camera={camera} idPrefix="ringload" only={ringInsetFilter(world)} />
      </div>
      <div style={{ position: "absolute", left: leftW + 60, top: 40, right: 0, fontFamily: fonts.sans, display: "flex", flexDirection: "column", gap: 22 }}>
        <div style={{ fontSize: type.label, fontWeight: 700, color: colors.muted }}>items per owner</div>
        {owners.map((o) => (
          <div key={o.id} style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <div style={{ width: 70, fontSize: type.body, fontWeight: 800, color: o.color ?? colors.accent }}>{o.label}</div>
            <div style={{ height: 40, width: `${((counts[o.id] ?? 0) / max) * 480 * grow}px`, minWidth: 4, borderRadius: 8, background: o.color ?? colors.accent }} />
            <div style={{ fontSize: type.body, fontWeight: 700, color: colors.text, fontFamily: fonts.mono }}>{counts[o.id] ?? 0}</div>
          </div>
        ))}
      </div>
    </Stage>
  );
};
