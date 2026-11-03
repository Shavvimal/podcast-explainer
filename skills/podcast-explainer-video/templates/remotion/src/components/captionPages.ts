// Split each turn's words into caption pages. A page never spans two turns (two speakers).
// karaoke: 3 to 7 words per page; pop: 1 to 3 words per page.
// Readability: a page stays on screen at least max(minPageMs, chars / maxCharsPerSecond).
// A page that speech would flash past faster than that merges with a neighbour in the same turn
// (up to `hardWords` / `hardChars`, two lines for karaoke), because the audio clock cannot slow down.
// Across pages (after the per-turn build):
// - Reading rate: a page faster than TARGET_CPS (19 chars/s) starts early, up to MAX_LEAD_MS, into
//   the silence before its first word (never before the previous page's last word has ended, and
//   never so early that the previous page goes above TARGET_CPS). Words still light on their own
//   start frame; the early part shows the page unspoken (grey).
// - Flicker: a blank of 1 to HOLD_GAP_MS (5 frames) between two pages is closed by holding the
//   earlier page until the next one starts, also across a speaker change.
// - Holds (N05): the early start never reaches back into a pause-and-think hold. A page whose first
//   word comes after a hold starts at the hold's end at the earliest, so the answer to a predict or
//   retrieve prompt never shows (grey or not) while the learner is thinking. Pass manifest.holds.
// scripts/qc.py caption_pages() is a line-for-line Python port: change both together.
import type { CaptionMode, Turn, Word } from "../types";

export type HoldSpan = { startMs: number; endMs: number };

export type CaptionPage = {
  key: string;
  turnId: string;
  speaker: string;
  startMs: number;
  endMs: number;
  words: Word[];
};

const LIMITS = {
  karaoke: { minWords: 3, maxWords: 7, maxChars: 46, hardWords: 14, hardChars: 88 },
  pop: { minWords: 1, maxWords: 3, maxChars: 24, hardWords: 5, hardChars: 32 },
} as const;

