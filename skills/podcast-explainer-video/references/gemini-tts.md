# Gemini TTS for the explainer

How `scripts/tts.py` turns `script.json` into `audio/episode.wav` and turn-level `timing.json`, and what to do when a take goes wrong.

## Contents

1. Models and the 17 Nov 2026 shutdown
2. Commands
3. Request shape (per-turn and chunk)
4. Voices: default pair and audition
5. Style and tags
6. Limits
7. Cost
8. What tts.py does to the audio
9. Known bugs and the mitigations in tts.py
10. Redo a turn or a segment
11. Chunk mode
12. Troubleshooting by error message
13. Measurements
14. Names that ASR mishears (lexicon)

## 1. Models and the 17 Nov 2026 shutdown

| Model | Use | Status |
| --- | --- | --- |
| `gemini-3.8-flash-tts` | Default. Google recommends it for multi-speaker dialogue and long-form stability. | Current |
| `gemini-3.8-flash-lite-tts` | Fallback: cheaper and faster, same request shape. Voices sound a little different, so switch for a whole episode, not for one turn. | Current |
| `gemini-3.1-flash-tts-preview`, `gemini-2.5-flash-preview-tts`, `gemini-2.5-pro-preview-tts` | Never. `tts.py` refuses them. | Shutdown 17 Nov 2026, per the Gemini API deprecations page https://ai.google.dev/gemini-api/docs/deprecations (fetched by the research agent on 2 Nov 2026) |

Use the Gemini Developer API (`generativelanguage.googleapis.com`, `generateContent`, header `x-goog-api-key`). The 3.8 models are not on the Cloud Text-to-Speech API. The model list for the key on 2 Nov 2026 showed all five TTS models above.

The key comes from env `GEMINI_API_KEY`, else from the single variable `GEMINI_API_KEY` in `~/.config/podcast-explainer/env`, which `tts.py` parses in code with the same parser as `preflight.py` (`scripts/pe_common.py`; it handles `GEMINI_API_KEY="value" # comment`). The script never prints, logs or writes the key. It checks the key for header-safe characters before any request (a bad key fails with a message that never shows it), and every log line, error, `tts-report.json` and cache metadata file passes through redaction, because an API or proxy error body can reflect the request. Since 19 June 2026 the API rejects unrestricted keys: an AI Studio key is fine, a Cloud console key must be restricted to the Gemini API.

`google-genai` 1.73.1 (installed) has no `SpeechMetadata` type and no `speech_metadata` field on `Part`, so `tts.py` calls REST with `urllib` and needs no third-party package.

## 2. Commands

Run from the skill folder. `<ep>` is the episode folder that holds `script.json`.

| Goal | Command |
| --- | --- |
| Turn count, characters, estimated duration and cost, no API call | `python3 scripts/tts.py <ep> --dry-run` |
| Free timing draft with macOS `say` voices (`scratch: true`) | `python3 scripts/tts.py <ep> --scratch` |
| Real audio, one call per turn | `python3 scripts/tts.py <ep>` |
| Audition voices | `python3 scripts/tts.py <ep> --audition Sulafat,Iapetus,Leda` |
| Redo turns after a text edit | `python3 scripts/tts.py <ep> --only t03,t04` |
| Redo a segment | `python3 scripts/tts.py <ep> --segment seg02` |
| New take of an unchanged turn that sounds wrong | `python3 scripts/tts.py <ep> --only t03 --retake` |
| Two-speaker chunks (EXPERIMENTAL, not for delivery, section 11) | `python3 scripts/tts.py <ep> --mode chunk --experimental` |
| Cheaper model | `python3 scripts/tts.py <ep> --model gemini-3.8-flash-lite-tts` |

