// Pure state of a compare scene at a local frame: banner, panel titles and tags, table rows and
// cells, stat line. CompareScene draws it; visibleText.ts reads it, so QC and the renderer agree.
// No React, no theme: safe to import from node tests (bundled with esbuild).
import { answerFrame, cueFrame } from "../frames";
import { STEP_FALLBACK_FRAMES, STEP_FALLBACK_START } from "../motionConstants";
import type { Camera, CountClaim, World, WorldStep } from "../types";

export type TableRow = { id: string; label: string; cells: string[]; atMs?: number };

// A stat pill. A string is shorthand for {text}. W11b: it shows from its word until the panel's next
// step (stale-label rule) unless persist is true; claim states its count for qc.py labels.counts.
export type Stat = string | { text: string; persist?: boolean; claim?: CountClaim };

export type PanelStep = WorldStep & {
  atMs?: number;
  stat?: Stat; // result line under the panel, zero lead; until the panel's next step unless persist ("" clears)
  title?: string; // replaces the panel title from this cue on (zero lead); inherited
  tag?: string; // replaces the tag pill from this cue on (zero lead); inherited ("" hides it)
  marks?: Record<string, number[]>; // table: row id -> 0-based columns outlined; inherited, {} clears
  // table: colour class (theme name or #hex) -> row id -> columns: a solid outline in that colour that
  // replaces the dashed mark; splits cells by what happened to them (W9). Inherited, {} clears.
  cellTint?: Record<string, Record<string, number[]>>;
  fill?: Record<string, number[] | "all">; // table: cells shown on this cue (zero lead); cumulative.
  // A row named in any step's fill shows "?" in each cell until that cell is filled.
};

export type ComparePanel = {
  title: string;
  tag?: string; // short pill beside the title, e.g. "before", "naive"
  kind: "world" | "table" | "text";
  world?: World | "shared"; // kind world: a local world, or "shared" to continue the episode world
  camera?: Partial<Camera>; // kind world: fixed view; default fits the ring (or all nodes) to the panel
  columns?: string[]; // kind table: column headers
  rows?: TableRow[]; // kind table: a row with `at` appears on its cue (zero lead); without it, from the start
  valueColors?: Record<string, string>; // kind table: cell text -> fill colour (e.g. owner colours)
  lines?: { text: string; atMs?: number }[]; // kind text
  steps?: PanelStep[];
};

export type Winner = "left" | "right" | "none";

// One banner under the panels. Each banner replaces the one before it on its word (zero lead).
// text "" hides the badge. `winner` colours the panels (right green, wrong red); "none" keeps them
// neutral. `labels` replaces the RIGHT / WRONG pill text per side (for example move counts).
// W11b: a banner shows until the next step of either panel after its word, unless persist is true.
export type Banner = { text: string; winner?: Winner; labels?: { left?: string; right?: string }; atMs?: number; persist?: boolean; claim?: CountClaim };

export type CompareProps = {
  title?: string;
  left: ComparePanel;
  right: ComparePanel;
  verdict?: Banner; // the first banner (kept for older scenes.json files)
  banners?: Banner[]; // later banners: change or hide the verdict when it stops being true
};

export type BannerState = { text: string; winner: Winner; labels: { left?: string; right?: string }; at: number; until: number; claim?: CountClaim };

const fallback = (i: number) => STEP_FALLBACK_START + i * STEP_FALLBACK_FRAMES;

// W13b (codex round 4, Q05): a label with a count claim may write its numbers as placeholders,
// {value}, {of} and {to}, which the renderer fills from the claim, so the displayed text cannot
// disagree with the claim. claimTextProblems() checks the displayed text against the claim with the
// rules of pe_common.claim_text_problem (W13a): "X of Y" must be value of of; else a bare number
// must be the value; "none", "no", "zero", "nothing" mean 0; "all", "every", "each" mean of. A
// placeholder without a claim is also a problem. The renderer throws on any problem.
export const claimText = (text: string, claim?: CountClaim): string =>
  claim ? text.replace(/\{value\}/g, String(claim.value)).replace(/\{of\}/g, String(claim.of)).replace(/\{to\}/g, claim.to ?? "") : text;

const X_OF_Y = /(?<![\d.])(\d+)\s+of\s+(\d+)(?![\d.])/;
const NUM = /(?<![\w.])\d+(?:[.,]\d+)*(?!\w)/g;
const NONE = /\b(none|no|zero|nothing)\b/i;
const ALL = /\b(all|every|each)\b/i;