const GAP_BREAK_MS = 600;
const HOLD_AFTER_TURN_MS = 300;
export const TARGET_CPS = 19;
export const MAX_LEAD_MS = 500;
export const HOLD_GAP_MS = 167; // 5 frames at 30 fps
const SENTENCE_END = /[.?!;:]["')\]]?$/;
const CLAUSE_END = /[,—-]["')\]]?$/;

const chars = (words: Word[]) => words.map((w) => w.text).join(" ").length;

export const buildCaptionPages = (
  turns: Turn[],
  mode: Exclude<CaptionMode, "off">,
  maxCharsPerSecond: number,
  minPageMs: number,
  holds: HoldSpan[] = [],
): CaptionPage[] => {
  const lim = LIMITS[mode];
  const out: CaptionPage[] = [];
  const need = (g: Word[]) => Math.max(minPageMs, (chars(g) / maxCharsPerSecond) * 1000);

  turns.forEach((turn, ti) => {
    const words = turn.words.filter((w) => w.text.trim().length > 0);
    if (words.length === 0) return;

    // 1. Greedy split on size, punctuation and pauses.
    let groups: Word[][] = [];
    let cur: Word[] = [];
    words.forEach((w, i) => {
      if (cur.length > 0 && chars([...cur, w]) > lim.maxChars) {
        groups.push(cur);
        cur = [];
      }
      cur.push(w);
      const next = words[i + 1];
      const pause = next ? next.startMs - w.endMs > GAP_BREAK_MS : false;
      // Do not strand the end of a sentence on the next page: a sentence that ends within the
      // next two words may run up to two words past maxWords (the character cap still applies).
      const endsSoon = [1, 2].some((k) => {
        const ahead = words.slice(i + 1, i + 1 + k);
        return ahead.length === k && SENTENCE_END.test(ahead[k - 1].text) && cur.length + k <= lim.maxWords + 2;
      });
      if (
        (cur.length >= lim.maxWords && !(endsSoon && !pause)) ||
        (SENTENCE_END.test(w.text) && cur.length >= lim.minWords) ||
        (CLAUSE_END.test(w.text) && cur.length >= lim.minWords + (mode === "karaoke" ? 1 : 0)) ||
        (pause && cur.length >= lim.minWords)
      ) {
        groups.push(cur);
        cur = [];
      }
    });
    if (cur.length) {
      // A short tail joins the previous page when the result stays on one line.
      const prev = groups[groups.length - 1];
      if (prev && cur.length < lim.minWords && prev.length + cur.length <= lim.maxWords + 1 && chars([...prev, ...cur]) <= lim.maxChars + 8) {
        prev.push(...cur);
      } else {
        groups.push(cur);
      }
    }

    // 2. Merge pages that speech would flash past too fast to read.
    const nextTurnStart = turns[ti + 1]?.startMs ?? Number.POSITIVE_INFINITY;
    const turnEnd = Math.min(turn.endMs + HOLD_AFTER_TURN_MS, nextTurnStart);
    const shown = (gs: Word[][], gi: number) =>
      (gi + 1 < gs.length ? gs[gi + 1][0].startMs : Math.max(turnEnd, Math.min(gs[gi][0].startMs + need(gs[gi]), nextTurnStart))) -
      gs[gi][0].startMs;
    const deficit = (gs: Word[][], gi: number) => need(gs[gi]) - shown(gs, gi);
    const fits = (g: Word[]) => g.length <= lim.hardWords && chars(g) <= lim.hardChars;

    const stuck = new Set<Word>();
    for (let guard = 0; guard < 500; guard++) {
      const gi = groups.findIndex((g, i) => !stuck.has(g[0]) && deficit(groups, i) > 0);
      if (gi < 0) break;
      const options: { at: number; merged: Word[] }[] = [];
      if (gi + 1 < groups.length) options.push({ at: gi, merged: [...groups[gi], ...groups[gi + 1]] });
      if (gi > 0) options.push({ at: gi - 1, merged: [...groups[gi - 1], ...groups[gi]] });
      let best: { at: number; merged: Word[]; d: number } | null = null;
      for (const o of options) {
        if (!fits(o.merged)) continue;
        const trial = [...groups.slice(0, o.at), o.merged, ...groups.slice(o.at + 2)];
        const d = deficit(trial, o.at);
        if (!best || d < best.d) best = { ...o, d };
      }
      if (!best) {
        stuck.add(groups[gi][0]);
        continue;
      }
      groups.splice(best.at, 2, best.merged);
    }

    // 2b. Reading rate: a page above TARGET_CPS moves its boundary with a neighbour in the same
    // turn by up to 4 words when that lowers the faster page of the pair (each side keeps 2 words).
    const cps = (gs: Word[][], gi: number) => (chars(gs[gi]) / Math.max(1, shown(gs, gi))) * 1000;
    for (let pass = 0; pass < 3; pass++) {
      let changed = false;
      for (let gi = 0; gi < groups.length; gi++) {
        if (cps(groups, gi) <= TARGET_CPS) continue;
        let best: { score: number; gs: Word[][] | null } = { score: cps(groups, gi), gs: null };
        for (const at of [gi - 1, gi]) {
          if (at < 0 || at + 1 >= groups.length) continue;
          const both = [...groups[at], ...groups[at + 1]];
          for (let cut = 2; cut <= both.length - 2; cut++) {
            if (cut === groups[at].length || Math.abs(cut - groups[at].length) > 4) continue;
            const a = both.slice(0, cut);
            const b = both.slice(cut);
            if (!fits(a) || !fits(b)) continue;
            const trial = [...groups.slice(0, at), a, b, ...groups.slice(at + 2)];
            const score = Math.max(cps(trial, at), cps(trial, at + 1));
            if (score < best.score - 0.05) best = { score, gs: trial };
          }
        }
        if (best.gs) {
          groups = best.gs;
          changed = true;
        }
      }
      if (!changed) break;
    }

    groups.forEach((g, gi) => {
      const startMs = g[0].startMs;
      const endMs = startMs + shown(groups, gi);
      out.push({ key: `${turn.id}-${gi}`, turnId: turn.id, speaker: turn.speaker, startMs, endMs, words: g });
    });
  });

  // 3. Reading rate: start a fast page early, into silence only.
  for (let i = 0; i < out.length; i++) {
    const p = out[i];
    const c = chars(p.words);
    const want = (c / TARGET_CPS) * 1000;
    const shownMs = p.endMs - p.startMs;
    if (shownMs >= want) continue;
    const prev = out[i - 1];
    let earliest = Math.max(0, p.startMs - MAX_LEAD_MS);
    if (prev) {
      const prevSpeechEnd = prev.words[prev.words.length - 1].endMs;
      const prevKeep = prev.startMs + (chars(prev.words) / TARGET_CPS) * 1000;
      earliest = Math.max(earliest, prevSpeechEnd, Math.min(prevKeep, prev.endMs));
    }
    // N05: never into a hold that ends before this page's first word.
    for (const h of holds) {
      if (h.endMs > h.startMs && h.startMs < p.startMs && h.endMs > earliest) earliest = Math.max(earliest, Math.min(h.endMs, p.startMs));
    }
    const start = Math.max(earliest, p.endMs - want);
    if (start < p.startMs) {
      p.startMs = Math.round(start);
      if (prev && prev.endMs > p.startMs) prev.endMs = p.startMs;
    }
  }

  // 4. Flicker: hold a page through a blank shorter than HOLD_GAP_MS.
  for (let i = 0; i + 1 < out.length; i++) {
    const gap = out[i + 1].startMs - out[i].endMs;
    if (gap > 0 && gap < HOLD_GAP_MS) out[i].endMs = out[i + 1].startMs;
  }

  return out;
};
