# Buds FE Capability Lab: Project Spec

## 1. Goal

Build a small local web dashboard that helps me discover and verify **every signal and command** my Samsung Galaxy Buds FE (SM-R400) can produce or accept.

Core loop:

1. The dashboard shows a **guided action** ("Double-tap the LEFT bud").
2. I perform it physically.
3. The dashboard captures the resulting signal (decoded event or raw bytes), shows it live on graphs and logs, and marks the capability **Verified / Not observed / Partial**.
4. At the end I get an exported **capability matrix** (JSON + Markdown) describing what the FE actually exposes.

This is a discovery tool first. Controlling things (using the buds as a controller) comes later, so keep the event layer clean and reusable.

## 2. Known facts about the hardware (starting assumptions, verify all of them)

- Bluetooth 5.2, codecs AAC / SBC / Samsung SSC, profiles HFP, A2DP, AVRCP.
- Sensors: proximity, touch, Hall. **No accelerometer or gyroscope.** Do not build head-tracking or gesture features. If the app happens to observe any motion data, record it, but do not expect any.
- 3 mics per bud, ANC + ambient sound, touch pads (single / double / triple / touch-and-hold, configurable in Galaxy Wearable).
- Battery: buds and case (case battery may or may not be reported separately; find out).
- Galaxy Buds expose a proprietary binary protocol over **Bluetooth Classic RFCOMM (SPP)**, alongside standard A2DP/AVRCP/HFP.
- The FE protocol is **not documented**. Community work covers Buds+/Live/Pro/2. Treat the FE as "probably similar to the Buds2 family" and confirm empirically.

## 3. Signal sources (three layers)

The app must ingest and label events from all three layers so I can tell where each capability lives.

### Layer A: Standard Bluetooth (works without reverse engineering)
- Connection / disconnection events (OS-level).
- AVRCP media keys received by the host (play/pause, next, previous, volume up/down) triggered by taps and holds.
- A2DP: active codec, streaming state (started/suspended).
- HFP: call answer/end, voice-assistant trigger, mic stream availability, HFP battery indicator if exposed.
- Implementation options: on Linux use BlueZ via D-Bus (`dbus-next` / `pydbus`) plus `evdev` or MPRIS for media keys; on Windows use OS media-key hooks. Pick whichever platform I am on (see section 9).

### Layer B: Samsung RFCOMM protocol (main source of rich signals)
- Open an RFCOMM socket to the buds' SPP channel, parse frames, log every message (direction, timestamp, message ID, payload hex, decoded fields).
- Expected message families (from community projects for other Buds models; **confirm which the FE actually emits or accepts**):
  - Status update / extended status update (battery L/R, case battery, wear state, placement, connection info, ANC/ambient state, touchpad lock, etc.)
  - Touch events and touchpad tap action
  - Version info (firmware, hardware)
  - Debug data / debug info, serial number, sensor/diagnostic reports
  - Noise-control state changes
  - Voice-wakeup listening updates (likely irrelevant on the FE; record if seen)
- Expected commands (each must be tested individually and marked supported or not):
  - Set noise control mode (ANC on / off / ambient), ambient level if any
  - Set equalizer preset
  - Set touchpad option (per-side action mapping) and lock/unlock touchpad
  - Adjust sound balance / mute a bud
  - Find My Earbuds (start/stop; **warn me first, it plays a loud sound**)
  - Update time, prepare notification TTS (only if the FE accepts them)
- Reference material (read these, do not copy blindly):
  - `timschneeb/GalaxyBudsClient` (protocol notes: `GalaxyBudsRFCommProtocol.md`, `Galaxy Buds Plus RFComm Protocol Notes.md`). License is GPL-3.0, so implement independently from the documented protocol, or keep my project GPL-3.0 if code is adapted.
  - `JojiiOfficial/GalaxyBuds-rs` (message/command lists).
  - `mpxc/galaxy-buds-plus` (simple Perl interface, useful as a minimal reference for the SPP connection).