export const claimTextProblems = (text: string, claim?: CountClaim): string[] => {
  if (!claim) return /\{(value|of|to)\}/.test(text) ? [`label "${text}" uses a {value}, {of} or {to} placeholder but has no claim`] : [];
  const shown = claimText(text, claim);
  const { value, of } = claim;
  const m = X_OF_Y.exec(shown);
  if (m) {
    const [x, y] = [Number(m[1]), Number(m[2])];
    return x !== value || y !== of ? [`label "${shown}" says '${m[0]}' but its claim says ${value} of ${of}; write "{value} of {of}" or fix the claim`] : [];
  }
  const nums = (shown.match(NUM) ?? []).map((n) => Math.trunc(Number(n.replace(/,/g, ""))));
  if (nums.length) return nums.includes(value) ? [] : [`label "${shown}" shows ${nums.join(", ")} but its claim value is ${value}`];
  if (NONE.test(shown) && value !== 0) return [`label "${shown}" says none but its claim value is ${value}`];
  if (ALL.test(shown) && value !== of) return [`label "${shown}" says all but its claim says ${value} of ${of}`];
  return [];
};

// Cue frames (state changes, LEAD_FRAMES early) and result frames (zero lead) of a panel's steps.
export const stepFrames = (panel: ComparePanel | undefined, fromFrame: number, fps: number) =>
  (panel?.steps ?? []).map((s, i) => ({
    cue: cueFrame(s.atMs, fallback(i), fromFrame, fps),
    result: answerFrame(s.atMs, fromFrame, fps) ?? fallback(i),
  }));

// W11b, stale labels: the frame at which a label shown from result frame `at` expires: the cue
// frame of the first step (in `frames`) whose word comes after `at`, never before at + 1.
// Infinity when no step follows.
export const expiryFrame = (at: number, frames: { cue: number; result: number }[]): number => {
  let e = Infinity;
  for (const f of frames) if (f.result > at) e = Math.min(e, Math.max(at + 1, f.cue));
  return e;
};

// The banner shown at local `frame`: the latest verdict or banner whose cue has passed, until the
// next step of either panel after its word (unless persist). A banner without a cue never shows
// (no time-based default), like every answer. An expired banner shows nothing: neutral panels.
export const bannerAt = (props: Pick<CompareProps, "verdict" | "banners"> & Partial<Pick<CompareProps, "left" | "right">>, fromFrame: number, fps: number, frame: number): BannerState | null => {
  const list = [...(props.verdict ? [props.verdict] : []), ...(props.banners ?? [])];
  let best: { b: Banner; at: number } | null = null;
  for (const b of list) {
    const at = answerFrame(b.atMs, fromFrame, fps);
    if (at === null || at > frame) continue;
    if (best === null || at >= best.at) best = { b, at };
  }
  if (!best) return null;
  const frames = [...stepFrames(props.left, fromFrame, fps), ...stepFrames(props.right, fromFrame, fps)];
  const until = best.b.persist ? Infinity : expiryFrame(best.at, frames);
  if (frame >= until) return null;
  return { text: claimText(best.b.text, best.b.claim), winner: best.b.winner ?? "none", labels: best.b.labels ?? {}, at: best.at, until, ...(best.b.claim ? { claim: best.b.claim } : {}) };
};

export type CellState = { text: string; filled: boolean; at: number | null }; // at: frame the value appeared (null: from the start)
export type RowState = { id: string; label: string; at: number | null; visible: boolean; cells: CellState[]; marked: Set<number>; tinted: Map<number, string> };

export type PanelState = {
  title: string;
  titleAt: number | null; // frame of the last title change (null: the original)
  tag: string | undefined;
  stat: { text: string; at: number; until: number; claim?: CountClaim } | null;
  rows: RowState[]; // kind table
  lines: { text: string; at: number | null; visible: boolean }[]; // kind text
};

