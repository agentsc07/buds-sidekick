# Buds Sidekick

A voice-aware personal assistant in your ear (Galaxy Buds FE + MacBook). It listens to conversations, knows who is
speaking, remembers what each person said, answers your questions, whispers guidance, replays what you missed, and
translates English <-> Telugu. All local: speech recognition, speaker identity, memory and language models run on this Mac.

Install and run: see `../startup.md`. Docs: `../docs/README.md`.

## Run

```bash
cd assistant
../.venv/bin/python -m buds_assistant.sidekick --simulate          # no buds: dashboard drives gestures/wear (http://127.0.0.1:8770)
../.venv/bin/python -m buds_assistant.sidekick                     # real buds (stop the lab first: one control client at a time)
../.venv/bin/python -m buds_assistant.sidekick --simulate --silent # never plays sound
../.venv/bin/python -m pytest -m "not slow"                        # tests (add `-m slow` for the real-model ones)
```
Needs Ollama running with `qwen3.5:4b-mlx`, `gemma4:12b-mlx` (translation) and `nomic-embed-text`
(`ollama pull ...`). First run downloads Whisper models and (if enabled) the Telugu model. The older gesture-only
assistant is still available as `python -m buds_assistant` (v0).

## What it does

| Mode | What happens |
|---|---|
| **Standby** | Mic closed. Gestures and typed questions work. |
| **Listen** | Mic open: live transcript, speaker labels, rolling replay buffer, "who is talking?", catch-up. Ambient sound is switched on for you (and restored). Never speaks unless asked. |
| **Autopilot** | Listen plus whispered hints: your own promises noted ("Noted: send it, Friday"), a question you can answer from memory, a stored commitment mentioned, a known name briefed, an identity cue. Never for unknown voices, never while someone is mid-sentence. Every whisper *and every silence* is in the decision log (`store.decisions()`, the dashboard's Autopilot feed). Sensitivity `quiet / balanced / proactive` (`autopilot_sensitivity`). |
| **Interpreter** | Translate live (mode and model residency are in; the voice-to-voice pipeline is Phase 5). Uses the Mac mic; pauses Autopilot and gives it back on exit. |
| **Private** | Mic closed, replay buffer wiped, nothing stored. Leaving it always lands in Standby. |

*Ask* is an action (left single tap), not a mode. A memory level (live / remember / recording) applies to Listen, Autopilot and Interpreter.

**Ear vs remote.** Wear state selects the placement automatically. *In ear*: buds mic and buds audio. *Remote* (both buds out): the
buds are a pocket clicker, capture uses the Mac mic and answers play on the Mac speakers, with a different gesture profile
(one tap starts/stops capture, one tap marks, ...). See `config/sidekick_gestures.yaml`.

**Identity.** Enrol a person (consent note required), or name an unknown "Speaker A" during or after a conversation.
Unknown voices are never stored. Correct a wrong label from the transcript; the voice model learns from it. Per-person keep
policy: `none` / `transcript` / `audio` (+ retention days). **Forget** deletes the voiceprint, transcripts, audio, facts and hints.

**Memory.** Retrieval over what each person said (semantic + keyword, recency boost), facts and commitments extracted when a
conversation ends (each linked to its source line), dossier per person, commitments list.

**Translation.** English <-> Telugu through `gemma4:12b` (the only local model that translated English -> Telugu correctly in our test),
Telugu voice *Geeta*. Say "translate to Telugu: ..." or "translate that", or use the Translate tab. **Telugu speech**: turn on
*telugu stt* in Settings (Telugu-tuned Whisper, routed by a fast language gate). With *interpreter* on, Telugu speech is
translated and whispered to you in English. Telugu transcripts are flagged experimental and never stored.

## Dashboard (http://127.0.0.1:8770)
v3 (2026-10-04): five places (Home with a living orb, Day, People with voice health, Controls for gestures and voice commands, Settings with six rows). Specs: `../docs/specs/spec-v3-ux.md`, `../docs/specs/spec-v3-voice.md`; voice evaluation: `../docs/validation/voice-eval.md`.

Home (what Sidekick is doing now, mode cards, Ask bar, live conversation with Sidekick's whispers in the margin and the reason for every
silence), People (saved voices, voices it couldn't name, forget with exact counts), Library (conversations, open promises), Settings
(Autopilot sensitivity, gesture editor with a try-it mode, privacy, delete everything), first-run Setup, and a Developer view (`#/dev`,
and the original dashboard at `/dev/`). Preact + htm are vendored (`dashboard/web/vendor`), so it works offline; no build step.
`?demo=1` renders every screen from fixtures without the backend (`&state=autopilot|listen|interpreter|private|standby|disconnected|ollama-down`,
`&theme=light|dark`). API: `/api/v2/*` (`dashboard/api_v2.py`). Tests: `tests/test_api_v2.py`, `tests/test_setup_api.py`, `tests/test_dashboard_tasks.py`
(every API call in the JavaScript must match a real route; no browser dialogs; every non-developer task works).

## Default gestures (`config/sidekick_gestures.yaml`) - same in the ear and as a remote
| Gesture | Action |
|---|---|
| L single | Ask (speak, stops when you stop) |
| L double | Replay last N s (again within 6 s: catch me up) |
| L triple | Private on/off |
| L hold (toggle) | Interpreter on/off |
| R single | Mark this moment |
| R double | Autopilot on/off |
| R triple | Who is talking |
| R hold (toggle) | Listen on/off |

Contextual (a few seconds only): any single tap while it speaks = stop; within 4 s after a whisper single = "tell me more",
double = "not useful"; within 5 s after "Noted:" double = undo. Anti-accident filter: touches within 1 s of inserting/removing a
bud and bursts of more than 3 taps in 1 s are ignored. Every accepted gesture and mode change has an earcon (`earcons.py`).

The buds keep their own default actions (e.g. single tap = play/pause, hold = noise mode). `button_remap` (off by default) can remap
the hold and always restores the original, also after a crash; enable it only after hardware check #5 in `../docs/validation/phase0-v2.md`.

## Verified, and not yet verified

**Verified by tests and real-model runs on this Mac (no humans, no buds):** frame/gesture logic, ring buffer, segmenter,
speaker enrolment/identification/unknown clusters/retroactive naming with real voices, privacy rules (unknown never stored, forget
leaves no residue incl. the DB file), memory retrieval with real embeddings, fact extraction with the real 4B model, grounded answers,
auto-mode policy, ear/remote switching logic, output arbiter, dashboard API and WebSocket, English<->Telugu translation, Telugu speech
recognition + gate + interpreter through the whole app. Measured warm latency: grounded answer ~1-1.5 s; the first question after
idle can take 10-25 s if models were swapped out (warm-up at start helps; keep heavy models unloaded).

**Not verified yet (needs you):**
- **Speaker accuracy on real people.** Synthetic voices mislead: same-engine voices of similar timbre scored 0.70-0.80 vs a
  0.62 threshold (false accepts) while the same voice scored 0.92. Run the Phase-0 kit (`../docs/validation/phase0.md`) and set the threshold from real data.
- **Buds mic hearing other people**, mic quality and delay, battery impact of an always-open mic.
- **Live buds:** gestures into modes, wear-driven placement switching, the ambient-sound command, remote mode with the Mac mic/speakers.
- **Telugu speech from real people** (only a clean synthetic voice has been tested) and Telugu voice naturalness.
- Encryption at rest is not implemented (file permissions only).

## Layout
```
assistant/
  run.sh                     start the app (real buds); add --simulate for no buds
  requirements.txt  pytest.ini
  buds_assistant/config/     sidekick.yaml (settings), sidekick_gestures.yaml (gestures, edited by the dashboard), gestures.yaml (legacy v0)
  models/                    speaker-model weights (see models/README.md)
  data/  data-sim/           runtime data: SQLite, audio, setup state (git-ignored; simulator uses data-sim)
  buds_assistant/
    sidekick.py              composition root: builds everything, runs the app (python -m buds_assistant.sidekick)
    __main__.py              the legacy v0 entry point (python -m buds_assistant)
    core/                    config, events, store (SQLite), models (memory residency), modes, pipeline (per-utterance), uistate
    audio/                   capture + replay buffer, segmenter (VAD), output (speech arbiter), earcons, mic_check, listener, demo audio
    speech/                  speaker (who), transcribe (what), translate, interpreter, calibrate
    intelligence/            llm client, brain (answers), memory, autopilot (rules), judge (model judgement), wake, personal, timeparse, commitments, voice_lines
    controls/                gestures, touchfilter, context, buttonmap, bridge (to the lab's buds transport)
    dashboard/               FastAPI server + api_v2 + the web app (web/: Preact, no build step; web_v1/: developer view)
    eval/                    benchmarks: voice_bench, latency_bench, speaker_bench, capture_kit
    legacy/                  v0 gesture-only assistant (app, audio_io, stt, tts)
  tests/                     core/ audio/ speech/ intelligence/ controls/ dashboard/ e2e/ support/
```
Data in `data/` (SQLite `sidekick.db`, per-person audio if kept). Full code map: `../docs/README.md`.
