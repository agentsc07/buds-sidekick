# Documentation and code map

## Start here
| I want to... | Read |
|---|---|
| understand the whole system | [architecture.md](architecture.md) (diagrams, flows, data model, models) |
| know what each screen and switch does | [app-map.md](app-map.md) |
| know the product goals | [specs/product-spec.md](specs/product-spec.md) |
| run it | [../assistant/README.md](../assistant/README.md) (`assistant/run.sh`) |
| understand the earbuds' protocol | [research/buds-hardware-findings.md](research/buds-hardware-findings.md), [../lab/README.md](../lab/README.md) |

## docs/
| Folder | Contents |
|---|---|
| `specs/` | What we decided to build: `product-spec.md` (v1), `spec-v2.md` (modes, Autopilot, dashboard), `spec-v3-voice.md` (voice recognition), `spec-v3-ux.md` (UI, controls, assistant voice), `spec-v3-latency.md` (where the time goes, what we tried) |
| `plans/` | Implementation plans that followed the specs, dated |
| `validation/` | How we checked it: `voice-eval.md` (speaker model and scoring results), `phase0.md` and `phase0-v2.md` (hardware measurement kits), `hardware-checklist-v2.md` |
| `research/` | `buds-hardware-findings.md`: what the Galaxy Buds FE do and do not expose |
| `design/` | `dashboard-acceptance.md` and `screenshots/` from the visual reviews |

## Repository layout
```
BudsFE/
  README.md            overview
  docs/                documentation (above)
  lab/                 earbuds capability lab: protocol decoders, Bluetooth RFCOMM transport, experiments, findings
  assistant/           Buds Sidekick, the product
  .venv/               shared virtualenv (git-ignored)
```

## Code map: where is what (`assistant/buds_assistant/`)
| Package | File | Responsibility |
|---|---|---|
| (top) | `sidekick.py` | Composition root: builds every part, wires events, runs the app (`python -m buds_assistant.sidekick`) |
| | `__main__.py` | Legacy v0 entry point (`python -m buds_assistant`) |
| `core/` | `config.py` | Settings and defaults (`Config`), paths (`HERE`, `CONFIG_DIR`), simulator data dir |
| | `events.py` | In-process event bus; every event has a sequence number (replayed to the dashboard on reconnect) |
| | `store.py` | SQLite: people, voice samples, conversations, segments, facts, hints, decisions, calendar, to-dos, unnamed voices, audit; forget and wipe |
| | `models.py` | Model residency on 16 GB: loads the chat/embedding models, swaps them for the translator, restores |
| | `modes.py` | Operating modes (standby, listen, autopilot, interpreter, private), gesture actions, placement (ear / remote) |
| | `pipeline.py` | Per-utterance work: echo guard, identify, transcribe, store, hand to Autopilot / wake word / interpreter |
| | `uistate.py` | The snapshot the dashboard renders (mode, models, buds, banner, pending mode, busy) |
| `audio/` | `capture.py` | Microphone sources (buds / Mac / file) and the replay ring buffer |
| | `segmenter.py` | Streaming voice-activity segmentation with adaptive noise floor and Interpreter clause splitting |
| | `output.py` | Everything you hear: priorities, routes (buds or Mac), whisper gain, own-voice spans, `say` rendering |
| | `earcons.py`, `mic_check.py`, `listener.py`, `demo.py` | Designed sounds; mic comparison; push-to-ask listener; synthetic conversation audio |
| `speech/` | `speaker.py` | Voice embeddings (TitaNet), kNN scoring, S-norm, turn pooling, clusters, adaptation, assistant own-voice profile |
| | `transcribe.py` | English and Telugu recognisers, language gate, loop/hallucination filters |
| | `translate.py`, `interpreter.py` | English <-> Telugu translation; the live phrase-by-phrase interpreter |
| | `calibrate.py` | "Check recognition": places the match threshold from your own speech |
| `intelligence/` | `llm.py` | Ollama client (chat, embeddings, unload) and a fake for tests |
| | `brain.py`, `agent.py` | Answers: calendar / to-do / reminders intents, retrieval answers, catch-up; rule fallback |
| | `memory.py` | Retrieval over what people said; fact and commitment extraction |
| | `autopilot.py`, `policy.py` | Autopilot rules and gating (alias `policy` kept for older imports) |
| | `judge.py`, `wake.py` | Model judgement for chiming in; "Hey Sidekick" wake word |
| | `personal.py`, `timeparse.py`, `commitments.py` | Your calendar, to-dos, reminders; time phrases; promise detection |
| | `voice_lines.py` | Every line the assistant says about itself (polite, short) |
| `controls/` | `gestures.py`, `touchfilter.py`, `context.py` | Touch tokens -> gestures; accident filter; short-lived contextual gestures |
| | `buttonmap.py`, `bridge.py` | Safe remapping of the buds' hold action; link to the lab's transport |
| `dashboard/` | `server.py`, `api_v2.py` | FastAPI app and the `/api/v2/*` routes, local-only middleware, WebSocket |
| | `web/` | The dashboard: `index.html`, `css/` (tokens, base, components, views, v3), `js/` (main, store, router, `views/`, `components/`, fixtures), vendored Preact |
| | `web_v1/` | The original analysis dashboard (Developer view) |
| `eval/` | `voice_bench.py`, `latency_bench.py`, `speaker_bench.py`, `capture_kit.py` | Benchmarks and measurement kits |
| `legacy/` | `app.py`, `audio_io.py`, `stt.py`, `tts.py` | The v0 gesture-only assistant |

## Tests (`assistant/tests/`)
`core/` store, modes, models, pipeline, UI state, review fixes, answer hygiene · `audio/` capture, earcons, output, segmenter, VAD, latency trims ·
`speech/` speaker, voice quality and v3, unnamed voices, assistant/rename, transcription, Telugu, translation, interpreter ·
`intelligence/` brain, memory, Autopilot (rules, delivery, script), proactive, judge, wake, voice lines, timeparse, personal ·
`controls/` gestures, gesture map, touch filter, context, button map · `dashboard/` API, setup API, dashboard tasks, browser self-test ·
`e2e/` whole-pipeline and evaluation tests · `support/` shared helpers. Run: `cd assistant && ../.venv/bin/python -m pytest -m "not slow"`.
