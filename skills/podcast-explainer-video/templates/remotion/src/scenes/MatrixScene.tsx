import { useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts } from "../theme";
import type { SceneProps } from "../types";
import { Stage } from "./common";
import {
  MATRIX_AXIS_H,
  MATRIX_AXIS_W,
  MATRIX_GAP,
  MATRIX_NOTE_H,
  type MatrixProps,
  matrixLayout,
  matrixProblems,
  matrixStateAt,
} from "./matrixLayout";

// Heatmap: a cell's background mixes surfaceRaised toward HEAT by its intensity (0..1). White text
// on HEAT is 5.6:1, so every intensity keeps cell text at 4.5:1 or more.
export const MATRIX_HEAT = "#245C9E";
const HIGHLIGHT = colors.warn;

const hex = (c: string) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const mix = (a: string, b: string, t: number) => {
  const [x, y] = [hex(a), hex(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`;
};

// A score or weight matrix between two sets of words (W16, W14b D08): row and column headers as
// words, optional cell values and heat, and highlight steps on word cues. A highlight shows from its
// step until the next step (persist: to the scene end); the step's note shows under the grid.
export const MatrixScene: React.FC<SceneProps<MatrixProps>> = (props) => {
  const { title, rows, columns, cells, heat, rowAxis, colAxis, fromFrame, enter } = props;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const problems = matrixProblems(props);
  if (problems.length) throw new Error(`Matrix "${title ?? props.sceneId}": ${problems.join("; ")}`);
  const L = matrixLayout(props);
  const st = matrixStateAt(props, fromFrame, fps, frame);
  const anyMark = st.cells.size + st.rows.size + st.cols.size > 0;
  const headerStyle = (on: boolean): React.CSSProperties => ({
    fontFamily: fonts.mono,
    fontSize: L.font,
    fontWeight: 700,
    color: on ? HIGHLIGHT : colors.muted,
    whiteSpace: "nowrap",
  });
  return (
    <Stage enter={enter} heading={title}>
      {colAxis ? (
        <div style={{ position: "absolute", left: (rowAxis ? MATRIX_AXIS_W : 0) + L.left + L.headerW, top: 0, height: MATRIX_AXIS_H, fontFamily: fonts.sans, fontSize: 30, fontWeight: 700, color: colors.muted }}>
          {colAxis} →
        </div>
      ) : null}
      {rowAxis ? (
        <div style={{ position: "absolute", left: 0, top: (colAxis ? MATRIX_AXIS_H : 0) + L.top + L.cellH, width: MATRIX_AXIS_W, height: L.gridH - L.cellH, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ transform: "rotate(-90deg)", whiteSpace: "nowrap", fontFamily: fonts.sans, fontSize: 30, fontWeight: 700, color: colors.muted }}>← {rowAxis}</div>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: (rowAxis ? MATRIX_AXIS_W : 0) + L.left, top: (colAxis ? MATRIX_AXIS_H : 0) + L.top, width: L.gridW }}>
        <div style={{ display: "flex", height: L.cellH, marginBottom: MATRIX_GAP, alignItems: "center" }}>
          <div style={{ width: L.headerW, flexShrink: 0 }} />
          {columns.map((c, j) => (
            <div key={j} style={{ width: L.cellW, marginRight: MATRIX_GAP, flexShrink: 0, textAlign: "center", ...headerStyle(st.cols.has(j) || [...st.cells].some((k) => k.endsWith(`,${j}`))) }}>
              {c}
            </div>
          ))}
        </div>
        {rows.map((r, i) => (
          <div key={i} style={{ display: "flex", height: L.cellH, marginBottom: MATRIX_GAP, alignItems: "center" }}>
            <div style={{ width: L.headerW, flexShrink: 0, textAlign: "right", paddingRight: 16, boxSizing: "border-box", ...headerStyle(st.rows.has(i) || [...st.cells].some((k) => k.startsWith(`${i},`))) }}>{r}</div>
            {columns.map((_, j) => {
              const on = st.cells.has(`${i},${j}`) || st.rows.has(i) || st.cols.has(j);
              const h = heat?.[i]?.[j];
              return (
                <div
                  key={j}
                  style={{
                    width: L.cellW,
                    height: L.cellH,
                    marginRight: MATRIX_GAP,
                    flexShrink: 0,
                    borderRadius: 10,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: h === undefined ? colors.surfaceRaised : mix(colors.surfaceRaised, MATRIX_HEAT, h),
                    color: colors.text,
                    opacity: anyMark && !on ? 0.65 : 1,
                    fontFamily: fonts.mono,
                    fontSize: L.font,
                    fontWeight: 800,
                    outline: on ? `5px solid ${HIGHLIGHT}` : "none",
                    outlineOffset: -5,
                    whiteSpace: "nowrap",
                  }}
                >
                  {cells?.[i]?.[j] ?? ""}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      {st.note ? (
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: MATRIX_NOTE_H, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: fonts.sans, fontSize: 36, fontWeight: 700, color: colors.text }}>
          <span style={{ borderLeft: `6px solid ${HIGHLIGHT}`, paddingLeft: 18 }}>{st.note}</span>
        </div>
      ) : null}
    </Stage>
  );
};