Other flags: `--gap-ms` (default 250), `--tail-pad-ms` (600), `--lead-ms` (250), `--lufs` (-19, mono; the stereo mp4 then measures about -16), `--true-peak` (-4.5 dBTP ceiling of the wav; both loudness defaults come from `pe_common.py` `MONO_LUFS` and `MONO_TRUE_PEAK`), `--experimental` (required with `--mode chunk`), `--no-normalize`, `--workers` (4 parallel calls), `--tries` (3), `--timeout` (120 s), `--min-ratio` (0.5), `--max-ratio` (2.5), `--chunk-turns` (8), `--chunk-chars` (1800).

Outputs: `audio/cache/<hash>.wav` and `.json` (raw take and its call log), `audio/turn-<id>.wav` (trimmed clip, raw level), `audio/episode.wav` (normalised), `timing.json`, `audio/tts-report.json` (calls, latency, tokens, cost, loudness of the last run).

## 3. Request shape (per-turn and chunk)

Endpoint: `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent` with header `x-goog-api-key`.

Per-turn (default), one voice, `speech_metadata` only when the turn has a style:

```json
{ "contents": [{ "role": "user", "parts": [
    { "text": "Try it. The table starts with 16 buckets.", "speech_metadata": { "style": "warm" } } ] }],
  "generationConfig": { "responseModalities": ["AUDIO"],
    "speechConfig": { "voiceConfig": { "voice": "Iapetus" } } } }
```

Chunk, two speakers, one part per turn, `speech_metadata.speaker` on every part (else HTTP 400 "Multi-speaker generation requests must specify speech_metadata.speaker for each text part"):

```json
{ "contents": [{ "role": "user", "parts": [
    { "text": "So every key gets its own slot?", "speech_metadata": { "speaker": "Nia" } },
    { "text": "Try it |hmm| with 16 buckets.", "speech_metadata": { "speaker": "Theo" } } ] }],
  "generationConfig": { "responseModalities": ["AUDIO"],
    "speechConfig": { "multiSpeakerVoiceConfig": { "speakerVoiceConfigs": [
      { "speaker": "Nia", "voiceConfig": { "prebuiltVoiceConfig": { "voiceName": "Sulafat" } } },
      { "speaker": "Theo", "voiceConfig": { "prebuiltVoiceConfig": { "voiceName": "Iapetus" } } } ] } } } }
```

The speaker label is `speakers[].name` from `script.json` (the `id` if two names clash). Response: `candidates[0].content.parts[0].inlineData` with `mimeType` `audio/wav` (RIFF header, 24 kHz, mono, 16-bit) on unary calls, plus `finishReason` and `usageMetadata` (`promptTokenCount`, `candidatesTokenCount`). The response holds no timestamps on any model, and `audioTranscriptionConfig.wordTimestamp` is ignored. Word times come from `align.mjs`.

## 4. Voices: default pair and audition

Default pair (chosen from the voice audition on 2 Nov 2026): learner host `Sulafat` (Warm), expert guest `Iapetus` (Clear), names Nia and Theo. Each voice gave a clean per-turn take on 2 Nov 2026 (W9 check, section 13), and the consistent-hashing v4 episode uses the pair for every turn. It is the pair in the sample `script.json` files. `tts.py` `DEFAULT_VOICES` applies it when a speaker in `script.json` has no `voice` (by `role`) and logs the fallback. The earlier pair `Kore` (Firm) and `Puck` (Upbeat) gave 6 of 6 clean takes on 2 Nov 2026 and stays a good fallback.

Google's 30 prebuilt voices with their one-word labels: Zephyr Bright, Puck Upbeat, Charon Informative, Kore Firm, Fenrir Excitable, Leda Youthful, Orus Firm, Aoede Breezy, Callirrhoe Easy-going, Autonoe Bright, Enceladus Breathy, Iapetus Clear, Umbriel Easy-going, Algieba Smooth, Despina Smooth, Erinome Clear, Algenib Gravelly, Rasalgethi Informative, Laomedeia Upbeat, Achernar Soft, Alnilam Firm, Schedar Even, Gacrux Mature, Pulcherrima Forward, Achird Friendly, Zubenelgenubi Casual, Vindemiatrix Gentle, Sadachbia Lively, Sadaltager Knowledgeable, Sulafat Warm. More voices: the Extended Voice Library (`GET /v1beta/voices`) and Voice design (`voice_...` IDs, which work in per-turn mode only, because a two-speaker request takes prebuilt voices only).