### Layer C: Raw discovery
- Capture **all** RFCOMM traffic as raw hex even when it can't be decoded.
- Keep an "Unknown messages" table: message ID, count, first/last seen, example payloads, and which guided action was active when it appeared. Correlating unknown IDs to actions is how I find undocumented FE capabilities.
- Optionally log which SDP services/UUIDs the buds advertise (helps discover other channels or BLE/GATT services). Also try a BLE scan and record whether the buds advertise anything useful.

## 4. Guided experiments (the "action catalog")

Store the catalog as data (`experiments.yaml`), not hardcoded, so I can add entries. Each experiment has: `id`, `title`, `instruction` (what I physically do), `expected_signals` (which events would confirm it), `timeout_seconds` (default 15), `category`, `risk` (safe / audible / changes-settings).

Categories and starting experiments:

**Touch**
- Single tap L / R, double tap L / R, triple tap L / R, touch-and-hold L / R
- Tap while music is playing vs. paused vs. in a call (behavior can differ)
- Swipe attempt on pad (expect no signal; record if any)
- Touchpad locked via command, then tap L / R (expect suppression)

**Wear / placement / proximity**
- Remove left bud, reinsert; remove right bud, reinsert; remove both, reinsert both
- Cover the proximity sensor with a finger without wearing
- Put a bud in the case and close the lid, then open the lid (Hall sensor)
- Take only one bud out of the case

**Case / charging / battery**
- Open case, close case, plug USB-C in, unplug
- Record battery values at each step; record how often battery is reported (periodic vs on-change)

**Noise control**
- Set ANC on, ambient on, off via command; observe the state event
- Change mode via touch-and-hold action (if mapped) and observe the event

**Audio state**
- Start / pause music on host; observe A2DP stream state
- Trigger codec change if possible; log negotiated codec
- Place / receive a call (optional); observe HFP events and mic stream

**Commands (safe / changes-settings)**
- Each supported command in section 3B, one at a time, with an "undo" step where relevant
- For every command record: acked / rejected / no response, round-trip latency

**Discovery**
- "Do something unlisted" free-form mode: I describe what I did in a text box, and the app tags all traffic in a time window with my note

Result states per experiment: `VERIFIED` (expected signal seen), `PARTIAL` (some signal but not the expected one), `UNKNOWN_SIGNAL` (traffic seen but undecoded, saved for analysis), `NOT_OBSERVED`, `SKIPPED`.

## 5. Dashboard

Single-page local web app. Keep it simple and readable, not flashy.

### Views
1. **Live**: connection status, current guided action card with countdown, live signal feed.
2. **Metrics**: graphs (below).
3. **Experiments**: catalog, per-experiment status, re-run buttons, notes.
4. **Protocol**: raw traffic log (filterable by direction, layer, message ID), unknown-messages table, message ID frequency.
5. **Commands**: manual send panel with an allowlist, shows response and latency.
6. **Report**: capability matrix preview and export buttons.

### Graphs / metrics
- Battery over time: left, right, case (line chart). Mark events on the time axis (insert, remove, charge).
- Event timeline: swimlane chart, one lane per signal type (touch, wear, case, ANC, audio, battery, unknown), each event a marker.
- Wear-state strip: L/R in-ear vs out over time.
- Message rate: messages per second (RFCOMM rx/tx) as a line chart, plus stacked bars by message ID.
- Command latency: histogram / scatter of round-trip times per command.
- Touch event heatmap or counters: counts per gesture per side.
- Counters: total events, unique message IDs, verified vs total experiments (progress bar).
- Everything time-aligned to one shared clock. Show times relative to the start of the session.

### Interaction
- The "current action" card gives the instruction, a countdown, and shows the detected signal the moment it arrives (with a sound or flash on the page so I notice without watching).
- Buttons: Start guided run (all or by category), Skip, Retry, Mark as verified manually, Add note.
- Auto-advance to the next experiment after success, with a short pause I can extend.

## 6. Architecture

