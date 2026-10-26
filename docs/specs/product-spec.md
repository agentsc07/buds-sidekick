# Buds Sidekick: a voice-aware personal assistant in your ear

*Spec v1. Supersedes the lab spec (now `lab/SPEC-lab.md`). Product code lives in `assistant/`; `lab/` stays the
experimentation sandbox and supplies the Bluetooth/protocol layer.*

## 1. What we are building, in one paragraph

A local-first assistant that lives in a Galaxy Buds FE and a MacBook. It **listens to conversations, knows who is
speaking by voice, remembers what each person said, and helps you in the moment**: you can ask it things
(**manual mode**), it can offer short whispered guidance on its own (**auto mode**), you can replay the last few
seconds you missed (**replay mode**), and it can keep a searchable record per person (**archive mode**). The idea is
RAG where the documents are conversations and the retrieval key is *who said it*. Gestures on the buds are the
controls; a local LLM (Ollama) is the brain; nothing leaves the machine unless you explicitly allow it.

## 2. Problem statement

People lose track in conversations: what someone promised last week, who this person is, what was just said while
attention drifted, what to answer. Notes apps need hands and eyes; voice assistants have no memory of *people* and do not
listen to the room. Earbuds are already in your ears, always with you, and (verified in this repo) give us touch gestures,
wear state and a microphone, but nothing uses them as a memory-and-coaching device.

## 3. Starting point (verified facts and assets)

| Fact | Source |
|---|---|
| Touch gestures arrive over RFCOMM with side + gesture (single/double/triple/hold); holds arrive as bursts, so toggle-debounce is needed | lab, real buds |
| Wear, case, battery (incl. case), noise mode are pushed; `noise_control`, touchpad and lock commands work (40-80 ms ack) | lab, real buds |
| Mic = Bluetooth headset profile: mono, <=16 kHz; opening it flips the buds to call mode (quality dip, flip delay) | observed; mic quality numbers still **unmeasured** |
| Buds permit one control client at a time (phone must be disconnected) | observed |
| Assistant pipeline exists: gestures -> chime -> VAD record -> Whisper -> agent -> `say`; sticky mic session; barge-in | `assistant/`, real buds |
| Machine: Apple M3, 16 GB RAM, Ollama installed with `qwen3.5:4b-mlx`, `qwen3.5:9b-mlx`, `gemma4:12b-mlx`, `llama3.2`, `nomic-embed-text` | checked 2026-10-01 |

**Largest unknown, and the first thing we test:** how well the buds' mics hear *the other person* (they are tuned for the
wearer's voice) and whether speaker recognition survives 16 kHz call-mode audio. See Phase 0.

## 4. Goals and non-goals

### Goals
1. **Identity-aware memory**: after enrolling a person once, recognise them in later conversations with >= 90 % segment accuracy and <= 5 % wrong-person labels on buds audio (gate in Phase 0; fallbacks in section 11).
2. **Manual mode useful in the moment**: spoken answer starts <= 3.5 s after you finish asking (p50), grounded in stored conversations with the right person.
3. **Replay mode as an attention safety net**: one gesture replays the last N seconds (default 8, configurable 5-60) in <= 700 ms, without ever persisting audio unless asked.
4. **Auto mode that helps without nagging**: >= 60 % of hints rated useful, <= 12 hints/hour, never talks over you.
5. **Private by construction**: all audio, voiceprints and transcripts stay local; per-person forget works completely; unknown people are never stored.
6. **REDUCED LATENCY IN EACH AND EVERY TASK POSSIBLE**
7. **A dashboard to view all this and interface to edit it easily and modify, etc. This further can be improved in later stages**

