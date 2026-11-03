#!/usr/bin/env node
// align.mjs: add word timing to <workspace>/<slug>/timing.json.
//
// Run it from the folder that holds explainers/ (or from explainers/remotion). It loads
// @remotion/install-whisper-cpp from <workspace>/remotion, installed from the template's package.json:
//
//   node <skill>/scripts/align.mjs <slug> [--workspace explainers] [--only t03,t04] [--model small.en]
//                                         [--estimate-only] [--whisper-version 1.5.5] [--cache-dir DIR]
//   node <skill>/scripts/align.mjs <slug> --show-asr t07,t08    print the raw ASR of those turns, change nothing
//   node <skill>/scripts/align.mjs --warm [--model small.en] [--cache-dir DIR]   build whisper.cpp + model now
//   node <skill>/scripts/align.mjs --help
//
// Fidelity: each turn keeps its raw ASR words (turns[].asr, episode ms) and the take it was aligned to
// (alignedAudioSha). After writing timing.json, align.mjs runs scripts/fidelity.py, which compares the
// raw ASR with the script in both directions (insertions, deletions, substitutions, numbers, negations)
// and exits 1 on an unresolved fidelity failure; align.mjs then exits 1 too. --estimate-only is a
// declared draft mode: timing.alignment.draft is true and qc.py blocks delivery.
//
// For each turn clip: resample to 16 kHz mono s16 with ffmpeg, transcribe with whisper.cpp
// (token-level DTW timestamps, split on word), align the ASR words to the script words with an
// edit-distance alignment, keep the script spelling, interpolate unmatched words between their
// matched neighbours, offset by the clip start in episode.wav, and write turns[].words[]
// with source = asr | interpolated | estimated. If whisper.cpp cannot be installed or fails,
// the words are estimated from letter counts (source = estimated) and the run says so loudly.
//
// Chunk mode (several turns share one audio file): the file is transcribed once, aligned against
// the concatenated script of its turns, and each turn's startMs/endMs is set from its words.
// The chunk's start in episode.wav comes from timing.chunks[].startMs when present, else from
// the earliest startMs of its turns.
//
// whisper.cpp and the model download once into the cache dir
// (default ~/.cache/podcast-explainer/whisper.cpp-<version>). whisper.cpp 1.5.5 builds with
// plain `make` (no cmake needed) and supports DTW token timestamps.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const argv = process.argv.slice(2);
const USAGE =
  "usage: node align.mjs <slug> [--workspace explainers] [--only t01,t02] [--model small.en] [--estimate-only] [--whisper-version 1.5.5] [--cache-dir DIR]\n" +
  "       node align.mjs <slug> --show-asr t01,t02   (print raw ASR, change nothing)\n" +
  "       node align.mjs --warm [--model small.en] [--cache-dir DIR]   (build whisper.cpp, download the model, test it; no slug)\n" +
  "Run from the folder that holds explainers/ or from explainers/remotion. Exit 0 ok, 1 error or fidelity failure, 2 usage.";
if (argv.includes("--help") || argv.includes("-h")) {
  console.log(USAGE);
  process.exit(0);
}
const flag = (k) => argv.includes(k);
const opt = (k, d) => {
  const i = argv.indexOf(k);
  return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : d;
};

