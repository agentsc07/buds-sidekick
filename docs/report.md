# Buds Sidekick: a private, local voice assistant for earbuds

## Problem
Conversations are fast and forgettable. People forget who promised what, what a number was, or what was just said in a language they
half speak. Cloud assistants could help, but they would have to listen to everyone in the room. The goal: an assistant that works through
earbuds the user already owns, understands who is speaking, remembers, speaks only when useful, and **keeps everything on the laptop**.

## Method
A Mac app (FastAPI + a browser dashboard) reads the Galaxy Buds FE microphone and touch/wear signals over Bluetooth (reverse-engineered
RFCOMM protocol in `lab/`). Audio is cut into utterances by an adaptive voice-activity segmenter. Each utterance is (1) matched to a
saved voiceprint (NeMo TitaNet-small, k-nearest-neighbour scoring with score normalisation and per-microphone samples; unknown voices
are never stored), (2) transcribed (faster-whisper small.en; a Telugu-tuned Whisper behind a language gate), (3) stored per the speaker's
privacy policy in SQLite with embeddings for retrieval. **Ask** answers from calendar, to-dos and retrieved lines with the source.
**Autopilot** combines rules (your promise becomes a to-do, a stored commitment is mentioned, a known name briefed) with a model
judge (Gemma 4 12B via Ollama) behind gates: category, minimum gap, hourly budget, never while someone is speaking; every whisper and every
silence is logged with its reason. Translation English <-> Telugu uses the same resident model and a Telugu voice. A memory-residency
manager keeps one large model resident on a 16 GB machine. Live translation (they speak one language, you hear the other in your ear) is built and switchable, with the latency caveat below.

## Evaluation
Machine: MacBook Air M3, 16 GB, quiet-ish (load average 4-6). Raw data: `docs/validation/eval-results.json`.

| Measure | Result | Data and caveat |
|---|---|---|
| Speaker ID equal error rate | 2.0% with TitaNet (ResNet34: 7.1%, CAM++ 28.8%) | 12 synthetic voices, buds-like channel; real people not yet measured |
| English WER | 4.9% (6/122) | 12 synthetic clips; the 6 errors are number formatting ("$2 million") |
| Telugu WER | 9.5% (2/21) | 4 synthetic clips; both errors are a word-split spelling (ఈ రోజు / ఈరోజు) |
| End of speech -> Autopilot whisper | 2.0 s median (n=5) | text published; spoken playback adds 2-4 s |
| End of speech -> Ask answer (LLM) | 2.1 s median (n=5) | grounded answer from memory |
| End of speech -> quick command | 2.2 s median (n=5) | calendar rule; dominated by pause detection (0.7 s) + recognition (~1 s) |
| Autopilot precision, scripted | 100% (8/8) | rules only, labelled 10-minute script; **not** a human judgement |
| Autopilot precision, human-rated | pending | needs a rated session (`docs/validation/recording-script.md`) |

Two defects were found and fixed by this evaluation: the file-audio simulator drifted ~5% against real time (inflating latencies by
up to 16 s over a minute), and Whisper mis-heard the assistant's own name ("Sidekick" -> "I take it"), silently disabling Ask; a spelling
hint in the recogniser prompt fixed it. 422 automated tests pass.

## Limitations
- All accuracy numbers so far use synthetic voices; real-speaker speaker-ID, Telugu recognition and human-rated Autopilot precision are pending recordings.
- Live Translate (voice in, voice out) measured 5.8-6.6 s median against a 2.5-3 s target, is 3-10x slower on a busy Mac and
  has a 19 s cold start. It is on but experimental (`live_translation: false` hides it). Telugu from real speakers is unmeasured.
- Buds accept one control client (phone Bluetooth must be off); macOS and Apple silicon only; no encryption at rest.
- Latency figures exclude speech playback.

## Next steps
Record the real-voice sets and report their numbers; streaming Telugu recognition (a streaming Conformer) to bring the Interpreter under
3 s; a signed .app/.dmg; encryption at rest for the SQLite file; a user study of Autopilot usefulness over a week.
