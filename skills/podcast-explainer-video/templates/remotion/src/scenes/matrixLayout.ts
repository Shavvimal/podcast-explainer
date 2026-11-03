// Layout and state of a `matrix` scene (pure: no React, no theme), so qc.py and build_manifest.py
// port it line for line (pe_common.matrix_layout, matrix_problems, matrix_state_at). W16 (W14b D08):
// a grid of scores between tokens with word headers ("brick", "fell") and decimal or word cells
// ("0.81", "minus inf"), an optional heatmap intensity per cell, and highlight steps bound to words.
// Text never draws under MIN_TEXT_PX: a matrix that cannot fit stops the build and the render with
// the numbers and the largest column count that would fit.
import { cueFrame } from "../frames";
import { LEAD_FRAMES, MIN_TEXT_PX, STEP_FALLBACK_FRAMES, STEP_FALLBACK_START } from "../motionConstants";
import { CHAR_W } from "./tableLayout";

export const MATRIX_W = 1728; // the stage
export const MATRIX_H = 712;
export const MATRIX_HEADING_H = 92; // a title takes this much of the stage height (as DiagramScene)
export const MATRIX_NOTE_H = 72; // the step note line under the grid (always reserved)
export const MATRIX_AXIS_H = 44; // the column-axis caption row ("keys"), when colAxis is set
export const MATRIX_AXIS_W = 56; // the row-axis caption column ("queries", turned), when rowAxis is set
export const MATRIX_GAP = 6; // between cells
export const MATRIX_TEXT_PAD = 16; // horizontal room a cell or header keeps around its text
export const MATRIX_TEXT_MAX = 40; // largest cell text, px
export const MATRIX_CELL_MAX_W = 260;
export const MATRIX_CELL_MAX_H = 120;
export const MATRIX_MAX_CHARS = 12; // schema limit for a header or cell

export type MatrixRef = number | string; // a 0-based index or a header text
export type MatrixMark = { row?: MatrixRef; col?: MatrixRef };
export type MatrixStep = { atMs?: number; highlight?: MatrixMark[]; note?: string; persist?: boolean };
export type MatrixProps = {
  title?: string;
  rows: string[];
  columns: string[];
  cells?: string[][];
  heat?: number[][];
  rowAxis?: string;
  colAxis?: string;
  steps?: MatrixStep[];
};

export type MatrixLayout = {
  font: number; // cell and header text, px at 1080p
  headerW: number; // row-header column width
  cellW: number;
  cellH: number;
  gridW: number; // header column plus every cell column
  gridH: number; // header row plus every cell row
  left: number; // grid left edge inside the stage body (centred)
  top: number;
  bodyW: number;
  bodyH: number;
  cellChars: number;
  rowChars: number;
  fits: boolean;
};

const maxLen = (xs: (string | undefined)[]) => Math.max(1, ...xs.map((x) => (x ?? "").length));

export const matrixCellChars = (p: Pick<MatrixProps, "columns" | "cells">) => maxLen([...(p.columns ?? []), ...(p.cells ?? []).flat()]);
export const matrixRowChars = (p: Pick<MatrixProps, "rows">) => maxLen(p.rows ?? []);

// The body the grid draws in: the stage minus the heading, the note line and the axis captions.
export const matrixBody = (hasTitle: boolean, rowAxis: boolean, colAxis: boolean) => ({
  w: MATRIX_W - (rowAxis ? MATRIX_AXIS_W : 0),
  h: MATRIX_H - (hasTitle ? MATRIX_HEADING_H : 0) - MATRIX_NOTE_H - (colAxis ? MATRIX_AXIS_H : 0),
});

// nRows x nCols cells plus one header row and one header column. The font is the largest that lets
// the longest header or cell fit its column width and 60 % of the row height.
export const matrixLayoutFor = (nRows: number, nCols: number, cellChars: number, rowChars: number, hasTitle: boolean, rowAxis = false, colAxis = false): MatrixLayout => {
  const R = Math.max(1, nRows);
  const C = Math.max(1, nCols);
  const { w: bodyW, h: bodyH } = matrixBody(hasTitle, rowAxis, colAxis);
  const fw = (bodyW - MATRIX_TEXT_PAD - C * (MATRIX_TEXT_PAD + MATRIX_GAP)) / (CHAR_W * (rowChars + C * cellChars));
  const rowSlot = Math.floor(bodyH / (R + 1)) - MATRIX_GAP;
  const fh = Math.floor(Math.min(MATRIX_CELL_MAX_H, rowSlot) * 0.6);
  const font = Math.max(0, Math.floor(Math.min(MATRIX_TEXT_MAX, fw, fh)));
  const headerW = Math.ceil(rowChars * CHAR_W * Math.max(font, 1)) + MATRIX_TEXT_PAD;
  const cellW = Math.max(1, Math.min(MATRIX_CELL_MAX_W, Math.floor((bodyW - headerW) / C) - MATRIX_GAP));
  const cellH = Math.max(1, Math.min(MATRIX_CELL_MAX_H, rowSlot));
  const gridW = headerW + C * (cellW + MATRIX_GAP);
  const gridH = (R + 1) * (cellH + MATRIX_GAP);
  return {
    font, headerW, cellW, cellH, gridW, gridH,
    left: Math.max(0, Math.floor((bodyW - gridW) / 2)),
    top: Math.max(0, Math.floor((bodyH - gridH) / 2)),
    bodyW, bodyH, cellChars, rowChars,
    fits: font >= MIN_TEXT_PX && cellW >= Math.ceil(cellChars * CHAR_W * font) + MATRIX_TEXT_PAD / 2,
  };
};