// --warm: build whisper.cpp and download the model now, then transcribe one second of silence to
// prove the binary runs. No slug, no timing.json, nothing in the workspace changes. Run it before the
// paid TTS step so the first align.mjs run cannot stall on a build after audio money is spent
// (preflight.py --warm-whisper calls this). Exit 0 ready, 1 failed.
if (flag("--warm")) {
  const version = opt("--whisper-version", "1.5.5");
  const model = opt("--model", "small.en");
  const cache = path.resolve(
    opt("--cache-dir", process.env.PODCAST_EXPLAINER_CACHE ?? path.join(os.homedir(), ".cache", "podcast-explainer")),
  );
  const ws = path.resolve(opt("--workspace", fs.existsSync(path.join(process.cwd(), "explainers")) ? "explainers" : ".."));
  let lib = null;
  for (const dir of [path.join(ws, "remotion"), process.cwd()]) {
    try {
      lib = createRequire(path.join(dir, "package.json"))("@remotion/install-whisper-cpp");
      break;
    } catch {
      // try the next place
    }
  }
  if (!lib) {
    console.error(`align.mjs --warm: @remotion/install-whisper-cpp is not installed in ${path.join(ws, "remotion")} or ${process.cwd()}; run npm install in the workspace Remotion project first`);
    process.exit(1);
  }
  const whisperPath = path.join(cache, `whisper.cpp-${version}`);
  try {
    fs.mkdirSync(cache, { recursive: true });
    const exe = lib.getWhisperExecutablePath ? lib.getWhisperExecutablePath(whisperPath, version) : path.join(whisperPath, "main");
    if (!fs.existsSync(exe)) {
      console.log(`installing whisper.cpp ${version} into ${whisperPath} (one time, about 30 s; needs make and a C compiler) ...`);
      if (fs.existsSync(whisperPath)) fs.rmSync(whisperPath, { recursive: true, force: true });
      await lib.installWhisperCpp({ to: whisperPath, version, printOutput: false });
    }
    const modelFile = path.join(whisperPath, `ggml-${model}.bin`);
    if (!fs.existsSync(modelFile)) {
      console.log(`downloading whisper model ${model} into ${whisperPath} (one time, needs network) ...`);
      await lib.downloadWhisperModel({ model, folder: whisperPath, printOutput: false });
    }
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pe-warm-"));
    const wav = path.join(tmp, "silence.wav");
    const r = spawnSync("ffmpeg", ["-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1", "-c:a", "pcm_s16le", wav]);
    if (r.status !== 0) throw new Error(`ffmpeg could not make a test clip: ${r.stderr.toString().trim()}`);
    await lib.transcribe({ inputPath: wav, whisperPath, whisperCppVersion: version, model, tokenLevelTimestamps: true, splitOnWord: true, printOutput: false });
    fs.rmSync(tmp, { recursive: true, force: true });
    console.log(`whisper ready: whisper.cpp ${version}, model ${model}, in ${whisperPath}`);
    process.exit(0);
  } catch (e) {
    console.error(`align.mjs --warm: whisper is not ready: ${e?.message ?? e}`);
    process.exit(1);
  }
}
const VALUE_FLAGS = new Set(["--workspace", "--only", "--model", "--whisper-version", "--cache-dir", "--show-asr"]);
const positionals = argv.filter((a, i) => !a.startsWith("--") && !(i > 0 && VALUE_FLAGS.has(argv[i - 1])));
const slug = positionals[0];
if (!slug) {
  console.error(USAGE);
  process.exit(2);
}
// Identifiers are checked at the command-line boundary (same rules as scripts/pe_common.py).
const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const TURN_RE = /^t[0-9]{2,3}$/;
if (!SLUG_RE.test(slug) || slug.length > 60) {
  console.error(`align.mjs: invalid slug ${JSON.stringify(slug)}: use lowercase letters, digits and single hyphens`);
  process.exit(2);
}

// Workspace: --workspace, else ./explainers when run from the project root, else .. (run from explainers/remotion).
const WS = path.resolve(opt("--workspace", fs.existsSync(path.join(process.cwd(), "explainers", slug)) ? "explainers" : ".."));
const DIR = path.join(WS, slug);
{
  // containment, symlinks included: the episode folder must resolve inside the workspace
  const realWs = fs.existsSync(WS) ? fs.realpathSync(WS) : WS;
  const realDir = fs.existsSync(DIR) ? fs.realpathSync(DIR) : DIR;
  if (!realDir.startsWith(realWs + path.sep)) {
    console.error(`align.mjs: ${realDir} is outside the workspace ${realWs}`);
    process.exit(2);
  }
}
const MODEL = opt("--model", "small.en");
const WHISPER_VERSION = opt("--whisper-version", "1.5.5");
const CACHE = path.resolve(
  opt("--cache-dir", process.env.PODCAST_EXPLAINER_CACHE ?? path.join(os.homedir(), ".cache", "podcast-explainer")),
);
const ONLY = opt("--only", null)?.split(",").map((s) => s.trim()).filter(Boolean) ?? null;
const SHOW_ASR = opt("--show-asr", null)?.split(",").map((s) => s.trim()).filter(Boolean) ?? null;
for (const id of [...(ONLY ?? []), ...(SHOW_ASR ?? [])]) {
  if (!TURN_RE.test(id)) {
    console.error(`align.mjs: invalid turn id ${JSON.stringify(id)}: use t followed by 2 or 3 digits`);
    process.exit(2);
  }
}
// Trailing silence added to every clip before ASR: whisper.cpp often drops the token timestamps of
// the last words of a clip that ends right after speech (7 of 72 turns on 2 Nov 2026).
const ASR_PAD_S = 0.6;
const ESTIMATE_ONLY = flag("--estimate-only");
const WARN_RATE = 0.9;