### Non-goals (v1)
- **Not a cloud product or multi-user service.** One user, one Mac, local models. (Optional cloud LLM is a later, explicit opt-in that sends text only.)
- **No phone/Android app, no standalone-without-Mac operation.** The Mac is the compute; Bluetooth range (~10 m) is the leash. Revisit after v1.
- **No emotion/stress/lie detection and no covert profiling.** Not reliable, ethically fraught, outside the brief.
- **No speaking *as* the user** (no voice cloning, no auto-replying). The assistant whispers to you only.
- **No firmware/reset/debug protocol use.** The allowlist from the lab stays; unknown messages stay listen-only.
- **No support for other earbuds** until the Buds FE flow is proven (keep the capture layer abstract, though).

## 5. Users and modes

**User:** one primary user (the wearer) who talks to colleagues, clients, family. Personas: *Professional* (meetings,
follow-ups), *Student/learner* (lectures, catching up), *Caregiver/relative* (remembering what family said), *Anyone with
attention or memory strain* who benefits from replay.

### Modes (an explicit state machine; one visible mode at all times)

| Mode | Audio | Does | Default control |
|---|---|---|---|
| **Idle** | mic closed (buds in music mode) | gestures work, manual one-shot questions | default |
| **Manual** | opens on demand (sticky ~20 s) | you ask; it answers using memory + current conversation | L double / L hold-toggle |
| **Conversation** | mic open, live ring buffer + rolling transcript + speaker ID | replay, "who is talking?", catch-up, logging | R hold-toggle |
| **Auto** | Conversation + proactive hints | whispers guidance by policy (section 8.4) | toggled from Conversation |
| **Archive** (flag on Conversation) | as Conversation | stores segments/audio per person under their retention rules | per-person opt-in |
| **Private** | mic hard-closed, nothing logged | for sensitive moments | one gesture; also auto when both buds out |

Wear/case state drives context: both buds out or in case = Private/Idle; one bud out = conversation continues
(you are probably talking to someone), ambient mode auto-enabled via the `noise_control` command and restored on exit.

## 6. User stories

**Manual mode**
- As the wearer, I want to double-tap and ask "what did Ravi say about the budget last week?" so that I can answer him without scrolling notes.
- As the wearer, I want to ask "who is talking?" and hear a one-word answer so that I never blank on a name.
- As the wearer, I want to say "remind me what I know about Anita" and get a 3-sentence brief so that I walk into the chat prepared.
- As the wearer, I want "what did I promise Ravi?" to list my open commitments to him so that I follow through.

**Replay / attention**
- As the wearer, I want one tap to replay the last 8 seconds so that a lapse of attention costs me nothing.
- As the wearer, I want "catch me up" to summarise the last two minutes so that I can rejoin a conversation gracefully.
- As the wearer, I want a "mark this" gesture so that important moments are bookmarked with who said them.

**Identity and enrolment**
- As the wearer, I want to register a person by name from a short sample, with their consent noted, so that they are recognised afterwards.
- As the wearer, I want unknown voices labelled "Speaker A/B" during a conversation and a chance to name them afterwards ("Speaker A was Ravi") so that enrolment needs no ceremony.
- As the wearer, I want to correct a wrong label by voice ("that wasn't Ravi, that was Dev") so that the system gets better, not stubborn.

**Auto mode**
- As the wearer, I want a whispered "That's Ravi. Last time: he owes you the Q3 report" when someone I know starts talking so that I have context instantly.
- As the wearer, I want a hint when I am asked a direct question and a stored fact answers it so that I respond accurately.
- As the wearer, I want to dismiss or mute hints with a gesture and have the assistant get quieter so that it never becomes noise.

**Archive and privacy**
- As the wearer, I want per-person choices (transcript only / audio too / nothing) so that I record only where I should.
- As the wearer, I want "forget Ravi" to delete his voiceprint, transcripts, audio and derived facts, verifiably, so that I can honour requests.
- As the wearer, I want an audit log of what was recorded, when, and why a hint was spoken so that I can trust it.

## 7. Scope expansion (what else this platform makes possible)

Ranked by value / effort. P0 = v1 core, P1 = fast follow, P2 = later.