export const matrixLayout = (p: MatrixProps): MatrixLayout =>
  matrixLayoutFor((p.rows ?? []).length, (p.columns ?? []).length, matrixCellChars(p), matrixRowChars(p), !!p.title, !!p.rowAxis, !!p.colAxis);

// A highlight reference as an index, or -1 when it names no header (or names two: ambiguous).
export const matrixIndex = (headers: string[], ref: MatrixRef | undefined): number => {
  if (ref === undefined) return -1;
  if (typeof ref === "number") return Number.isInteger(ref) && ref >= 0 && ref < headers.length ? ref : -1;
  const hits = headers.map((h, i) => (h === ref ? i : -1)).filter((i) => i >= 0);
  return hits.length === 1 ? hits[0] : -1;
};

// Why this matrix cannot be drawn (empty when it can): shapes, references and the 28 px rule.
export const matrixProblems = (p: MatrixProps): string[] => {
  const out: string[] = [];
  const rows = p.rows ?? [];
  const cols = p.columns ?? [];
  if (!rows.length || !cols.length) out.push("a matrix needs at least one row header and one column header");
  for (const [name, grid] of [["cells", p.cells], ["heat", p.heat]] as const) {
    if (!grid) continue;
    if (grid.length !== rows.length) out.push(`${name} has ${grid.length} rows for ${rows.length} row headers; give one row per header`);
    grid.forEach((r, i) => {
      if (r.length !== cols.length) out.push(`${name} row ${i} has ${r.length} entries for ${cols.length} columns; give one per column`);
    });
  }
  (p.heat ?? []).flat().forEach((v) => {
    if (typeof v !== "number" || !(v >= 0 && v <= 1)) out.push(`heat value ${v} is outside 0..1`);
  });
  (p.steps ?? []).forEach((s, i) => {
    (s.highlight ?? []).forEach((m) => {
      if (m.row === undefined && m.col === undefined) out.push(`step ${i} highlight names neither row nor col`);
      if (m.row !== undefined && matrixIndex(rows, m.row) < 0) out.push(`step ${i} highlight row ${JSON.stringify(m.row)} is not one row header (use its index when a header repeats)`);
      if (m.col !== undefined && matrixIndex(cols, m.col) < 0) out.push(`step ${i} highlight col ${JSON.stringify(m.col)} is not one column header (use its index when a header repeats)`);
    });
  });
  if (!rows.length || !cols.length) return out;
  const L = matrixLayout(p);
  if (!L.fits) {
    let fitCols = 0;
    for (let k = 1; k <= 40; k++) {
      if (matrixLayoutFor(rows.length, k, L.cellChars, L.rowChars, !!p.title, !!p.rowAxis, !!p.colAxis).fits) fitCols = k;
    }
    out.push(
      `${cols.length} columns x ${rows.length} rows (longest cell or column header ${L.cellChars} characters, longest row header ${L.rowChars}) ` +
        `in a ${L.bodyW} x ${L.bodyH} px body gives ${L.font} px text; text must be at least ${MIN_TEXT_PX} px. ` +
        (fitCols > 0 ? `At most ${fitCols} columns fit with these rows and texts; ` : `No column count fits ${rows.length} rows; `) +
        `cut rows or columns, shorten headers or cells${p.title ? ", or drop the title" : ""}.`,
    );
  }
  return out;
};

// The step whose highlight and note show at `frame` (local to the scene): the latest step at or
// before it; a highlight expires at the next step unless persist (then it stays to the scene end).
export type MatrixState = { cells: Set<string>; rows: Set<number>; cols: Set<number>; note: string | null };
export const matrixStateAt = (p: MatrixProps, fromFrame: number, fps: number, frame: number): MatrixState => {
  const steps = p.steps ?? [];
  const at = steps.map((s, i) => cueFrame(s.atMs, STEP_FALLBACK_START + i * STEP_FALLBACK_FRAMES, fromFrame, fps, LEAD_FRAMES));
  let cur = -1;
  at.forEach((f, i) => {
    if (frame >= f && (cur < 0 || f >= at[cur])) cur = i;
  });
  const st: MatrixState = { cells: new Set(), rows: new Set(), cols: new Set(), note: null };
  steps.forEach((s, i) => {
    if (frame < at[i] || (i !== cur && !s.persist)) return;
    for (const m of s.highlight ?? []) {
      const r = matrixIndex(p.rows, m.row);
      const c = matrixIndex(p.columns, m.col);
      if (r >= 0 && c >= 0) st.cells.add(`${r},${c}`);
      else if (r >= 0) st.rows.add(r);
      else if (c >= 0) st.cols.add(c);
    }
  });
  if (cur >= 0) st.note = steps[cur].note ?? null;
  return st;
};

// Every text a matrix draws at `frame`: title, axis captions, headers, cells, the current note.
export const matrixTextsAt = (p: MatrixProps, fromFrame: number, fps: number, frame: number): string[] => {
  const out: string[] = [];
  for (const x of [p.title, p.rowAxis, p.colAxis, ...(p.columns ?? []), ...(p.rows ?? []), ...(p.cells ?? []).flat()]) if (x) out.push(x);
  const n = matrixStateAt(p, fromFrame, fps, frame).note;
  if (n) out.push(n);
  return out;
};