const die = (msg) => {
  console.error(`align.mjs: ${msg}`);
  process.exit(1);
};
const readJson = (p) => {
  if (!fs.existsSync(p)) die(`missing ${p}`);
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (e) {
    die(`${p} is not valid JSON: ${e.message}`);
  }
};

const timingPath = path.join(DIR, "timing.json");
const timing = readJson(timingPath);
const script = readJson(path.join(DIR, "script.json"));

function spokenTextOf(text) {
  return text.replace(/<([a-z][a-z \-]*)>/g, " ").replace(/\|[^|]*\|/g, " ").replace(/\|/g, " ").replace(/\s+/g, " ").trim();
}
const scriptTurns = new Map();
for (const seg of script.segments ?? []) for (const t of seg.turns ?? []) scriptTurns.set(t.id, t);

if (!Array.isArray(timing.turns) || timing.turns.length === 0) die(`${timingPath} has no turns[]`);
for (const t of timing.turns) {
  if (!scriptTurns.has(t.id)) die(`turn ${t.id} is in timing.json but not in script.json`);
  if (typeof t.startMs !== "number" || typeof t.endMs !== "number") die(`turn ${t.id} has no startMs/endMs in timing.json`);
}
if (ONLY) for (const id of ONLY) if (!timing.turns.some((t) => t.id === id)) die(`--only names unknown turn ${id}`);
if (SHOW_ASR) {
  for (const id of SHOW_ASR) {
    const t = timing.turns.find((x) => x.id === id);
    if (!t) die(`--show-asr names unknown turn ${id}`);
    const said = (t.asr ?? []).map((w) => w.text).join(" ");
    console.log(`${id} script: ${spokenTextOf(scriptTurns.get(id).text)}`);
    console.log(`${id} heard:  ${t.asr ? said : "(no raw ASR stored: run align.mjs without --estimate-only)"}`);
  }
  process.exit(0);
}

// ---------- text normalisation and the alignment ----------

