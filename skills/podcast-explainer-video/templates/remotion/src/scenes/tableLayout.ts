// Layout of a compare table panel (pure: no React, no theme), so qc.py and build_manifest.py can
// port it line for line. W11b (R01, R03): the layout picks the band count that gives the largest
// text, sizes text to the cell AND to the longest string it must hold, and reports whether the text
// reaches MIN_TEXT_PX (28 px at 1080p). A table that cannot reach it does not render: CompareScene
// throws tableProblems() with the numbers, and build_manifest.py runs the same check first.
// Every row must have exactly one cell per column (no padding), so the drawn cells are exactly
// bands.flat() of each row, and visibleText.ts enumerates the same indexes.
import { MIN_TEXT_PX } from "../motionConstants";

export const GRID_TEXT_PX = 36; // theme.ts type.grid: the preferred cell, header and row-label text at 1080p
export const TABLE_LABEL_W = 180; // smallest row-label column (8 characters of bold text at 36 px fit)
// W13b (codex round 4, stumble 5): the row-label column grows to hold the longest row label at the
// table's text size, up to TABLE_LABEL_MAX; beyond that the label text shrinks, and a label that
// would draw under MIN_TEXT_PX is refused with the numbers (tableProblems). "Before change" (13
// characters) needs 291 px at 36 px.
export const TABLE_LABEL_MAX = 320;
export const TABLE_CELL_GAP = 6; // right margin of each cell
export const TABLE_ROW_PAD = 12; // row height = cell + pad
export const TABLE_BAND_GAP = 16; // vertical space between bands
export const TABLE_PAD_X = 24; // panel inset left and right
export const TABLE_PAD_TOP = 8;
export const TABLE_MAX_CELL = 110;
export const CHAR_W = 0.62; // advance width of a bold mono or sans character, in font sizes
export const CELL_TEXT_PAD = 8; // horizontal room a cell keeps around its text

// Compare scene geometry inside the 1728 x 712 stage, shared with CompareScene.tsx.
export const COMPARE_GAP = 40;
export const COMPARE_HEADER_H = 64;
export const COMPARE_STAT_H = 84; // stat pill (52 px) plus 16 px clear of the panel's bottom border
export const COMPARE_VERDICT_H = 72;
export const COMPARE_TITLE_H = 80;

// Size of a panel's body (the box a table, ring or text lines draw in), px at 1080p.
export const compareBodySize = (hasTitle: boolean) => {
  const panelW = (1728 - COMPARE_GAP) / 2;
  const panelH = 712 - (hasTitle ? COMPARE_TITLE_H : 0) - COMPARE_VERDICT_H - 16;
  return { w: panelW - 12, h: panelH - COMPARE_HEADER_H - COMPARE_STAT_H - 12, panelW, panelH };
};

export type TableLayout = {
  bands: number[][]; // column indices per band
  perBand: number; // most cells per row in one band
  cell: number; // cell height (and the square side for short text), px at 1080p
  cellW: number; // W16: cell width; wider than `cell` when the longest text needs it (up to the column room)
  rowH: number;
  font: number; // cell and header text size, px at 1080p
  labelW: number; // row-label column width, px
  labelFont: number; // row-label text size, px (at most font)
  labelChars: number; // longest row label, characters
  bandGap: number;
  header: boolean;
  fits: boolean; // font >= MIN_TEXT_PX and labelFont >= MIN_TEXT_PX
};

// Width a row label of `chars` characters needs at `font` px (the renderer's CHAR_W estimate).
export const labelWidth = (chars: number, font: number) => Math.ceil(chars * CHAR_W * font);

// Row-label column: wide enough for the longest label at GRID_TEXT_PX, between TABLE_LABEL_W and
// TABLE_LABEL_MAX.
export const tableLabelW = (labelChars: number) => Math.min(TABLE_LABEL_MAX, Math.max(TABLE_LABEL_W, labelWidth(labelChars, GRID_TEXT_PX)));

const layoutFor = (n: number, nb: number, nRows: number, w: number, h: number, header: boolean, chars: number, labelChars: number): TableLayout => {
  const per = Math.ceil(n / nb);
  const bandsN = Math.ceil(n / per);
  const bands: number[][] = [];
  for (let b = 0; b < bandsN; b++) {
    const band: number[] = [];
    for (let c = b * per; c < Math.min(n, (b + 1) * per); c++) band.push(c);
    bands.push(band);
  }
  const rowsPerBand = Math.max(1, nRows) + (header ? 1 : 0);
  const labelW = tableLabelW(labelChars);
  const roomW = Math.floor((w - 2 * TABLE_PAD_X - labelW) / per) - TABLE_CELL_GAP;
  const cellH = Math.floor((h - TABLE_PAD_TOP - (bandsN - 1) * TABLE_BAND_GAP) / (bandsN * rowsPerBand)) - TABLE_ROW_PAD;
  const cell = Math.max(1, Math.min(TABLE_MAX_CELL, roomW, cellH));
  // W16 (W14b D08): a cell widens past the square side to hold text up to 12 characters at the grid
  // size, within the column room; short text keeps square cells (cellW === cell).
  const need = Math.ceil(CHAR_W * GRID_TEXT_PX * Math.max(1, chars)) + CELL_TEXT_PAD;
  const cellW = Math.max(cell, Math.min(roomW, need));
  const font = Math.max(0, Math.min(GRID_TEXT_PX, Math.floor(cell * 0.8), Math.floor((cellW - CELL_TEXT_PAD) / (CHAR_W * Math.max(1, chars)))));
  const labelFont = labelChars === 0 ? font : Math.max(0, Math.min(font, Math.floor(labelW / (CHAR_W * labelChars))));
  return { bands, perBand: per, cell, cellW, rowH: cell + TABLE_ROW_PAD, font, labelW, labelFont, labelChars, bandGap: TABLE_BAND_GAP, header, fits: font >= MIN_TEXT_PX && labelFont >= MIN_TEXT_PX };
};