- **Backend**: Python 3.11+. FastAPI + WebSocket for live events. Async throughout.
  - `transport/rfcomm.py`: connection management (connect, reconnect, timeout, clean shutdown). Use `PyBluez` or stdlib `socket.AF_BLUETOOTH` / `BTPROTO_RFCOMM` on Linux. Isolate platform specifics behind an interface.
  - `transport/standard.py`: Layer A sources (connection, media keys, A2DP/HFP state).
  - `protocol/frames.py`: framing, CRC (check the reference notes; the format is likely SOF, length, message ID, payload, CRC16, EOF), encode and decode.
  - `protocol/messages.py`: message ID registry with decoders. Unknown IDs decode to raw payloads without crashing.
  - `core/events.py`: normalized event model: `{ts, layer, source, type, side, data, raw_hex}`.
  - `core/experiments.py`: runner that arms an experiment, watches the event stream against `expected_signals`, and records results.
  - `core/store.py`: SQLite (events, experiments, notes, sessions) + JSONL raw capture per session.
  - `api/`: REST for catalog/results/commands/export, WebSocket for the live feed.
- **Frontend**: plain HTML + JS (or Vite/React, minimal) with Chart.js or uPlot. No heavy framework required. Must work offline (bundle libraries locally).
- **Packaging**: `README.md`, `requirements.txt` or `pyproject.toml`, single command to run (`python -m budslab`), dashboard on `http://localhost:8765`.
- **Simulator mode**: a fake transport that replays a recorded JSONL session or generates synthetic events, so the dashboard can be built and tested without the buds connected.

## 7. Safety and constraints

- **Read-only by default.** Sending commands requires an explicit toggle in the Commands view.
- Command **allowlist**: only settings-type commands (noise control, EQ, touchpad options/lock, balance, find-my-earbuds with a confirmation, time sync). 
- **Never implement or send**: firmware update/flashing/downgrade, bonding-key or pairing-key dumping, factory reset, hidden debug-mode toggles, or any message not on the allowlist. These are out of scope and can brick the buds.
- Unknown-message experiments are **listen-only**. Do not fuzz or replay arbitrary payloads to the buds.
- Warn before anything loud (Find My Earbuds) and tell me to remove the buds from my ears.
- Log everything locally only. No network calls, no telemetry.

## 8. Deliverables

1. Working app per sections 3-6, with simulator mode.
2. `experiments.yaml` containing the catalog from section 4.
3. `docs/protocol-findings.md` auto-appended/generated from sessions: message IDs seen, decoded fields, confidence level per message (Confirmed / Likely / Unknown).
4. Export: `capabilities.json` and `capabilities.md`, a matrix of capability, layer, how to trigger it, signal seen (message ID / event type), reliability (X of Y attempts), and notes.
5. `README.md` with setup, pairing steps, and troubleshooting (see section 9).
6. Tests for frame encode/decode (using known frames from the reference notes) and for the experiment runner (using the simulator).

## 9. Environment and open questions for Claude Code to resolve first

Before writing code, do these in order and report back:

1. **Ask me** which OS the buds will be connected to (Linux, Windows, macOS) and whether an Android phone is involved. RFCOMM access differs a lot (BlueZ on Linux is easiest; Windows needs a compatible PyBluez or WinRT approach; macOS uses IOBluetooth).
2. Read the reference protocol notes above and produce a short summary of the frame format and the message IDs relevant to the FE-class devices (Buds2 family), noting what is uncertain.
3. Build a **minimal probe script** first: connect RFCOMM, print raw frames for 60 seconds while I tap and wear/remove the buds. Confirm the FE responds on the same SPP channel and framing as the reference. If not, adapt before building the dashboard.
4. Then build the dashboard on top of the verified transport.

Known practical issues to handle:
- The Galaxy Wearable app or the phone may hold the RFCOMM connection; document how to disconnect it (buds pair to one active client at a time for this channel).
- Reconnect logic when buds go into the case or out of range.
- Some messages arrive only after a handshake or after a "register/subscribe"-style message; check the reference notes for any required init sequence.

## 10. Acceptance criteria

- With the buds connected, I can run the guided flow and see each physical action produce a visible signal within the dashboard, or a clear "not observed" result.
- Battery, wear state, and touch events show on live graphs with correct timing.
- Unknown traffic is preserved and correlated to the action that was active.
- The exported capability matrix is accurate enough that I can pick "controller" project ideas directly from it (for example: which touch gestures arrive as distinct events, whether wear/case events exist, latency).
- The app runs fully in simulator mode with no hardware.
- No command outside the allowlist can be sent.