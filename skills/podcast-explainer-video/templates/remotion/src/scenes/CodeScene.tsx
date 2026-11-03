import { Highlight, type PrismTheme } from "prism-react-renderer";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts, layout, radius, type } from "../theme";
import { clamp, cueFrame, easeOut, parseLines } from "../time";
import type { SceneProps } from "../types";
import { Stage } from "./common";

export type CodeStep = {
  atMs?: number;
  lines?: string | number[]; // lines revealed on this step, e.g. "4-6" (cumulative)
  focus?: string | number[]; // lines highlighted from this step on; other lines dim
};

export type CodeProps = {
  code: string;
  language?: string; // prism-react-renderer language id: python, javascript, typescript, tsx, go, rust, sql, bash, json ...
  title?: string;
  filename?: string;
  steps?: CodeStep[];
};

// Colours chosen for at least 4.5:1 contrast on colors.surface (#171C26).
const codeTheme: PrismTheme = {
  plain: { color: colors.text, backgroundColor: colors.surface },
  styles: [
    { types: ["comment", "prolog", "doctype", "cdata"], style: { color: "#9AA3B5", fontStyle: "italic" } },
    { types: ["keyword", "selector", "important", "atrule"], style: { color: "#D2A8FF" } },
    { types: ["string", "char", "attr-value", "regex", "inserted"], style: { color: "#A5E39A" } },
    { types: ["number", "boolean", "constant", "symbol"], style: { color: "#FFB86C" } },
    { types: ["function", "class-name", "maybe-class-name"], style: { color: "#7CC4FF" } },
    { types: ["builtin", "tag", "deleted"], style: { color: "#FF9E9E" } },
    { types: ["operator", "punctuation"], style: { color: "#C3CAD8" } },
    { types: ["property", "attr-name", "variable", "parameter"], style: { color: "#FFD580" } },
  ],
};

const FONT = type.code;
const LINE_H = Math.round(FONT * 1.5);
const STEP_FALLBACK_FRAMES = 45;

// Syntax-highlighted code with line reveals and focus. Lines no step reveals are visible from the
// start. The panel scrolls so the newest revealed or focused line stays in view.
export const CodeScene: React.FC<SceneProps<CodeProps>> = ({
  code,
  language = "python",
  title,
  filename,
  steps = [],
  fromFrame,
  enter,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const lines = code.replace(/\n+$/, "").split("\n");
  const n = lines.length;

  const cues = steps.map((s, i) => cueFrame(s.atMs, 15 + i * STEP_FALLBACK_FRAMES, fromFrame, fps));
  const revealAt: Record<number, number> = {};
  steps.forEach((s, i) => parseLines(s.lines).forEach((ln) => (revealAt[ln] ??= cues[i])));

  let active = -1;
  cues.forEach((c, i) => {
    if (frame >= c) active = i;
  });
  // focus inherits from the last step that set it
  let focus = new Set<number>();
  let focusFrom = 0;
  for (let i = 0; i <= active; i++) {
    if (steps[i].focus !== undefined) {
      focus = parseLines(steps[i].focus);
      focusFrom = cues[i];
    }
  }
  const fP = interpolate(frame, [focusFrom, focusFrom + 9], [0, 1], clamp);

  const headingH = title ? 92 : 0;
  const tabH = filename ? 52 : 0;
  const panelH = layout.stage.h - headingH;
  const visible = Math.max(1, Math.floor((panelH - tabH - 48) / LINE_H));

  // Scroll target per step: keep the latest revealed or focused line on screen.
  const targetTop = (upTo: number) => {
    let want = 0;
    for (let i = 0; i <= upTo; i++) {
      const ids = [...parseLines(steps[i].lines), ...parseLines(steps[i].focus)];
      if (ids.length) want = Math.max(...ids);
    }
    return Math.max(0, Math.min(n - visible, want - visible + 1));
  };
  const prevTop = active > 0 ? targetTop(active - 1) : 0;
  const nextTop = active >= 0 ? targetTop(active) : 0;
  const top =
    active >= 0
      ? interpolate(frame, [cues[active], cues[active] + 12], [prevTop, nextTop], { ...clamp, easing: easeOut })
      : 0;

  return (
    <Stage enter={enter} heading={title}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: colors.surface,
          borderRadius: radius.card,
          border: `2px solid ${colors.line}`,
          overflow: "hidden",
        }}
      >
        {filename ? (
          <div
            style={{
              height: tabH,
              display: "flex",
              alignItems: "center",
              padding: "0 28px",
              borderBottom: `2px solid ${colors.line}`,
              fontFamily: fonts.mono,
              fontSize: type.min,
              color: colors.muted,
            }}
          >
            {filename}
          </div>
        ) : null}
        <div style={{ position: "absolute", top: tabH + 24, left: 0, right: 0, bottom: 24, overflow: "hidden" }}>
          <Highlight theme={codeTheme} code={lines.join("\n")} language={language}>
            {({ tokens, getTokenProps }) => (
              <div style={{ translate: `0px ${-top * LINE_H}px` }}>
                {tokens.map((line, i) => {
                  const ln = i + 1;
                  const at = revealAt[ln];
                  const shown = at === undefined ? 1 : interpolate(frame, [at, at + 8], [0, 1], { ...clamp, easing: easeOut });
                  const isFocus = focus.has(ln);
                  const dim = focus.size > 0 && !isFocus ? 1 - 0.6 * fP : 1;
                  return (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        height: LINE_H,
                        alignItems: "center",
                        fontFamily: fonts.mono,
                        fontSize: FONT,
                        whiteSpace: "pre",
                        opacity: shown * dim,
                        translate: `${(1 - shown) * 24}px 0px`,
                        background: isFocus ? `rgba(124,196,255,${0.14 * fP})` : "transparent",
                        borderLeft: `6px solid ${isFocus ? `rgba(124,196,255,${fP})` : "transparent"}`,
                      }}
                    >
                      <span style={{ width: 70, textAlign: "right", paddingRight: 24, color: colors.dim, flexShrink: 0 }}>{ln}</span>
                      <span>
                        {line.map((token, k) => (
                          <span key={k} {...getTokenProps({ token })} />
                        ))}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </Highlight>
        </div>
      </div>
    </Stage>
  );
};