// nCols: column count; nRows: table rows (hidden rows keep their space); w, h: panel body size;
// chars: the longest cell or header text; labelChars: the longest row label. Tries every band count
// and keeps the largest text, then the larger cell, then fewer bands.
export const tableLayout = (nCols: number, nRows: number, w: number, h: number, header: boolean, chars = 1, labelChars = 0): TableLayout => {
  const n = Math.max(1, nCols);
  let best: TableLayout | null = null;
  for (let nb = 1; nb <= n; nb++) {
    if (nb > 1 && Math.ceil(n / Math.ceil(n / nb)) !== nb) continue; // same split as a smaller count
    const L = layoutFor(n, nb, nRows, w, h, header, chars, labelChars);
    if (!best || L.font > best.font || (L.font === best.font && L.cell > best.cell)) best = L;
  }
  return best!;
};

type TablePanelLike = { title?: string; columns?: string[]; rows?: { id: string; label?: string; cells: string[] }[] };

export const tableLabelChars = (panel: TablePanelLike) => Math.max(0, ...(panel.rows ?? []).map((r) => (r.label ?? "").length));

export const tableChars = (panel: TablePanelLike) =>
  Math.max(1, ...(panel.columns ?? []).map((c) => c.length), ...(panel.rows ?? []).flatMap((r) => r.cells.map((c) => c.length)));

export const tableColumns = (panel: TablePanelLike) =>
  Math.max(1, (panel.columns ?? []).length || Math.max(0, ...(panel.rows ?? []).map((r) => r.cells.length)));

// The layout a table panel draws with (CompareScene and visibleText both call this).
export const panelTableLayout = (panel: TablePanelLike, hasTitle: boolean): TableLayout => {
  const { w, h } = compareBodySize(hasTitle);
  return tableLayout(tableColumns(panel), (panel.rows ?? []).length, w, h, (panel.columns ?? []).length > 0, tableChars(panel), tableLabelChars(panel));
};

// R01 and R03 as messages (empty when the table is drawable): a row whose cell count differs from
// the column count (or, without columns, from the first row), and geometry that cannot keep text
// at MIN_TEXT_PX. The message carries the numbers and the largest column count that would fit.
export const tableProblems = (panel: TablePanelLike, hasTitle: boolean): string[] => {
  const out: string[] = [];
  const rows = panel.rows ?? [];
  const n = (panel.columns ?? []).length || (rows[0]?.cells.length ?? 0);
  const what = (panel.columns ?? []).length ? `${n} columns` : `${n} cells in the first row`;
  for (const r of rows) {
    if (r.cells.length !== n) out.push(`row ${r.id} has ${r.cells.length} cells for ${what}; give every row exactly one cell per column`);
  }
  const L = panelTableLayout(panel, hasTitle);
  if (L.labelFont < MIN_TEXT_PX && L.labelChars > 0) {
    const longest = (panel.rows ?? []).reduce((a, r) => ((r.label ?? "").length > a.length ? (r.label ?? "") : a), "");
    const maxChars = Math.floor(TABLE_LABEL_MAX / (CHAR_W * MIN_TEXT_PX));
    out.push(
      `row label "${longest}" (${L.labelChars} characters) needs ${labelWidth(L.labelChars, MIN_TEXT_PX)} px at ${MIN_TEXT_PX} px text, ` +
        `but the row-label column is at most ${TABLE_LABEL_MAX} px, so it would draw at ${L.labelFont} px; ` +
        `shorten it to ${maxChars} characters or fewer`,
    );
  }
  if (L.font < MIN_TEXT_PX) {
    const { w, h } = compareBodySize(hasTitle);
    const chars = tableChars(panel);
    let fitCols = 0;
    for (let k = 1; k <= 40; k++) {
      if (tableLayout(k, rows.length, w, h, (panel.columns ?? []).length > 0, chars, L.labelChars).font >= MIN_TEXT_PX) fitCols = k;
    }
    out.push(
      `${tableColumns(panel)} columns x ${rows.length} rows (longest text ${chars} characters, row-label column ${L.labelW} px) in a ${w} x ${h} px panel body ` +
        `gives ${L.cell} px cells and ${L.font} px text (${L.bands.length} band(s) of ${L.perBand}); text must be at least ${MIN_TEXT_PX} px. ` +
        (fitCols > 0 ? `At most ${fitCols} columns fit with these rows; ` : `No column count fits ${rows.length} rows; `) +
        `cut columns or rows, shorten cell text${hasTitle ? ", or drop the scene title" : ""}.`,
    );
  }
  return out;
};