How to pick when the learner wants other voices:

Where to listen first: `python3 scripts/tts.py <ep> --audition <all 30 names>` writes one wav per voice (about $0.03 for all 30). AI Studio's speech page https://aistudio.google.com/generate-speech also plays every voice and browses the Extended Voice Library (voice list: https://ai.google.dev/gemini-api/docs/speech-generation#voices).

1. Pick 3 candidates for the role that changes. The two hosts must differ clearly in pitch or texture: pair a Firm or Bright voice with an Upbeat, Informative or Knowledgeable one.
2. Run `python3 scripts/tts.py <ep> --audition A,B,C`. It speaks one sentence (the first sentence of the script, or `--audition-text`) per voice into `audio/audition/<Voice>.wav` and prints an `afplay` command for each. Cost is about $0.001 per voice.
3. Let the learner listen and choose. Do not choose for them.
4. Set `speakers[].voice` in `script.json`. Every turn of that speaker gets a new hash, so the next run re-synthesises those turns.

## 5. Style and tags

- `text` is a verbatim transcript. 3.8 speaks stage directions and `Name:` prefixes aloud. Keep both out of `text`.
- `style` (turn field, or `speakers[].style` as a constant default) is short: empty for most turns, else 1 to 4 words such as `warm`, `curious`, `speaking slowly`. Reuse the exact same string to keep a baseline.
- Never write meta-instructions such as "keep the same voice" or "do not switch speaker identity", and never write long "Audio Profile" or "Director's Notes" blocks. Google names these as the most common cause of voice drift.
- Do not put age, gender, accent or names in `style`. Pick a different voice.
- Inline point events in angle brackets at the exact spot: `<short pause>`, `<long pause>`, `<laugh>`, `<chuckle>`, `<sigh>`, `<breath>`, `<gasp>`, `<cough>`, `<throat-clearing>`, `<tsk>`, `<exhales>`, `<whispers>` (full list in Google's speech-generation prompting guide). A tag not on the list is read as text. `<long pause>` lasts about 2.1 to 2.5 s.
- Square-bracket 3.1-style tags (`[excited]`) are legacy. Do not use them.
- Emphasis: CAPS on a word. Hesitation: `...` or `--`. Disfluencies ("uh", "hm") written into the text sound natural.
- Backchannels `|mhm|` (1 to 3 words in pipes, inside the active speaker's turn) work only in a two-speaker request. In per-turn mode `tts.py` removes them and warns, because one voice would speak both sides. Write a reaction as its own short turn instead ("Right." "Wait, really?").
- Keep each turn under 500 characters. Split a long turn into two turns of the same speaker.

## 6. Limits

| Item | Value |
| --- | --- |
| Input tokens per request | 8,192 |
| Output tokens per request | 16,384, at 25 audio tokens per second about 655 s, then the audio is truncated |
| Speakers per request | 2, prebuilt voices only |
| Internal re-anchoring on 3.8 | every ~500 input tokens (~1,900 characters), which can cause a 0.8 to 2.1 dB step (forum report). `tts.py` keeps a chunk at 1,800 characters or less. |
| Output format, unary | WAV, 24 kHz, mono, 16-bit LE (verified 2 Nov 2026) |
| Rate limits | Per project, shown only in AI Studio (https://aistudio.google.com/rate-limit). `tts.py` runs 4 calls in parallel and backs off on 429. |
| Consumption | Caching, thinking and structured output are not supported on 3.8 TTS |

## 7. Cost

Prices from https://ai.google.dev/gemini-api/docs/pricing (read 2 Nov 2026), USD per 1M tokens:

| Model | Until 31 Dec 2026 (text in / audio out) | From 1 Jan 2027 |
| --- | --- | --- |
| `gemini-3.8-flash-tts` | $0.50 / $9.00 | $1.00 / $18.00 |
| `gemini-3.8-flash-lite-tts` | $0.50 / $6.00 | $1.00 / $12.00 |

Per 10 minutes of speech on `gemini-3.8-flash-tts`: 600 s x 25 = 15,000 audio tokens, about $0.14 until 31 Dec 2026 and $0.27 from 1 Jan 2027. Input text adds under $0.01. A retry is billed again, so budget up to 2x. The measured run in section 13 cost $0.0144 for 64 s, which gives $0.135 per 10 minutes.

`tts.py` reads `usageMetadata` from every call (failed takes included) and prints the run cost at the end. `--dry-run` prints an estimate from 0.4 s per word (a deliberate overestimate: the measured rate is 0.357), adds the hold seconds separately (holds are not billed), and counts only the turns that the cache does not hold. It also prints the predicted final length (`pe_common.predict_length`: words x 0.357 s + pause tags + holds + `--gap-ms` gaps + `--tail-pad-ms` segment tails + `--lead-ms` lead, the same prediction as `validate_script.py` E39/W39) and an ERROR line when it is more than 15% over `targetMinutes` (a warning above 8%) or, for a series part, over 684 s (12 minutes minus 5% headroom). A length error makes `--dry-run` exit 1, and the paid run refuses to start on the same error (`pe_common.length_check`, with the actual `--gap-ms`, `--tail-pad-ms` and `--lead-ms`) unless `--allow-over-length "<reason>"` is given; the reason, the prediction and the errors go into `timing.json` `lengthOverride`. `--scratch` is never blocked. On the e2e-v4 and v5 runs it was within 1.2% and 0.5% of the measured audio.

## 8. What tts.py does to the audio

1. Builds one unit per turn (per-turn) or per chunk (chunk). The hash of each unit covers model, voice, style, text and mode. A unit whose hash is in `audio/cache/` is not called again. Turns with identical text, voice and style share one hash, so they get one job, one take and one bill, and two workers never write the same cache file.
2. Calls the API with up to 4 workers. Each take must pass all checks: HTTP 200, `finishReason` `STOP`, audio present, speech longer than 0.15 s, speech at least 0.5x the expected length (turns of 4 or more words), speech not over 2.5x and 2 s past the expected length. Expected length is 0.4 s per spoken word, plus 0.5 s per `<short pause>`, 2.3 s per `<long pause>`, 0.4 s per other tag or backchannel.
3. On a failed check, 429, 5xx, 408, timeout or network error, it retries after 2 s, then 4 s (plus jitter, or longer if the API sends `retryDelay`). After 3 failed takes it stops the run, names the turn and the reason, prints the cost so far and assembles nothing. A 400 or 403 stops at once. It never ships silence for a turn.
4. Trims each take to its speech (threshold -45 dBFS, 30 ms kept before, 60 ms after) and writes `audio/turn-<id>.wav` at raw level.
5. Joins: 250 ms lead, then each clip; after a clip comes the turn's `holdAfterMs` when it sets one (a pause-and-think hold that starts when the speech ends; `timing.json` records `holdStartMs` and `holdEndMs`), then `gapMs` of silence, or `tailPadMs` after the last turn of a segment (also after the last turn of the episode). `startMs`/`endMs` come from sample counts, so a clip's length equals its span exactly. The hold is not in the cache hash: a new or changed hold costs nothing.
6. Normalises the join to -19 LUFS integrated, true peak -4.5 dBTP (defaults `--lufs` and `--true-peak`, from `pe_common.MONO_LUFS` and `MONO_TRUE_PEAK`), with ffmpeg `loudnorm` in two passes. The wav is mono; Remotion encodes it as dual-mono stereo, which measures about 3 LU louder, so the mp4 lands near the -16 LUFS that `qc.py probe` checks. Remotion's audio path also raises the true peak by 1.6 to 2.5 dB, so the wav ceiling sits well under the -1 dBTP limit. History, not settings (2 Nov 2026, consistent-hashing): a -1.5 dBTP wav gave an mp4 at +0.1 dBTP and a -3.0 ceiling -0.7 dBTP, both fails; a -4.0 ceiling gave -1.5 dBTP at -16.1 LUFS, a pass with 0.5 dB to spare; the default then moved to -4.5, which gave -2.0 dBTP on the e2e-v3 render. Scratch audio is normalised the same way. The output is resampled to 24 kHz and cut or padded to the exact sample count of the join, so `timing.json` stays exact. Per-turn clips stay raw for alignment.
7. Writes `timing.json`. Each turn has the contract fields plus `timingSource` (`clip`, `silence` or `proportional`), `hash` (the request), `audioSha` (the take), `holdAfterMs`, `holdStartMs` and `holdEndMs` when set, and `chunk` in chunk mode. Top level adds `leadMs`, and `experimental: true` in chunk mode. Old `words[]` and raw `asr[]` are kept, shifted by the change in `startMs`, only when the take is the same: `audioSha` and the old `alignedAudioSha` both match. A `--retake` of unchanged text has a new `audioSha`, so its words are dropped and `align.mjs` must run on it.

## 9. Known bugs and the mitigations in tts.py

| Bug (source) | Mitigation |
| --- | --- |
| Silent truncation: HTTP 200 with `finishReason: OTHER` or a short clip, random, billed (Gemini forum, 2.5 and 3.1 era) | `STOP` check plus duration window, 3 takes, fail loudly |
| Multi-speaker voice swap, skipped, duplicated or invented lines (forum, 2.5 and 3.1) | Per-turn mode is the only supported mode, so a swap cannot happen. `fidelity.py` compares raw ASR with the script after alignment and fails on any changed number or negation. |
| 3.8 voice drift: timbre change mid-audio, takes differ (forum thread open on 27 Oct 2026) | Short requests, empty or constant style, listen, then `--only <id> --retake` |
| Loudness step every ~500 input tokens on 3.8 (forum) | Per-turn requests are far below 500 tokens. Seams fall on speaker changes. Final `loudnorm` evens out levels between takes. |
| Stage directions and speaker prefixes spoken aloud on 3.8 (Google migration notes) | `text` is verbatim; delivery goes in `style` |
| Unary 3.8 output is WAV, so concatenating bytes embeds headers as clicks (Google docs) | `tts.py` decodes every take to samples and writes one header |
| Streaming truncates past ~60 to 70 s (forum, 3.1) | `tts.py` uses unary calls only |
| No timestamps from TTS (forum, tested on 2.5, 3.1, 3.8) | Per-turn clips give exact turn times; `align.mjs` adds words |
| Old pod pipeline skipped a failed turn and shipped a gap (`ai-pod-produce/app/tts/tts_openai.py`) | The run stops with the turn id; nothing is assembled |
| Old pipeline only checked "file exists and size > 0" | Duration check against word count on every take, then `fidelity.py` (raw ASR vs script, both directions) after `align.mjs` |
| An error body that reflects the request could carry the key | Key validated before the header is built; all error text, logs, reports and cache metadata redacted |

## 10. Redo a turn or a segment

1. Edit the turn text (or `style`, or the speaker's voice) in `script.json`.
2. Run `python3 scripts/tts.py <ep> --only t07` (or `--segment seg03`). Only units whose hash changed are billed. Every other turn must already be in the cache for its current text, else the run stops and names it.
3. If the text is unchanged but the take sounds wrong (drift, crackle, odd stress), add `--retake`. The new take replaces the cached one. When another, unselected turn has the same text, voice and style, the new take is pinned to the selected turn only (`audio/cache/pins.json`), so the other turn keeps its take and its alignment. Audio, cache and turn clips must be real folders and files under the episode: `tts.py` refuses a symbolic link there.
4. Run `align.mjs --only` with the turns `tts.py` lists as "audio changed" (every turn whose take changed in this run, also in `tts-report.json` `changedTurns`), then `build_manifest.py`. All later turns move in time, and `timing.json` carries their shifted words. `build_manifest.py` refuses words aligned to an older take.

A full run without `--only` uses the cache too, so after edits to several turns a plain run bills only the edited ones.

## 11. Chunk mode

EXPERIMENTAL, not for delivery. `tts.py` refuses `--mode chunk` unless `--experimental` is also given, prints a warning, and marks `timing.json` `experimental: true`. Turn cuts inside a chunk are guesses from silences and word counts: a review on 2 Nov 2026 reproduced a cut that gave several seconds of one host to the other, and a hold inserted at that cut interrupts the wrong utterance. `align.mjs` aligns each cut clip, and `fidelity.py` catches a wrong cut as deletions and insertions, but do not ship chunk audio without a full listen.

`--mode chunk --experimental` sends 1 to 8 consecutive turns of one segment as one two-speaker request. The turns within a chunk keep the model's own pacing and can use `|backchannels|`; `gapMs` applies only between chunks. It needs exactly two speakers with prebuilt voices.

Turn times cannot come from file lengths in this mode. `tts.py` finds quiet runs of 120 ms or more (below -40 dBFS) inside the chunk, places each expected boundary by the share of expected speech length before it, and cuts at the quiet run whose middle is nearest (within 0.6 s or 40 % of an average turn, longer runs preferred). Each turn is then trimmed and saved as `audio/turn-<id>.wav`, so `align.mjs` still works per turn. A turn whose both edges came from quiet runs gets `timingSource: "silence"`. A turn with an edge placed by proportion gets `"proportional"` and needs a check: transcribe the two clips, or run `align.mjs` and look at the first and last words.

Checked on 2 Nov 2026 with 2 turns: both edges found by silence, and a `gemini-3.5-transcribe` pass on each clip returned exactly that turn's text. Not checked: that the voices were not swapped inside the chunk. Listen to every chunk.

Chunk mode costs the same per second of audio. A failed chunk wastes up to 8 turns of audio. A redo of one turn re-synthesises its whole chunk.

## 12. Troubleshooting by error message

| Message | Cause | Fix |
| --- | --- | --- |
| `no API key: set env GEMINI_API_KEY or add GEMINI_API_KEY to ...` | No key in env or file | Export the key in the shell, never in a file in the skill |
| `HTTP 400 INVALID_ARGUMENT: Request contains an invalid argument.` | Often a wrong voice name (seen 2 Nov 2026 with `NoSuchVoice`), a misspelt field, or a `voice_...` ID in chunk mode | Check `speakers[].voice` against section 4 |
| `HTTP 400 ... must specify speech_metadata.speaker for each text part` | Hand-built chunk request | Use `--mode chunk`, which sets it on every part |
| `HTTP 403 PERMISSION_DENIED` or `API key not valid` | Key unrestricted, revoked, or from the wrong project | Use an AI Studio key restricted to the Gemini API |
| `HTTP 404 ... model ... not found` | Model name typo or a shut-down model | `--model gemini-3.8-flash-tts` |
| `HTTP 429 RESOURCE_EXHAUSTED` after 3 tries | Project RPM/RPD or spend cap | Wait (RPD resets at midnight Pacific), lower `--workers` to 1, check AI Studio rate limits |
| `finishReason OTHER (... s of audio ...)` after 3 tries | Truncation, or a safety block shown as OTHER | Rephrase the turn, split it, or retry later |
| `possible truncation: X s, expected about Y s` | Take much shorter than its word count | Retry runs automatically. If it repeats, check for a long list of numbers or symbols and spell them out, or lower `--min-ratio` after listening. |
| `possible hallucination: X s, expected about Y s` | Take much longer: repeated or invented words, or many pause tags | Remove extra `<long pause>` tags; retake |
| `turn tNN has no cached take for its current text` | `--only`/`--segment` run while another turn has changed | Add that turn to `--only`, or run without it |
| `cached take is silent` | Cache file damaged | `--only <id> --retake` |
| `loudnorm pass 1 failed` | ffmpeg missing or the join is silent | Install ffmpeg 7; check the clips |
| `--mode chunk needs exactly two speakers` | Script has 1 or 3+ speakers | Use per-turn mode |
| `is deprecated (shutdown 17 Nov 2026)` | Old model name | Use a 3.8 model |

## 13. Measurements

2 Nov 2026, Gemini Developer API from London, `gemini-3.8-flash-tts`, voices Kore and Puck, empty style, 6-turn sample (t01 to t06 of `evals/files/sample-script.json`, 888 characters, 174 words):

| Measure | Value |
| --- | --- |
| Per-turn latency (9 to 13 s of speech per turn) | 3.4 to 4.6 s per call, all 6 on the first take |
| Wall time, 6 turns, 4 workers, including loudnorm | 9.0 s |
| Speech rate | 0.357 s per word (176 words in 62.8 s), so the 0.4 s per word estimate runs about 12 % long |
| Silence the API adds around a take | 0.3 to 0.5 s in total, removed by the trim |
| Tokens | 1,587 audio tokens for 61.1 s of trimmed speech (about 26 per second including the trimmed silence), 226 input tokens |
| Cost | $0.0144 for the 6 turns, $0.0025 for one redone turn, $0.0051 for a 2-turn chunk (22.4 s, 7.4 s latency), $0.0028 for a 3-voice audition |
| Loudness | raw join -17.0 LUFS; after loudnorm -16.0 LUFS integrated (ebur128), true peak -1.4 dBFS, no clipped samples. loudnorm chose dynamic mode because linear gain would pass the -1.5 dBTP ceiling used then. |
| Format | `episode.wav` pcm_s16le, 24,000 Hz, 1 channel; every clip length equals its `endMs - startMs` exactly (0 ms error) |
| Cache | after editing t03, `--only t03` billed 1 call and reused 5; an unchanged `--only t04` billed 0 |

Default pair check, 2 Nov 2026 (W9, consistent-hashing v4, `Sulafat` learner and `Iapetus` expert, empty style): a 2-voice audition cost $0.0007; the full episode billed 77 per-turn calls, 18,067 audio tokens, $0.1639, every take clean on the first try. One turn (t35, "5 mod 3 is 2") failed fidelity because the ASR heard "5.3"; one retake ($0.0031) passed. Speech rate: `Sulafat` 0.364 s per word, `Iapetus` 0.344 s per word, 0.353 overall (1,975 words in 696 s of speech), so the 0.357 budget constant still holds. Loudness after render: -16.0 LUFS, -2.0 dBTP.

Rerun on 2 Nov 2026 (consistent-hashing, 72 turns, 646 s, all 72 takes from the cache, $0 billed): with `--true-peak -3.0` the wav measured -19.0 LUFS and -2.8 dBTP, and the mp4 reached -0.7 dBTP; with -4.0 the wav measured -19.1 LUFS and -3.8 dBTP and the mp4 -16.1 LUFS and -1.5 dBTP (pass, 0.5 dB margin). The default is now -4.5 (section 10 and `pe_common.MONO_TRUE_PEAK`). Alignment with 0.6 s of trailing ASR padding: overall match 98.9 % (97.5 % before), 2 turns under 90 % (7 before); fidelity 60 ok, 11 warn, 1 fail before the homophone rule (none after).

## 14. Names that ASR mishears (lexicon)

Whisper writes some names wrongly (3 Nov 2026, v5: "Priya" heard as "pria"). List them in `brief.json` `lexicon`, for example `{"Priya": ["pria", "prayer"]}`. `fidelity.py` and `qc.py audio.fidelity` read a heard alias as its term, so the mishearing is not a warning. An alias that is a number, sign, negation or direction word, or a negating-prefix variant of its term, is refused (`validate_script.py` E40) and ignored, so the lexicon never hides a meaning change. The lexicon is part of the build identity.
