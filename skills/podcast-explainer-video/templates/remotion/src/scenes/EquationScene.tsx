import katex from "katex";
import "katex/dist/katex.min.css";
import { useEffect, useMemo, useState } from "react";
import { interpolate, useCurrentFrame, useDelayRender, useVideoConfig } from "remotion";
import { colors, fonts, type } from "../theme";
import { clamp, cueFrame, easeOut } from "../time";
import type { SceneProps } from "../types";
import { Stage } from "./common";

export type EquationLine = {
  tex?: string; // KaTeX source, rendered in display mode
  text?: string; // plain-text fallback, shown in the mono font
  note?: string; // short gloss to the right, e.g. "divide by the total"
  atMs?: number;
};

export type EquationProps = { title?: string; lines: EquationLine[] };

const STEP_FALLBACK_FRAMES = 45;
const KATEX_FONTS = ["KaTeX_Main", "KaTeX_Math", "KaTeX_Size1", "KaTeX_Size2"];

// Equation lines (a derivation or a definition) that appear one by one on their cues. The newest
// line is bright; earlier lines stay at 60 % so the eye lands on the new one.
export const EquationScene: React.FC<SceneProps<EquationProps>> = ({ title, lines, fromFrame, enter }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  useKatexFonts();

  const html = useMemo(
    () =>
      lines.map((l) =>
        l.tex ? katex.renderToString(l.tex, { displayMode: true, throwOnError: true, output: "html" }) : null,
      ),
    [lines],
  );
  const cues = lines.map((l, i) => cueFrame(l.atMs, 15 + i * STEP_FALLBACK_FRAMES, fromFrame, fps));
  let newest = -1;
  cues.forEach((c, i) => {
    if (frame >= c) newest = i;
  });

  return (
    <Stage enter={enter} heading={title}>
      {/* KaTeX display mode adds a 1em top and bottom margin per line; with 5 lines at 60 px that
          pushed the first and last lines out of the stage (v6 run, 3 Nov 2026). The scene's gap
          spaces the lines instead. */}
      <style>{`.pe-eq .katex-display { margin: 0; }`}</style>
      <div className="pe-eq" style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 28 }}>
        {lines.map((l, i) => {
          const p = interpolate(frame, [cues[i], cues[i] + 12], [0, 1], { ...clamp, easing: easeOut });
          if (p <= 0) return <div key={i} style={{ height: 0 }} />;
          const old = i < newest ? 0.6 : 1;
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 48,
                opacity: p * old,
                translate: `0px ${(1 - p) * 20}px`,
              }}
            >
              <div style={{ flex: "0 1 auto", fontSize: type.equation, color: colors.text }}>
                {html[i] ? (
                  <div dangerouslySetInnerHTML={{ __html: html[i]! }} />
                ) : (
                  <div style={{ fontFamily: fonts.mono, fontWeight: 700 }}>{l.text}</div>
                )}
              </div>
              {l.note ? (
                <div
                  style={{
                    fontFamily: fonts.sans,
                    fontSize: type.body - 4,
                    fontWeight: 600,
                    color: colors.muted,
                    borderLeft: `4px solid ${colors.accent}`,
                    paddingLeft: 20,
                    maxWidth: 620,
                  }}
                >
                  {l.note}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </Stage>
  );
};

// KaTeX fonts come from its CSS; hold the frame until they are loaded so no frame renders
// in a fallback font.
const useKatexFonts = () => {
  const { delayRender, continueRender, cancelRender } = useDelayRender();
  const [handle] = useState(() => delayRender("Loading KaTeX fonts"));
  useEffect(() => {
    Promise.all(KATEX_FONTS.map((f) => document.fonts.load(`40px ${f}`)))
      .then(() => continueRender(handle))
      .catch((e) => cancelRender(e));
  }, [handle, continueRender, cancelRender]);
};