// N02: every time below is a finite frame or null. A row or cell that is visible from the start
// has at = null and opacity 1; the renderer never interpolates over a non-finite range.
export const panelStateAt = (panel: ComparePanel, fromFrame: number, fps: number, frame: number): PanelState => {
  const steps = panel.steps ?? [];
  const frames = stepFrames(panel, fromFrame, fps);
  const cues = frames.map((f) => f.cue);
  const results = frames.map((f) => f.result);
  let stat: PanelState["stat"] = null;
  let statLatest = -Infinity; // steps may be listed out of time order: the latest word wins
  let title = panel.title;
  let titleAt: number | null = null;
  let tag = panel.tag;
  let marks: Record<string, number[]> = {};
  let cellTint: Record<string, Record<string, number[]>> = {};
  const filled: Record<string, Map<number, number>> = {}; // row -> column -> fill frame
  const fillRows = new Set<string>();
  const rows = panel.rows ?? [];
  steps.forEach((s, i) => {
    if (s.stat !== undefined && frame >= results[i] && results[i] >= statLatest) {
      statLatest = results[i];
      const st = typeof s.stat === "string" ? { text: s.stat } : s.stat;
      const until = st.persist ? Infinity : expiryFrame(results[i], frames);
      stat = st.text === "" ? null : { text: claimText(st.text, st.claim), at: results[i], until, ...(st.claim ? { claim: st.claim } : {}) };
    }
    if (s.title !== undefined && frame >= results[i]) {
      title = s.title;
      titleAt = results[i];
    }
    if (s.tag !== undefined && frame >= results[i]) tag = s.tag === "" ? undefined : s.tag;
    if (s.marks !== undefined && frame >= cues[i]) marks = s.marks;
    if (s.cellTint !== undefined && frame >= cues[i]) cellTint = s.cellTint;
    for (const [rid, cs] of Object.entries(s.fill ?? {})) {
      fillRows.add(rid);
      if (frame < results[i]) continue;
      const row = rows.find((r) => r.id === rid);
      const list = cs === "all" ? (row?.cells ?? []).map((_, k) => k) : cs;
      filled[rid] ??= new Map();
      for (const c of list) if (!filled[rid].has(c)) filled[rid].set(c, results[i]);
    }
  });
  const rowStates: RowState[] = rows.map((r) => {
    const at = answerFrame(r.atMs, fromFrame, fps);
    const cells: CellState[] = r.cells.map((text, c) => {
      if (!fillRows.has(r.id)) return { text, filled: true, at: null };
      const f = filled[r.id]?.get(c);
      return f === undefined ? { text: "?", filled: false, at: null } : { text, filled: true, at: f };
    });
    const tinted = new Map<number, string>();
    for (const [cls, byRow] of Object.entries(cellTint)) for (const c of byRow[r.id] ?? []) tinted.set(c, cls);
    return { id: r.id, label: r.label, at, visible: at === null || frame >= at, cells, marked: new Set(marks[r.id] ?? []), tinted };
  });
  const lines = (panel.lines ?? []).map((l) => {
    const at = answerFrame(l.atMs, fromFrame, fps);
    return { text: l.text, at, visible: at === null || frame >= at };
  });
  if (stat !== null && frame >= (stat as NonNullable<PanelState["stat"]>).until) stat = null;
  return { title, titleAt, tag, stat, rows: rowStates, lines };
};

// W11b, R02: evaluate a count claim against a table panel's state at a frame, over the panel's first
// two rows and the columns filled (not "?") in both. exact is true when both rows are visible and
// every column is filled, so the claim can be checked strictly; ok compares value and of with the
// table. Returns null when the panel is not a table or has fewer than two rows.
export type ClaimResult = { value: number; of: number; counted: number; exact: boolean; ok: boolean };

export const countClaim = (panel: ComparePanel, st: PanelState, claim: CountClaim): ClaimResult | null => {
  if (panel.kind !== "table" || st.rows.length < 2) return null;
  const [a, b] = st.rows;
  const nCols = (panel.columns ?? []).length || a.cells.length;
  const visible = a.visible && b.visible;
  let value = 0;
  let counted = 0;
  for (let c = 0; c < nCols; c++) {
    const x = a.cells[c];
    const y = b.cells[c];
    if (!visible || !x || !y || !x.filled || !y.filled) continue;
    counted++;
    if (x.text !== y.text && (claim.scope === "columns-changed" || y.text === claim.to)) value++;
  }
  return { value, of: nCols, counted, exact: visible && counted === nCols, ok: value === claim.value && claim.of === nCols };
};

// W13b: every banner, verdict and stat text in a compare scene against its claim (messages).
export const compareClaimProblems = (props: Pick<CompareProps, "verdict" | "banners" | "left" | "right">): string[] => {
  const out: string[] = [];
  for (const b of [...(props.verdict ? [props.verdict] : []), ...(props.banners ?? [])]) out.push(...claimTextProblems(b.text, b.claim));
  for (const panel of [props.left, props.right]) {
    for (const st of panel?.steps ?? []) {
      if (st.stat === undefined || typeof st.stat === "string") {
        if (typeof st.stat === "string") out.push(...claimTextProblems(st.stat));
        continue;
      }
      out.push(...claimTextProblems(st.stat.text, st.stat.claim));
    }
  }
  return out;
};
