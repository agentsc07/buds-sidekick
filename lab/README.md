# Buds FE Capability Lab

A local dashboard that walks you through physical actions on a Samsung Galaxy Buds FE (SM-R400), captures every
signal the buds produce, and exports a capability matrix. Discovery tool first; everything stays on your machine
(no network calls, no telemetry, server binds to localhost).

## Quick start

Run from the `lab/` folder (the virtualenv lives one level up in `../.venv`).

```bash
python3 -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt
../.venv/bin/python -m budslab --simulate          # no hardware: try the whole dashboard
../.venv/bin/python -m budslab.probe --seconds 60  # step 1 with real buds: passive raw-frame probe
../.venv/bin/python -m budslab                     # dashboard on http://localhost:8765
../.venv/bin/python -m pytest                      # tests
```

Useful flags: `--device AA:BB:CC:DD:EE:FF`, `--channel N`, `--replay data/sessions/<id>/raw.jsonl`,
`--speed 4` (faster simulator), `--handshake`, `--legacy-framing`.

## Status: what is and is not verified

Tested here: frame codec (against a real Buds FE frame from the reference project), decoders, experiment runner,
command guard, exports, API. All of that runs in the simulator.
**Not tested (no hardware in the build environment):** the IOBluetooth RFCOMM transport, the media-key tap, and the
Linux socket transport. Run the probe first; if it does not show frames with `crc=OK`, fix the transport before
trusting the dashboard. Simulator sessions are labelled `SIMULATOR` and excluded from evidence by default.

## Layers

* **A – standard Bluetooth / OS.** macOS: connection state (IOBluetooth), AVRCP media keys (CGEventTap), audio route
  (system_profiler; 44.1/48 kHz vs 8/16 kHz hints at A2DP vs HFP). macOS exposes **no** A2DP codec/stream state or HFP
  call events to apps, so those experiments will normally report NOT_OBSERVED. Linux/Windows Layer A: not implemented.
* **B – Samsung RFCOMM protocol.** Custom SPP service UUID `2e73a4ad-332d-41fc-90e2-16bef06523f2`.
* **C – raw discovery.** Every frame is stored as hex; undecoded IDs go to the Unknown table with the experiment that
  was armed. SDP records are dumped to `data/sessions/<id>/sdp.json`; BLE scan button in the Protocol view.

## Protocol summary (from timschneeb/GalaxyBudsClient notes; re-implemented independently)

`SOM 0xFD | header LE16 (size in low 10 bits; 0x2000 fragment, 0x1000 type) | msg id | payload | CRC16-XMODEM LE over id+payload | EOM 0xDD`,
where size = 1 + payload + 2. Confirmed on a real FE frame. Relevant IDs: 96 STATUS_UPDATED, 97 EXTENDED_STATUS_UPDATED
(battery L/R/case, placement, touch lock, noise mode…), 119 NOISE_CONTROLS_UPDATE, 145 TOUCH_UPDATED (only lock state),
81 RESP, 66 ACK, 120 NOISE_CONTROLS, 134 EQUALIZER, 144 LOCK_TOUCHPAD, 146 SET_TOUCHPAD_OPTION, 160/161 find my earbuds.
Uncertain: whether the FE reports individual taps over RFCOMM at all (the reference shows only lock state; taps
probably arrive only as AVRCP keys, without left/right), whether a handshake is required (reference client sends none
we could find; `--handshake` sends MANAGER_INFO once), sound balance (no documented message id, so not implemented),
EQ preset encoding and ambient-level range for the FE.

## Pairing and connecting (macOS)

1. Pair the buds in System Settings › Bluetooth (they must be out of the case, in pairing mode the first time).
2. Grant your terminal/IDE **Input Monitoring** (Privacy & Security) so media keys can be seen; restart it.
3. Don't press keyboard media keys during tests; they look identical to bud taps.
4. `python -m budslab` finds a paired "Buds FE" automatically or use `--device`.
5. Phone: the buds keep one active RFCOMM client. If a phone/Galaxy Wearable is connected, turn Bluetooth off on the
   phone (or "Disconnect" the buds there) before connecting from the Mac; `openRFCOMMChannel` errors mean someone else has it.
   To test the phone case, connect the phone last and watch the Unknown/Protocol views for what changes.

## Safety

Read-only by default. The Commands view needs an explicit toggle. Allowlist only: noise control, ambient level, EQ,
touchpad option, touchpad lock (preserves your gesture settings), find-my-earbuds (loud; confirmation and undo/stop
automatic, also on shutdown), mute bud (find-my mode only), time sync. Firmware/FOTA, reset, reboot, key/pairing dumps,
debug/hidden modes and everything else are absent and blocked twice in code (`protocol/commands.py`, `Lab._send_bytes`).
Unknown messages are listen-only; nothing is fuzzed or replayed.

## Workflow

Live › Start guided run. Each experiment shows an instruction, countdown, and flashes/beeps when a signal arrives.
Results: VERIFIED / PARTIAL / UNKNOWN_SIGNAL / NOT_OBSERVED / SKIPPED. Experiments live in `experiments.yaml`
(format documented at the top; "Reload catalog" in the Experiments view). Report › Export writes `capabilities.json`,
`capabilities.md` (under `data/exports/` and the session folder) and regenerates `docs/protocol-findings.md`
(Confirmed = decoded from real hardware traffic; Likely = decoder from reference only; Unknown).
The matrix aggregates attempts across all hardware sessions ("X of Y attempts").

## Troubleshooting

* *No paired Buds FE found* – pair in System Settings, or pass `--device`.
* *SDP: service not found* – check `sdp.json`; try `--channel N`; make sure the buds are connected and nothing else holds the link.
* *Frames with crc=BAD or junk* – try `--legacy-framing`; report the raw hex from the Protocol view.
* *Connected but silent* – try `--handshake`; some models only push status after a manager-info message.
* *Media keys unavailable* – Input Monitoring permission (see above).
* *Buds in the case / out of range* – the transport retries with backoff.

Licence note: message names/IDs and layouts are derived from GPL-3.0 community notes; this project is independent code,
but treat it as GPL-3.0 if you copy anything from that repo.
