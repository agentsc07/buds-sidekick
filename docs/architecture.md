# Buds Sidekick: architecture, flows and features

A voice-aware personal assistant in your ear (Galaxy Buds FE SM-R400 + a MacBook). Everything runs on the Mac: speech recognition, speaker
identity, memory, language models, the dashboard. Nothing leaves the machine.
Diagrams use Mermaid (they render in VS Code's Markdown preview and on GitHub).

## 1. System context
```mermaid
flowchart LR
  subgraph Ear["In your ear / on your desk"]
    B["Galaxy Buds FE<br/>mic, touch, wear sensors"]
    S["Mac speakers + Mac mic"]
  end
  subgraph Mac["MacBook (all local)"]
    L["lab/budslab<br/>RFCOMM protocol client"]
    A["assistant/buds_assistant<br/>FastAPI app + audio pipeline"]
    O[("Ollama<br/>qwen3.5 4B, nomic-embed, gemma4 12B")]
    D[("SQLite + audio files<br/>assistant/data")]
    W["Dashboard (browser)<br/>http://127.0.0.1:8770"]
  end
  B -- "Bluetooth RFCOMM: taps, wear, battery" --> L --> A
  B -- "HFP/A2DP audio" --> A
  S -- "mic in / speech out" --> A
  A <--> O
  A <--> D
  A <-- "HTTP + WebSocket (local only)" --> W
  P["Your phone"] -. "Bluetooth must be OFF:<br/>the buds accept one control client" .- B
```

## 2. Components
```mermaid
flowchart TB
  subgraph Input
    CAP["capture.py<br/>MicSource + RingBuffer (last seconds)"]
    SEG["segmenter.py<br/>adaptive VAD, soft clause split"]
    GES["gestures / touchfilter / context<br/>taps -> actions"]
  end
  subgraph Understanding
    SPK["speaker.py<br/>TitaNet embeddings, kNN + S-norm,<br/>clusters, assistant own-voice profile"]
    STT["transcribe.py<br/>faster-whisper small.en, tiny gate,<br/>Telugu CT2 small"]
    PIPE["pipeline.py<br/>per-utterance: identify, transcribe, store"]
  end
  subgraph Brain
    BR["brain.py<br/>intents: calendar, to-do, reminders, RAG, translate"]
    MEM["memory.py + store.py<br/>retrieval, facts, commitments"]
    AP["autopilot.py<br/>rules (promises, calendar, meetings)"]
    JU["judge.py<br/>model decides when to chip in"]
    WK["wake.py<br/>'Hey Sidekick, ...'"]
    INT["interpreter.py + translate.py<br/>phrase queue, echo guard"]
    PER["personal.py + timeparse.py<br/>calendar, to-dos, reminders"]
  end
  subgraph Output
    OUT["output.py<br/>arbiter: priorities, routes, own-voice spans"]
    EAR["earcons.py + voice_lines.py"]
  end
  subgraph Control
    MOD["modes.py<br/>standby, listen, autopilot, interpreter, private"]
    MDL["models.py<br/>memory residency (Ollama + Telugu STT)"]
    UI["uistate.py + dashboard/api_v2.py<br/>state pushed over /ws"]
  end
  CAP --> SEG --> PIPE
  PIPE --> SPK
  PIPE --> STT
  PIPE --> AP
  PIPE --> JU
  PIPE --> WK
  PIPE --> INT
  GES --> MOD
  WK --> BR
  JU --> OUT
  AP --> OUT
  BR --> OUT
  INT --> OUT
  BR --> MEM
  BR --> PER
  MOD --> PIPE
  MOD --> MDL
  OUT -. "own-voice spans" .-> PIPE
  PIPE --> UI
  OUT --> UI
```

## 3. One utterance, end to end
```mermaid
sequenceDiagram
  participant Mic
  participant Seg as Segmenter
  participant Pipe as Pipeline worker
  participant Spk as Speaker engine
  participant Stt as Recogniser
  participant Out as Output arbiter
  participant UI as Dashboard
  Mic->>Seg: 20 ms frames
  Seg->>Pipe: segment (speech + pre-roll)
  Pipe->>Out: was this my own voice playing? (>= 60% overlap -> drop)
  Pipe->>Spk: identify (kNN over per-microphone samples, S-norm, turn pooling, cluster naming)
  Note over Pipe,Spk: skipped in one-way Translate
  Pipe->>Stt: transcribe (English small.en, or gate -> Telugu)
  Pipe->>UI: segment event (seq numbered, deduplicated on reconnect)
  Pipe->>Pipe: store per the person's policy (never unknown/Telugu transcripts; never while translating)
  Pipe-->>Out: whisper / answer / translation (priority, route: buds or Mac)
```

## 4. Modes and what the switches mean
```mermaid
stateDiagram-v2
  [*] --> Standby
  Standby --> Listening: Listening on
  Listening --> Standby: Listening off (conversation kept)
  Listening --> Autopilot: Autopilot level > Off
  Autopilot --> Listening: Autopilot Off
  Listening --> Translating: Translate on (loads models, "Getting ready")
  Autopilot --> Translating: Translate on (Autopilot pauses, resumes after)
  Translating --> Listening: Translate off
  Listening --> Private: Go private (wipes last seconds, discards conversation)
  Standby --> Private
  Private --> Standby: End private
```
| Control | Meaning |
|---|---|
| Listening | The mic. Listens, keeps the replay buffer, answers gestures and "Sidekick, ...", saves the conversation. |
| Autopilot (Off / Quiet / Helpful / Proactive) | How much I chip in. Quiet = rules only. Helpful and Proactive add the model's judgement (needs score >= 4 or >= 3 of 5). |
| Translate | Live Telugu <-> English. Saves nothing. Uses the Mac mic. |
| Go private | Panic action, not a mode you live in. |

## 5. Autopilot
```mermaid
flowchart TD
  T["A finished utterance"] --> W{"Starts with 'Sidekick / Autopilot'?"}
  W -- yes --> ASK["Answer like Ask (speak it)"]
  W -- no --> R["Rules: your promise -> to-do, time being arranged -> calendar,<br/>stored promise mentioned, known name, who is this"]
  R -- "fired" --> G
  W -- no --> J["Judge: after a 1.5 s pause, the model reads the last 12 lines,<br/>your day, memories and what it already said"]
  J -- "say / to-do + score >= level" --> G
  J -- "nothing, low score, repeat" --> Q["silence (reason stored)"]
  G{"Gates: category on, gap, hourly budget,<br/>not while someone speaks, not stale"} -- pass --> S["Whisper in the ear + note under the line"]
  G -- fail --> Q
```
Every whisper and every silence has a stored reason (`autopilot_decisions`).

## 6. Interpreter
```mermaid
flowchart LR
  M["Mac mic"] --> SG["Segmenter<br/>(0.45 s end, 2.5 s soft split)"] --> Q["Queue<br/>merge when behind"]
  Q --> GT["Language gate"] --> R1{"Telugu?"}
  R1 -- yes --> TE["Telugu recogniser"]
  R1 -- "no, but English looks weak" --> TE
  R1 -- no --> EN["English recogniser"]
  TE --> TR["gemma4 12B translate"]
  EN --> TR
  TR --> TTS["say render"] --> PL["buds (one-way) or Mac speakers (two-way Telugu)"]
  PL -. "echo guard: do not translate our own speaker" .-> SG
```
Models are swapped to fit 16 GB: entering Translate unloads the chat and embedding models and loads gemma + Telugu STT; leaving restores them.

## 7. Data model (SQLite, `assistant/data/sidekick.db`)
| Table | Holds |
|---|---|
| people | name, consent note, keep policy (none / transcript / audio), kind (person / assistant) |
| voice_samples | per-person voice embeddings with their source (`enrol:buds`, `adapt:laptop`, `cluster`, `assistant`) |
| conversations, segments | transcript lines (known speakers only), language, confidence |
| facts | commitments, dates, preferences extracted when a conversation ends, each linked to its source line |
| hints, autopilot_decisions | every whisper and every silence with its reason |
| events, todos, reminders | your calendar, to-dos (incl. promises), reminders; sample data is flagged |
| unnamed_voices | voices I could not name: pooled voiceprint + <= 6 s clip, kept 7 days |
| bookmarks, audit | marked moments; an audit trail of enrolments, deletions and settings |

## 8. User flows
**First run:** open the dashboard -> Setup (check, connect buds with phone Bluetooth off, mic check, record your voice on each microphone, gestures, privacy, try it).
**Every day:** buds in -> Listening on -> talk. Left tap asks; right double-tap toggles Autopilot; say "Sidekick, ..." any time.
**Unknown person:** People -> "Voices I couldn't name" -> hear the clip -> name them or add to someone you know (or "Not now").
**Translate:** Translate on -> "Getting ready" (about 20 s the first time) -> their Telugu is spoken to you in English; two-way also speaks your English as Telugu on the Mac speakers.
**Privacy:** Go private (discard now); Save this conversation off; People -> Forget (counts shown, type the name); Settings -> Privacy -> keep unnamed voices off / delete everything.
**Something wrong:** the banner says the one thing that matters (voice not set up, Mac busy, buds not connected, model not running).

## 9. Features by place
| Place | Features |
|---|---|
| Home | status orb, Listening / Translate switches, Autopilot level, save toggle, Replay / Mark / Catch up / Go private, live conversation with whispers inline, translation panel, Ask bar |
| Day | calendar, to-dos (with "You promised" tags), reminders, sample-data switch |
| People | voices with health per microphone, Record more, rename, add a voice to someone, mark an entry as the assistant's own voice, unnamed voices from earlier, promises, conversations, forget |
| Controls | both buds with every gesture (editable), try-it, voice commands, sound legend |
| Settings | Voice and microphones, Assistant, Privacy, Appearance, Connection, Advanced (thresholds, models, developer view) |

## 10. Models and memory (16 GB)
| Model | Job | Notes |
|---|---|---|
| NeMo TitaNet-small (ONNX, sherpa-onnx) | speaker embeddings | 192-dim; ~4x fewer errors than WeSpeaker ResNet34 on the voice bench |
| faster-whisper small.en | English speech | tiny multilingual model as the language gate |
| whisper-telugu small (CT2, int8) | Telugu speech | experimental; never stored |
| qwen3.5 4B + nomic-embed | answers, judgement, memory | resident; unloaded while translating |
| gemma4 12B | translation | loaded only for Translate |
| macOS `say` (Samantha / Geeta) | speech output | rendered then played, so gain and route are ours |

## 11. Security and privacy
Local only: the API refuses foreign Origin/Host headers and WebSocket origins. Unknown voices are never stored beyond the short review
window; Telugu transcripts are never stored; Translate saves nothing; Private discards. Forget and Delete everything remove database rows,
audio files, event history and the live feed. Not done: encryption at rest (file permissions only).

## 12. Testing and evaluation
~420 automated tests (fakes for models and audio; a headless-Chrome self-test of the dashboard store). Real-model tools: `eval/voice_bench.py`
(speaker models and scoring on synthetic voices through a simulated microphone change), `eval/latency_bench.py` (Interpreter end to end),
`docs/validation/voice-eval.md`. Specs: `docs/specs/spec-v3-voice.md`, `docs/specs/spec-v3-ux.md`, `docs/specs/spec-v3-latency.md`; map of the screens: `docs/app-map.md`.

## 13. Known limits
Speaker accuracy on real people and Telugu quality on real speakers are not yet measured at scale; Interpreter latency is above target and
very sensitive to how busy the Mac is; one control client per buds (phone Bluetooth off); calendar is local only.