const SMALL = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const norm = (w) => {
  const s = w.toLowerCase().replace(/[’']/g, "").replace(/%/g, "percent").replace(/[^a-z0-9]/g, "");
  return /^\d+$/.test(s) && Number(s) <= 10 ? SMALL[Number(s)] : s;
};

const lev = (a, b) => {
  if (a === b) return 0;
  const m = a.length;
  const n = b.length;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[n];
};
// Close enough to treat as the same word: exact, or a small spelling difference on a long word
// (ASR writes "softmaxes" or "Kubernetes" slightly differently).
const similar = (a, b) => {
  if (!a || !b) return false;
  if (a === b) return true;
  const L = Math.max(a.length, b.length);
  return L >= 5 && lev(a, b) / L <= 0.25;
};

// Spoken text only: Gemini <tags> and |backchannels| (the other host, chunk mode) are not script words.
// Same patterns as tts.py TAG_RE and PIPE_RE.
const spokenText = (text) => text.replace(/<([a-z][a-z \-]*)>/g, " ").replace(/\|[^|]*\|/g, " ");

// Script tokens: split on whitespace; a token with no letters or digits (an em dash) joins the previous token.
const scriptTokens = (text) => {
  const out = [];
  for (const raw of spokenText(text).split(/\s+/).filter(Boolean)) {
    if (!norm(raw) && out.length) out[out.length - 1] += ` ${raw}`;
    else out.push(raw);
  }
  return out;
};

// Edit-distance alignment of script words (a) to ASR words (b).
// Moves: match/substitute (0 if similar, else 1), skip a script word (1), skip an ASR word (1),
// one script word = two ASR words ("KV-cache" vs "KV" "cache", 0.2),
// two script words = one ASR word ("hash map" vs "hashmap", 0.2).
// Returns, per script word, the ASR span [j0, j1] it matched, or null.
const alignWords = (a, b) => {
  const n = a.length;
  const m = b.length;
  const INF = 1e9;
  const D = Array.from({ length: n + 1 }, () => new Float64Array(m + 1).fill(INF));
  const P = Array.from({ length: n + 1 }, () => new Int8Array(m + 1));
  D[0][0] = 0;
  for (let i = 0; i <= n; i++) {
    for (let j = 0; j <= m; j++) {
      const here = D[i][j];
      if (here >= INF) continue;
      const relax = (ii, jj, cost, move) => {
        if (ii <= n && jj <= m && here + cost < D[ii][jj]) {
          D[ii][jj] = here + cost;
          P[ii][jj] = move;
        }
      };
      if (i < n && j < m) relax(i + 1, j + 1, similar(a[i], b[j]) ? 0 : 1, 1);
      if (i < n) relax(i + 1, j, 1, 2);
      if (j < m) relax(i, j + 1, 1, 3);
      if (i < n && j + 1 < m && a[i] === b[j] + b[j + 1]) relax(i + 1, j + 2, 0.2, 4);
      if (i + 1 < n && j < m && a[i] + a[i + 1] === b[j]) relax(i + 2, j + 1, 0.2, 5);
    }
  }
  const span = new Array(n).fill(null);
  let i = n;
  let j = m;
  while (i > 0 || j > 0) {
    const mv = P[i][j];
    if (mv === 1) {
      if (similar(a[i - 1], b[j - 1])) span[i - 1] = [j - 1, j - 1];
      i--;
      j--;
    } else if (mv === 2) i--;
    else if (mv === 3) j--;
    else if (mv === 4) {
      span[i - 1] = [j - 2, j - 1];
      i--;
      j -= 2;
    } else if (mv === 5) {
      span[i - 2] = [j - 1, j - 1, 0];
      span[i - 1] = [j - 1, j - 1, 1];
      i -= 2;
      j--;
    } else break;
  }
  return span;
};

// Script words with times (ms, clip-relative). `asr` items: {text, startMs, endMs}.
const snap = (tokens, asr, lo, hi) => {
  const a = tokens.map(norm);
  const b = asr.map((w) => norm(w.text));
  const span = alignWords(a, b);
  const out = tokens.map((t, i) => {
    const s = span[i];
    if (!s) return { text: t, startMs: NaN, endMs: NaN, source: "interpolated" };
    let st = asr[s[0]].startMs;
    let en = asr[s[1]].endMs;
    if (s.length === 3) {
      // two script words share one ASR word: split it in half
      const mid = (st + en) / 2;
      [st, en] = s[2] === 0 ? [st, mid] : [mid, en];
    }
    return { text: t, startMs: st, endMs: en, source: "asr" };
  });
  fill(out, lo, hi);
  return out;
};

// Unmatched words: spread evenly between their matched neighbours (or the clip edges).
const fill = (words, lo, hi) => {
  for (let i = 0; i < words.length; i++) {
    if (!Number.isNaN(words[i].startMs)) continue;
    let k = i;
    while (k < words.length && Number.isNaN(words[k].startMs)) k++;
    const s = i === 0 ? lo : words[i - 1].endMs;
    const e = k === words.length ? hi : words[k].startMs;
    const step = Math.max(0, e - s) / (k - i);
    for (let q = i; q < k; q++) {
      words[q].startMs = s + step * (q - i);
      words[q].endMs = s + step * (q - i + 1);
    }
    i = k - 1;
  }
};

// No ASR: spread [lo, hi] over the words by letter count.
const estimate = (tokens, lo, hi) => {
  const lens = tokens.map((t) => Math.max(1, norm(t).length) + 1);
  const sum = lens.reduce((x, y) => x + y, 0);
  let acc = lo;
  return tokens.map((t, i) => {
    const d = ((hi - lo) * lens[i]) / sum;
    const w = { text: t, startMs: acc, endMs: acc + d, source: "estimated" };
    acc += d;
    return w;
  });
};

// ---------- audio and whisper ----------

const ffmpegOk = spawnSync("ffmpeg", ["-version"]).status === 0;
if (!ffmpegOk) die("ffmpeg is not on PATH");

const clipDurationMs = (file) => {
  const r = spawnSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file]);
  const d = parseFloat(r.stdout?.toString() ?? "");
  if (r.status !== 0 || Number.isNaN(d)) die(`cannot read the duration of ${file}`);
  return Math.round(d * 1000);
};

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "pe-align-"));
const to16k = (file) => {
  const out = path.join(TMP, `${path.basename(file, path.extname(file))}-${Math.random().toString(36).slice(2, 8)}.wav`);
  // apad adds trailing silence only, so ASR times stay clip-relative.
  const r = spawnSync("ffmpeg", ["-v", "error", "-y", "-i", file, "-af", `apad=pad_dur=${ASR_PAD_S}`, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", out]);
  if (r.status !== 0) die(`ffmpeg could not resample ${file}: ${r.stderr.toString().trim()}`);
  return out;
};

// A missing package is a usage error (wrong folder), not a whisper failure: stop instead of estimating.
// The package comes from the workspace Remotion project (<workspace>/remotion) or the current folder.
const loadWhisperLib = () => {
  const places = [path.join(WS, "remotion"), process.cwd()];
  for (const dir of places) {
    try {
      return createRequire(path.join(dir, "package.json"))("@remotion/install-whisper-cpp");
    } catch {
      // try the next place
    }
  }
  die(
    `@remotion/install-whisper-cpp is not installed in ${places.join(" or ")}. Copy templates/remotion to <workspace>/remotion and run npm install there, or pass --estimate-only.`,
  );
};
if (!ESTIMATE_ONLY) loadWhisperLib();

let whisper = null; // { transcribe, whisperPath }
const setupWhisper = async () => {
  const lib = loadWhisperLib();
  const whisperPath = path.join(CACHE, `whisper.cpp-${WHISPER_VERSION}`);
  fs.mkdirSync(CACHE, { recursive: true });
  const exe = lib.getWhisperExecutablePath
    ? lib.getWhisperExecutablePath(whisperPath, WHISPER_VERSION)
    : path.join(whisperPath, "main");
  if (!fs.existsSync(exe)) {
    console.log(`installing whisper.cpp ${WHISPER_VERSION} into ${whisperPath} (one time, about 30 s) ...`);
    if (fs.existsSync(whisperPath)) fs.rmSync(whisperPath, { recursive: true, force: true });
    await lib.installWhisperCpp({ to: whisperPath, version: WHISPER_VERSION, printOutput: false });
  }
  const modelFile = path.join(whisperPath, `ggml-${MODEL}.bin`);
  if (!fs.existsSync(modelFile)) {
    console.log(`downloading whisper model ${MODEL} into ${whisperPath} (one time) ...`);
    await lib.downloadWhisperModel({ model: MODEL, folder: whisperPath, printOutput: false });
  }
  return { transcribe: lib.transcribe, whisperPath };
};

// Whisper words with clip-relative ms. With splitOnWord each item is one word.
// start = the earlier of the item offset and the first token's DTW time (the offset alone
// runs late after a pause); end = the item offset end, clipped to the next word's start.
const transcribeFile = async (file, raw) => {
  const wav16 = to16k(file);
  const { transcription } = await whisper.transcribe({
    inputPath: wav16,
    whisperPath: whisper.whisperPath,
    whisperCppVersion: WHISPER_VERSION,
    model: MODEL,
    tokenLevelTimestamps: true,
    splitOnWord: true,
    printOutput: false,
  });
  const words = [];
  for (const item of transcription) {
    const text = item.text.trim();
    if (!text || !norm(text)) continue;
    const tok = item.tokens.find((t) => norm(t.text));
    const dtw = tok && tok.t_dtw >= 0 ? tok.t_dtw * 10 : Infinity;
    words.push({ text, startMs: Math.min(item.offsets.from, dtw), endMs: item.offsets.to });
  }
  raw.push(...words.map((w) => ({ ...w })));
  for (let i = 0; i < words.length; i++) {
    const next = words[i + 1];
    if (next) words[i].endMs = Math.min(words[i].endMs, next.startMs);
    words[i].endMs = Math.max(words[i].endMs, words[i].startMs + 40);
  }
  return expandAsr(words);
};

// ASR writes "100-200" or "5-10%" as one item; the script says "100 to 200", "5 to 10 percent".
// Split such items into sub-words that share the item's time, for matching only.
const expandAsr = (words) => {
  const out = [];
  for (const w of words) {
    const parts = w.text
      .replace(/(\d)\s*[-–]\s*(\d)/g, "$1 to $2")
      .replace(/%/g, " percent")
      .split(/\s+/)
      .filter((p) => norm(p));
    if (parts.length <= 1) {
      out.push(w);
      continue;
    }
    const step = (w.endMs - w.startMs) / parts.length;
    parts.forEach((p, i) => out.push({ text: p, startMs: w.startMs + step * i, endMs: w.startMs + step * (i + 1) }));
  }
  return out;
};

// ---------- main ----------

const started = Date.now();
let mode = ESTIMATE_ONLY ? "estimated" : "whisper.cpp";
if (!ESTIMATE_ONLY) {
  try {
    whisper = await setupWhisper();
  } catch (e) {
    mode = "estimated";
    console.warn(`WARNING: whisper.cpp unavailable (${e.message}). All words fall back to source=estimated.`);
  }
}

// Group the selected turns by audio file (one file per turn in per-turn mode).
const selected = timing.turns.filter((t) => !ONLY || ONLY.includes(t.id));
const groups = new Map();
for (const t of selected) {
  if (!t.file) die(`turn ${t.id} has no "file" in timing.json`);
  const abs = path.join(DIR, t.file);
  if (!fs.existsSync(abs)) die(`turn ${t.id}: audio file ${abs} does not exist`);
  if (!groups.has(abs)) groups.set(abs, []);
  groups.get(abs).push(t);
}

const report = [];
for (const [file, turns] of groups) {
  turns.sort((x, y) => x.startMs - y.startMs);
  const chunked = turns.length > 1;
  const chunkInfo = (timing.chunks ?? []).find((c) => path.join(DIR, c.file) === file);
  const offset = chunked ? (chunkInfo?.startMs ?? Math.min(...turns.map((t) => t.startMs))) : turns[0].startMs;
  const clipMs = clipDurationMs(file);

  const tokensByTurn = turns.map((t) => scriptTokens(scriptTurns.get(t.id).text));
  const flat = tokensByTurn.flat();
  let words;
  let used = mode;
  const rawAsr = [];
  if (mode === "whisper.cpp") {
    try {
      const asr = await transcribeFile(file, rawAsr);
      words = snap(flat, asr, 0, clipMs);
    } catch (e) {
      used = "estimated";
      console.warn(`WARNING: whisper failed on ${path.relative(WS, file)} (${e.message}); turns ${turns.map((t) => t.id).join(",")} use estimated words.`);
    }
  }
  if (!words) words = estimate(flat, 0, clipMs); // a chunk is spread over all its turns by letter count

  // Split back into turns and move onto the episode clock.
  let k = 0;
  turns.forEach((t, ti) => {
    const n = tokensByTurn[ti].length;
    const tw = words.slice(k, k + n);
    k += n;
    const startMs = chunked ? Math.round(offset + tw[0].startMs) : t.startMs;
    const endMs = chunked ? Math.round(offset + tw[tw.length - 1].endMs) : t.endMs;
    let last = startMs;
    t.words = tw.map((w) => {
      const s = Math.min(Math.max(Math.round(offset + w.startMs), last, startMs), endMs);
      const e = Math.min(Math.max(Math.round(offset + w.endMs), s + 1), endMs);
      last = s;
      return { text: w.text, startMs: s, endMs: Math.max(e, s), source: w.source };
    });
    if (chunked) {
      t.startMs = startMs;
      t.endMs = endMs;
    }
    // Raw ASR (what was heard, unsnapped) for the fidelity check, on the episode clock. In a shared
    // chunk file each ASR word goes to the turn whose span holds its midpoint.
    if (used === "whisper.cpp") {
      const mine = rawAsr.filter((w) => {
        if (!chunked) return true;
        const mid = offset + (w.startMs + w.endMs) / 2;
        return mid >= startMs - 150 && mid <= endMs + 150;
      });
      t.asr = mine.map((w) => ({ text: w.text, startMs: Math.round(offset + w.startMs), endMs: Math.round(offset + w.endMs) }));
    } else {
      delete t.asr;
    }
    t.alignedAudioSha = t.audioSha ?? null;
    const asrCount = t.words.filter((w) => w.source === "asr").length;
    t.matchRate = t.words.length ? Math.round((asrCount / t.words.length) * 1000) / 1000 : 0;
    report.push({ id: t.id, n: t.words.length, asr: asrCount, rate: t.matchRate, used });
  });
}

const all = timing.turns.flatMap((t) => t.words ?? []);
const allAsr = all.filter((w) => w.source === "asr").length;
// engine describes the whole file: whisper.cpp when any word in it was measured.
const measured = allAsr > 0;
timing.alignment = {
  engine: measured ? "whisper.cpp" : "estimated",
  whisperCpp: measured ? (mode === "whisper.cpp" ? WHISPER_VERSION : (timing.alignment?.whisperCpp ?? WHISPER_VERSION)) : null,
  model: measured ? (mode === "whisper.cpp" ? MODEL : (timing.alignment?.model ?? MODEL)) : null,
  matchRate: all.length ? Math.round((allAsr / all.length) * 1000) / 1000 : 0,
  // Draft mode: any estimated word means the timing is not measured and delivery is blocked.
  draft: timing.turns.some((t) => !t.words || t.words.some((w) => w.source === "estimated")),
  alignedAt: new Date().toISOString(),
};
fs.writeFileSync(timingPath, `${JSON.stringify(timing, null, 2)}\n`);
fs.rmSync(TMP, { recursive: true, force: true });

console.log(`align: ${report.length} turns, ${((Date.now() - started) / 1000).toFixed(1)} s, this run ${mode}`);
console.log("turn      words  asr  match");
let low = 0;
for (const r of report) {
  const warn = r.used !== "estimated" && r.rate < WARN_RATE ? "  WARN under 90 %" : r.used === "estimated" ? "  estimated" : "";
  if (warn.includes("WARN")) low++;
  console.log(`${r.id.padEnd(9)} ${String(r.n).padStart(5)} ${String(r.asr).padStart(4)}  ${(r.rate * 100).toFixed(0).padStart(4)} %${warn}`);
}
console.log(`overall match ${(timing.alignment.matchRate * 100).toFixed(1)} % -> ${path.relative(process.cwd(), timingPath)}`);
if (low)
  console.warn(
    `WARNING: ${low} turn(s) under 90 % match: a TTS skip or ad-lib, or an aligner miss. The fidelity report below tells which; ` +
      `print what was heard with: node align.mjs ${slug} --show-asr <turn ids>`,
  );
if (timing.alignment.draft)
  console.warn("DRAFT: some word times are estimated, not measured. This timing is a draft: qc.py blocks delivery until align.mjs runs with whisper.cpp.");

// Fidelity: raw ASR vs script, both directions. Exit 1 on an unresolved failure.
const fid = spawnSync("python3", [path.join(path.dirname(fileURLToPath(import.meta.url)), "fidelity.py"), "--workspace", WS, "--slug", slug], {
  stdio: "inherit",
});
if (fid.error) {
  console.warn(`WARNING: could not run fidelity.py (${fid.error.message}); run it by hand: python3 <skill>/scripts/fidelity.py --workspace ${WS} --slug ${slug}`);
  process.exit(1);
}
process.exit(fid.status ?? 1);