| Area | Feature | P |
|---|---|---|
| Memory | Per-person dossier (facts, topics, last conversations) | P0 |
| Memory | Commitments tracker: "I'll send it Friday" extracted for both sides, with due dates and spoken reminders | P1 |
| Memory | Pre-conversation brief on voice recognition (the identity cue + one relevant fact) | P0/P1 |
| Memory | Topic threads across time ("everything about the budget, by person") | P1 |
| Attention | Replay N s, speed 1.0-1.5x, with text read-out option | P0 |
| Attention | Catch-up summary (30-120 s), "mark this", rolling transcript on screen | P0 |
| Guidance | Question-to-you detection + restate ("He asked: when can you deliver?") | P1 |
| Guidance | Fact lookup from your own notes/docs (local RAG over a folder) | P1 |
| Guidance | Talk-time/pace coach ("you've spoken 80 % of the last 5 minutes") | P2 |
| Guidance | Jargon/acronym explainer, unit/currency conversion | P2 |
| Guidance | Live translation whisper (needs multilingual STT/TTS) | P2 |
| Archive | Record per person with retention, searchable transcripts, export | P1 |
| Context | Auto ambient mode, Private on bud removal, battery warnings | P0 |
| Context | Calendar-aware ("meeting with Anita now") | P2 |
| Dashboard | People, timeline, transcripts with speaker colours, search, mode, privacy audit | P1 |
| Platform | Pluggable capture sources (buds, Mac mic, later phone/lapel), pluggable brain (local/cloud) | P0 (interfaces) |

## 8. Requirements

### 8.1 Capture and replay (P0)
- A `CaptureSource` interface (buds mic, Mac mic, file replay for tests) producing 16 kHz mono frames.
- **Ring buffer in RAM only**, default 8 s, configurable 5-60 s, per-conversation; cleared on mode exit, Private, or bud removal. Never written to disk unless Archive/keep-clip applies.
- **Acceptance:** Given Conversation mode, when R double-tap, then playback starts <= 700 ms and covers the last N s (+-0.3 s). Given Private mode, then nothing is buffered. Negative: a crash dump or log must not contain buffered audio.
- Replay playback through the buds (call-mode quality) with optional 1.25x; optional text read-out of the same span.
- "Keep clip" gesture promotes the last 30 s to a stored clip attributed to speakers.

### 8.2 Speaker identity (P0)
- Streaming VAD -> segments (>= 0.6 s) -> embedding (candidate: ECAPA-TDNN or a WeSpeaker/3D-Speaker ONNX model; chosen by Phase 0 benchmark) -> cosine match against enrolled centroids with an open-set threshold; unmatched voices become provisional clusters (Speaker A/B/...).
- **The wearer is a first-class enrolled speaker ("me")** so own speech is separated from others and can trigger manual queries by voice-activity rather than gestures if desired.
- Enrolment: (a) guided, 20-40 s of speech collected across prompts; (b) retroactive, name a provisional cluster after the conversation ("Speaker A was Ravi"); (c) correction by voice. Each enrolment records a **consent attestation** (who, when, how obtained).
- Voiceprint updates are conservative (only high-confidence segments adapt a centroid; max drift guard) and every change is logged and undoable.
- **Acceptance (gate):** on a held-out set recorded through the buds with >= 3 enrolled speakers + >= 3 strangers: segment accuracy >= 90 % for segments >= 2 s; stranger false-accept <= 5 %; confidence reported per segment. If missed, apply fallbacks (section 11) before building on identity.

