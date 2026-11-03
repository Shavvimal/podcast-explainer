import { evolvePath } from "@remotion/paths";
import { useEffect, useState } from "react";
import { interpolate, useCurrentFrame, useDelayRender, useVideoConfig } from "remotion";
import { episodeFile, useEpisode } from "../context";
import { sanitizeSvg } from "../svgSanitize";
import { colors, fonts, layout, motion, type } from "../theme";
import { clamp, cueFrame, easeOut } from "../time";
import type { SceneProps } from "../types";
import { Stage } from "./common";

// Data-only SVG element: an agent can draw a bespoke diagram as JSON, no code.
export type DiagramElement = {
  id: string;
  kind: "rect" | "circle" | "ellipse" | "line" | "arrow" | "path" | "polygon" | "text";
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  r?: number;
  rx?: number;
  ry?: number;
  x2?: number;
  y2?: number;
  d?: string;
  points?: string;
  text?: string;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  fontSize?: number;
  anchor?: "start" | "middle" | "end";
  draw?: boolean; // stroke draws on (evolvePath) instead of fading in; line, arrow and path only
  dashed?: boolean;
};

export type DiagramStep = { atMs?: number; reveal?: string[]; hide?: string[]; highlight?: string[] };

export type DiagramProps = {
  title?: string;
  viewBox?: string; // default "0 0 1728 600": one unit is one pixel under a heading
  svg?: string; // file relative to the episode folder, e.g. "diagrams/qkv.svg"; reveal by element id
  elements?: DiagramElement[];
  steps?: DiagramStep[];
};

const STEP_FALLBACK_FRAMES = 45;
// A non-highlighted element keeps 65% opacity while others are highlighted, so dimmed text keeps a
// contrast of at least 4.5:1 on the background (qc.py text.minsize ports this value).
export const DIAGRAM_DIM = 0.35;
const DIM = DIAGRAM_DIM;