### 8.3 Memory and brain (P0 manual, P1 extras)
- **Store:** SQLite for `people`, `conversations`, `segments(speaker, t0, t1, text, confidence, audio_ref?)`, `facts(person, kind: commitment|fact|preference|date, text, due, source_segment, status)`, `hints_log`, `audit_log`. Embeddings (`nomic-embed-text` via Ollama) stored as vectors; brute-force cosine search is fine at personal scale (< ~200k segments).
- **Fact extraction** runs after a conversation (or every few minutes live), via the LLM, with the source segment always attached so every claim is traceable and correctable.
- **Retrieval** for a query = filter by person (from the question or the current speaker) + semantic top-k + recency weighting; the prompt includes the *current conversation window* so "what did he just say" and "how should I answer" work.
- **Brain interface:** `Brain.respond(query, context) -> Reply(text, sources)`, local first: `qwen3.5:4b-mlx` default for latency, `qwen3.5:9b-mlx` for "think harder" queries; `RuleAgent` stays as the offline fallback and for deterministic commands (time, battery, notes). Optional cloud model: off by default, per-query opt-in, text only, never audio.
- Replies are **spoken-style**: <= 3 sentences by default, numbers and names spelled for TTS, with a "sources" option ("from Tuesday's call with Ravi").
- **Acceptance:** with a seeded fixture of 3 people and 20 conversations, 20 reference questions are answered with correct person attribution >= 85 % (graded by a fixed checklist), and the answer never cites a person who did not say it.

### 8.4 Auto mode policy (P1, minimal identity cue in P0)
Auto mode is a **policy engine around the brain**, not the brain talking constantly.
- **Triggers** (rules first, LLM judges only candidates): T1 known voice starts (identity cue, once per person per 10 min); T2 a question directed at you, detected after the speaker's end-of-turn, where retrieval finds a relevant fact; T3 a stored commitment or topic is mentioned; T4 a claim conflicts with a stored fact (P1+); T5 you hesitate after a question (silence > 2.5 s) (P1+).
- **Gating:** never while you are speaking; drop hints that go stale (> 6 s after trigger); <= 1 hint / 20 s and <= 12/hour; <= 20 words; whispered volume; ducking so real speech is not covered.
- **Feedback loop:** dismiss gesture = mute this class for 10 minutes; "useful"/"not useful" gestures log ratings; three dismissals in a row halve the hint rate automatically.
- **Acceptance:** replaying a scripted 10-minute 3-person conversation through the simulator yields hints only at labelled trigger points (precision >= 70 %, none during the wearer's speech); every hint has a log row with its trigger and sources.

### 8.5 Archive per person (P1)
- Per-person policy: `none` (default for unenrolled), `transcript`, `transcript+audio`; retention days; audio stored as compressed WAV/Opus under `data/people/<id>/`.
- Unknown speakers are never persisted (transcript text from them is dropped after the live window unless the user names them within the session).
- Export per person (JSON + audio) and **verified deletion** ("forget Ravi" removes voiceprint, segments, audio, facts, embeddings, and logs the deletion without the content).

### 8.6 Controls (defaults, all rebindable in `gestures.yaml`)
| Gesture | Action |
|---|---|
| L double | Ask (manual) |
| L hold (toggle) | Dictate a long question / note |
| R hold (toggle) | Conversation mode on/off |
| R double | Replay last N seconds |
| R triple | Dismiss / stop speaking / mute hints |
| L triple | "Who is talking?" |
| L single then R single | Mark this moment |
| R single then L single | Toggle Auto mode (while in Conversation) |
| Voice | "replay", "catch me up", "forget that", "that wasn't Ravi", "private mode" |

The buds still run their own defaults (e.g. hold toggles noise mode); the app remaps/locks these via the allowlisted commands on start and restores on exit.

### 8.7 Output (P0)
- Single audio-out arbiter with priorities (user-requested answer > hint > chime), barge-in, queue expiry, and ducking.
- Whisper-style hints: quieter TTS voice and slightly lower rate; soft chimes distinguish hint / answer / replay start.
- Optional screen mirror in the dashboard (live transcript with speaker colours) for debugging and for the user at the desk.

### 8.8 Privacy, safety and legality (P0, non-negotiable)
- **Local-only by default.** No network calls in the audio/identity path. Models run through local Ollama/Whisper.
- **Biometric data is sensitive.** Voiceprints and transcripts encrypted at rest (SQLCipher or per-file AES with a key in the macOS Keychain); file permissions locked down; no voiceprints in logs.
- **Consent.** Enrolment requires an attestation; the UI states that recording or identifying people without consent is illegal in many jurisdictions (two-party consent). Archive is opt-in per person.
- **Visibility.** A periodic soft cue while Conversation/Auto is live, a persistent menu-bar/dashboard indicator, and a one-gesture Private mode.
- **Minimisation.** Default retention for raw audio = none; derived text/facts kept under per-person retention.
- **Audit log** of mode changes, enrolments, hints (with trigger and sources), exports, deletions.
- **Safety rails for the brain:** hints are advisory, flagged when uncertain ("I think..."), never state a stored fact without a source, and never give legal/medical/financial directives.

## 9. Architecture

```
 Buds FE ──RFCOMM──> BudsLink (lab) ──> gesture engine ──┐
   │ (mic, HFP)                                           v
   └────audio────> CaptureSource ──> ring buffer ──> VAD ──> segmenter
                                        │ (RAM, N s)          │
                              replay <──┘                     ├─> speaker-ID (embed/match/cluster)
                                                              ├─> streaming STT (Whisper, VAD chunks)
                                                              v
                                             conversation window + memory store (SQLite + vectors)
                                                              │
                  mode state machine <──> policy engine ──> brain (Ollama LLM + retrieval) ──> output arbiter ──> TTS / replay -> buds
                                                              │
                                                  dashboard (FastAPI, reuse lab web) + audit log
```

- **Reuse** from `lab/`: transport, framing, decoders, `DeviceState`, command allowlist, runloop (macOS main-thread requirement), mic metrics, FastAPI dashboard shell.
- **Reuse** from `assistant/`: gesture recogniser (toggle debounce), sticky Recorder, Whisper STT, `say` TTS, chimes, barge-in, JSONL timing logs.
- **New packages:** `capture` (sources, ring buffer), `speaker` (embed/enrol/identify/cluster), `memory` (store, retrieval, fact extraction), `brain` (Ollama client, prompts, fallbacks), `policy` (auto triggers and gating), `modes`, `privacy` (consent, encryption, retention, forget), `eval` (harness).
- **Concurrency:** audio callback thread -> bounded queues -> worker threads (VAD, STT, speaker) -> asyncio event loop; slow stages drop work, never audio. Each stage logs timing.
- **Resource budget (M3, 16 GB, fanless):** Whisper `base.en` int8 for live transcription (consider `tiny.en`), speaker model on CPU/ONNX, one resident LLM (4B) plus embeddings; the 9B model loads on demand. Always-on pipeline target <= 35 % sustained CPU; measure thermal throttling in Phase 0.
- **Simulator:** `FileCaptureSource` replays multi-speaker WAVs and scripted gestures; `FakeBrain` for deterministic tests; all phases ship with simulator tests so nothing depends on live humans.

## 10. Success metrics

| Metric | Target | When |
|---|---|---|
| Speaker segment accuracy (buds audio, >= 2 s) | >= 90 %, stranger false-accept <= 5 % | Phase 0 gate, tracked after |
| Manual answer latency (question end -> first audio) | p50 <= 3.5 s, p90 <= 6 s | Phase 3 |
| Replay start latency | <= 700 ms | Phase 1 |
| STT word error rate on buds audio | measure; target <= 15 % in quiet room | Phase 1 |
| Hint usefulness (thumbs up / (up + dismissed)) | >= 60 % | Phase 4 |
| Hints per hour | <= 12 | Phase 4 |
| Wrong-person attribution in answers | <= 5 % | Phase 3 |
| Forget completeness (post-delete scan finds no residue) | 100 % | Phase 5 |
| Weekly active days / self-rated trust | track after dogfooding (>= 4 days/week) | after Phase 4 |

## 11. Risks and fallbacks

| Risk | Impact | Mitigation / fallback |
|---|---|---|
| Buds mics hear other people poorly / too noisy for speaker-ID | Core idea weak | Phase 0 measures it; fallback capture = Mac mic (room) with buds for output, or a phone/lapel source later; accept "wearer + near person" scope |
| Call-mode audio (<=16 kHz, flip delay, battery drain) | Quality/comfort | Sticky session, Conversation as an explicit mode with timeout, battery warning, optional Mac-mic capture |
| Auto mode annoying or wrong | Users turn it off | Policy gating, feedback loop, ship after manual+replay are solid, hint log review |
| Legal/ethical exposure (recording, voiceprints) | Serious | Consent attestations, local-only, per-person opt-in, visibility cues, delete/export, clear UI warnings; user owns the legal call (open question) |
| Local LLM too slow/unreliable | Latency, hallucination | 4B default, short outputs, retrieval-grounded prompts with sources, RuleAgent fallback, cloud opt-in text-only |
| English-only models vs multilingual speech | Misses real conversations | Open question; Whisper multilingual + multilingual TTS as a configuration, benchmark early |
| Buds allow one control client | Conflicts with phone | Documented; app owns the channel while running, cleans up on exit (fixed earlier) |
| Speaker drift / similar voices | Wrong labels | Confidence thresholds, correction by voice, conservative adaptation, "unsure" answers |

## 12. Phasing (each phase ends in a demo and a go/no-go)

| Phase | Deliverable | Gate |
|---|---|---|
| **0. Audio reality check** (days) | Measurement kit: record a second speaker at 0.5/1/2 m via buds vs Mac mic; build speaker-ID benchmark (>= 3 enrolled, >= 3 strangers); measure STT WER, taps-while-mic-open, CPU/thermal/battery over 30 min | Decide capture source and whether the 90 % target is reachable |
| **1. Conversation mode + replay** | Capture sources, RAM ring buffer, rolling STT, replay gesture, catch-up summary, ambient auto, Private mode, simulator | Replay <= 700 ms; STT usable |
| **2. Identity** | Speaker model, enrolment (guided + retroactive + correction), labelled transcripts, "who is talking?", consent log | Accuracy gate met |
| **3. Memory + brain (manual mode)** | SQLite + embeddings, fact extraction, Ollama brain, identity-aware Q&A, dossier, commitments query | Latency + attribution targets |
| **4. Auto mode** | Policy engine, identity cue, question detection, hint feedback, rate limits, audit of hints | Usefulness >= 60 % on dogfood |
| **5. Archive, dashboard, hardening** | Per-person archive/retention, export/forget, encryption, dashboard (people, timeline, search) | Forget completeness 100 % |
| **Later** | Commitment reminders, local-docs RAG, translation, calendar, phone capture, coaching | Per demand |

Rough sizing (one developer with this assistant): Phase 0 ~ 3-4 days, 1 ~ 1 week, 2 ~ 1-1.5 weeks, 3 ~ 1.5 weeks, 4 ~ 1.5 weeks, 5 ~ 1.5 weeks; Phase 0 results may reorder everything after it.

## 13. Testing and evaluation
- **Unit:** gestures, ring buffer bounds, VAD, policy gating, retention/forget, command allowlist (unchanged).
- **Simulated conversations:** scripted multi-speaker WAV fixtures with ground-truth speaker and trigger labels drive speaker-ID, STT, policy and brain tests end to end; the same fixtures run as a regression suite.
- **Real-hardware checklist (manual):** per phase, a short protocol recorded with the buds, results appended to `docs/`.
- **Evaluation harness:** per-metric reports (accuracy, latency histograms, hint precision) written after every run; no feature is "done" without its metric.
- **Privacy tests:** automated check that Private mode buffers nothing, unknown speakers leave no rows, and `forget` leaves no residue (DB, vectors, audio files, logs).

## 14. Open questions

| # | Question | Owner | Blocking? |
|---|---|---|---|
| 1 | Which languages are your conversations in? (current Whisper model is English-only) | You | Yes (STT/TTS model choice) |
| 2 | Legal context: which jurisdiction, and what consent practice will you follow for enrolling/recording others? | You (legal) | Yes, before any Archive/enrolment with real people |
| 3 | Typical settings: 1-on-1, small meetings, noisy places? Distance to the other person? | You | Yes (Phase 0 test plan) |
| 4 | Is it acceptable to use the Mac's mic or a second device as a room mic if the buds mics are weak? | You | After Phase 0 |
| 5 | Preferred brain for hard queries: always local (9B/12B), or optional cloud for text-only queries? | You | No |
| 6 | Speaker model choice (ECAPA vs ONNX WeSpeaker/3D-Speaker) given install weight on this Mac | Engineering | Phase 0 |
| 7 | Encryption approach (SQLCipher vs file-level AES + Keychain) | Engineering | Before Phase 5 |
| 8 | How should "unknown person talks to you" behave by default: ignore, or ask to name after the conversation? | You | No (default: ask after, store nothing) |
| 9 | Acceptable battery/comfort impact of an always-open mic in call mode | You | After Phase 0 |

## 15. Immediate next steps
1. Answer open questions 1-4 (a few lines is enough).
2. Build the **Phase 0 measurement kit** inside `lab/` (multi-speaker capture + metrics), run it with a volunteer, and record results in `docs/validation/phase0.md`.
3. Based on that gate, start Phase 1 in `assistant/` with the capture abstraction and ring buffer.

---

## Addendum v1.1 (2026-10-01): decisions after review

1. **Languages.** Conversations are **English**. **Translation English <-> Telugu is in v1**, via local `gemma4:12b-mlx`
   (verified: correct en->te; te->en fine on every local model tried) and the macOS Telugu voice *Geeta*.
   **Measured limit:** Telugu *speech recognition* is not usable locally (Whisper small/medium produce garbage, medium takes
   ~107 s per 6 s clip; Apple Speech has no `te-IN`). So v1 supports English speech -> Telugu text/speech, and Telugu text -> English;
   Telugu speech input is an experimental backend, with a fine-tuned-model attempt as a time-boxed stretch.
2. **Remote mode.** The buds also work as a **remote control out of the ears** (both buds out -> *remote* placement): touch
   gestures start/stop capture, mark moments, ask, replay; capture then comes from the Mac mic and audio output goes to the Mac
   speakers. Gesture profiles `ear` and `remote` are selected automatically from wear state.
3. **Dashboard** is part of v1 (live transcript with speaker colours, people/enrolment, conversations, memory search/ask,
   translation, settings, privacy/audit).
4. **Speaker model chosen:** WeSpeaker ResNet34 (ONNX via sherpa-onnx): same-voice cosine 0.85-0.94 vs <= 0.57 for different (synthetic) voices.
   Real-human accuracy still has to be measured (Phase 0 kit).
5. Implementation plan: `docs/plans/2026-10-01-sidekick-v1.md`.

## Implementation status (2026-10-01)

Built and tested in `assistant/` (see its README for the verified / not-verified list): replay ring buffer, streaming segmenter,
speaker identity with enrolment/unknown clusters/naming/correction, per-person keep policy and verified forget, memory + RAG
with facts/commitments/dossier, manual and auto modes (policy engine), ear/remote placement with separate gesture profiles,
English <-> Telugu translation, Telugu speech recognition with an interpreter mode, dashboard, Phase-0 measurement kit.

**Updated finding (supersedes item 1 above):** stock Whisper small/medium cannot transcribe Telugu, but a Telugu-tuned CTranslate2
Whisper (`ukta-app/whisper-telugu-ct2`) transcribed a clean synthetic Telugu clip correctly in ~2 s. Real Telugu speech is untested.

**Not done / still to validate:** speaker accuracy on real people (Phase-0 gate), buds-mic capture of other people, live-hardware
checks of gesture/placement switching, encryption at rest, calendar/local-docs RAG, phone capture.