// SVG reveal steps. Elements named in a step's `reveal` appear on that step's cue; elements never
// named are visible from the start. `hide` fades an element out for good. `highlight` recolours its elements and dims the rest.
export const DiagramScene: React.FC<SceneProps<DiagramProps>> = ({
  title,
  viewBox = "0 0 1728 600",
  svg,
  elements = [],
  steps = [],
  fromFrame,
  enter,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cues = steps.map((s, i) => cueFrame(s.atMs, 15 + i * STEP_FALLBACK_FRAMES, fromFrame, fps));
  const revealAt: Record<string, number> = {};
  steps.forEach((s, i) => (s.reveal ?? []).forEach((id) => (revealAt[id] ??= cues[i])));
  // `hide`: an element fades out on its first hide step and stays hidden (move a part by hiding the
  // old copy and revealing a new one). visibleText.ts and pe_common.visible_text drop its text then.
  const hideAt: Record<string, number> = {};
  steps.forEach((s, i) => (s.hide ?? []).forEach((id) => (hideAt[id] ??= cues[i])));
  let active = -1;
  cues.forEach((c, i) => {
    if (frame >= c) active = i;
  });
  const highlight = new Set(active >= 0 ? (steps[active].highlight ?? []) : []);
  // No text under type.min px: the viewBox scales to the stage (meet), so a wide viewBox shrinks
  // its text. minUnits is the smallest fontSize in viewBox units that still renders at 28 px.
  const [, , vbW, vbH] = viewBox.split(/[\s,]+/).map(Number);
  const availH = layout.stage.h - (title ? 92 : 0);
  const vbScale = vbW > 0 && vbH > 0 ? Math.min(layout.stage.w / vbW, availH / vbH) : 1;
  const minUnits = type.min / vbScale;
  const hiP = active >= 0 ? interpolate(frame, [cues[active], cues[active] + 9], [0, 1], clamp) : 0;

  const progress = (id: string, frames = motion.enterFrames + 6) => {
    const at = revealAt[id];
    const shown = at === undefined ? 1 : interpolate(frame, [at, at + frames], [0, 1], { ...clamp, easing: easeOut });
    const off = hideAt[id];
    if (off === undefined) return shown;
    return frame >= off ? shown * interpolate(frame, [off, off + motion.enterFrames], [1, 0], clamp) : shown;
  };

  return (
    <Stage enter={enter} heading={title}>
      {svg ? (
        <SvgFile src={svg} viewBox={viewBox} revealProgress={progress} ids={[...new Set([...Object.keys(revealAt), ...Object.keys(hideAt)])]} highlight={highlight} hiP={hiP} />
      ) : (
        <svg viewBox={viewBox} width="100%" height="100%" preserveAspectRatio="xMidYMid meet" style={{ overflow: "visible" }}>
          <defs>
            <marker id="diag-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
            </marker>
          </defs>
          {elements.map((el) => {
            const p = progress(el.id, el.draw ? 24 : motion.enterFrames + 6);
            if (p <= 0 || (hideAt[el.id] !== undefined && frame >= hideAt[el.id] + motion.enterFrames)) return null;
            const hi = highlight.has(el.id);
            const dimmed = highlight.size > 0 && !hi;
            return (
              <g key={el.id} opacity={(el.draw && hideAt[el.id] === undefined ? 1 : p) * (dimmed ? 1 - DIM * hiP : 1)}>
                <Element el={el} drawProgress={el.draw ? p : 1} highlighted={hi ? hiP : 0} minUnits={minUnits} />
              </g>
            );
          })}
        </svg>
      )}
    </Stage>
  );
};

const Element: React.FC<{ el: DiagramElement; drawProgress: number; highlighted: number; minUnits: number }> = ({
  el,
  drawProgress,
  highlighted,
  minUnits,
}) => {
  const stroke = highlighted > 0.5 ? colors.accent : (el.stroke ?? colors.line);
  const sw = (el.strokeWidth ?? 4) + 2 * highlighted;
  const fill = el.fill ?? (el.kind === "text" ? colors.text : "none");
  const common = { stroke, strokeWidth: sw, fill, strokeDasharray: el.dashed ? "14 12" : undefined };
  switch (el.kind) {
    case "rect":
      return <rect x={el.x} y={el.y} width={el.w} height={el.h} rx={el.rx ?? 16} {...common} fill={el.fill ?? colors.surface} />;
    case "circle":
      return <circle cx={el.x} cy={el.y} r={el.r} {...common} fill={el.fill ?? colors.surface} />;
    case "ellipse":
      return <ellipse cx={el.x} cy={el.y} rx={el.rx} ry={el.ry} {...common} fill={el.fill ?? colors.surface} />;
    case "polygon":
      return <polygon points={el.points} {...common} fill={el.fill ?? colors.surface} />;
    case "line":
    case "arrow":
    case "path": {
      const d = el.d ?? `M ${el.x} ${el.y} L ${el.x2} ${el.y2}`;
      const ev = drawProgress < 1 ? evolvePath(drawProgress, d) : null;
      return (
        <path
          d={d}
          {...common}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={ev ? ev.strokeDasharray : common.strokeDasharray}
          strokeDashoffset={ev ? ev.strokeDashoffset : undefined}
          markerEnd={el.kind === "arrow" && drawProgress > 0.95 ? "url(#diag-arrow)" : undefined}
        />
      );
    }
    case "text":
      return (
        <text
          x={el.x}
          y={el.y}
          textAnchor={el.anchor ?? "middle"}
          dominantBaseline="middle"
          fontFamily={fonts.sans}
          fontWeight={700}
          fontSize={Math.max(type.min, minUnits, el.fontSize ?? type.label)}
          fill={highlighted > 0.5 ? colors.accent : fill}
        >
          {el.text}
        </text>
      );
    default:
      return null;
  }
};

// External SVG file (for example a pre-rendered Mermaid diagram). Reveal and highlight work by
// element id through a generated <style>, so the file needs stable ids on the parts you cue.
// The markup passes sanitizeSvg (src/svgSanitize.ts) first: scripts, HTML, event attributes and
// external references fail the render with the file name.
const SvgFile: React.FC<{
  src: string;
  viewBox: string;
  ids: string[];
  revealProgress: (id: string) => number;
  highlight: Set<string>;
  hiP: number;
}> = ({ src, ids, revealProgress, highlight, hiP }) => {
  const { slug } = useEpisode();
  const [markup, setMarkup] = useState<string | null>(null);
  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender(`Loading diagram ${src}`));
  const scope = `diag-${src.replace(/[^a-z0-9]/gi, "-")}`;

  useEffect(() => {
    fetch(episodeFile(slug, src))
      .then((r) => {
        if (!r.ok) throw new Error(`Diagram ${src} not found in public/episodes/${slug}/ (HTTP ${r.status}).`);
        return r.text();
      })
      .then((t) => {
        // C04: allowlist check before the markup reaches the DOM; an unsafe file stops the render.
        // N07: <style> rules are rewritten under #scope, so they never reach the rest of the frame.
        setMarkup(sanitizeSvg(t, src, scope));
        continueRender(handle);
      })
      .catch((e) => cancelRender(e));
  }, [slug, src, scope, handle, continueRender, cancelRender]);

  const css = [
    `#${scope} svg { width: 100%; height: 100%; }`,
    ...ids.map((id) => `#${scope} #${CSS.escape(id)} { opacity: ${revealProgress(id)}; }`),
    ...[...highlight].map(
      (id) => `#${scope} #${CSS.escape(id)} { filter: drop-shadow(0 0 ${14 * hiP}px ${colors.accent}); }`,
    ),
  ].join("\n");

  return (
    <div id={scope} style={{ position: "absolute", inset: 0, maxHeight: layout.stage.h }}>
      <style>{css}</style>
      {markup ? <div style={{ width: "100%", height: "100%" }} dangerouslySetInnerHTML={{ __html: markup }} /> : null}
    </div>
  );
};
