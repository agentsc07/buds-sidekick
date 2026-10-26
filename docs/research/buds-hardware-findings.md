# Galaxy Buds FE as a remote control + voice interface: what we have learned and built

## Goal
Use Samsung Galaxy Buds FE (SM-R400) earbuds to control a personal assistant remotely: gestures on the buds trigger
actions, the buds' mic captures speech, answers are spoken back into the buds. Host: a MacBook (macOS).

## Verified facts about the hardware (tested on the real buds)
- **Control channel:** the buds expose Samsung's binary protocol over Bluetooth Classic RFCOMM (custom SPP service
  `2e73a4ad-...`, channel 27, "GEARMANAGER"). Only ONE client at a time (a phone or Galaxy Wearable blocks it). Frames:
  `0xFD | header | msg id | payload | CRC16 | 0xDD`. No handshake needed: the buds stream data as soon as it opens.
- **Touch events are available with side and gesture** (message 45): left/right x single, double, triple, hold.
  A continuous hold arrives as a burst of repeated on/off events, so a hold has to be debounced into one toggle.
- **State pushed automatically (message 97):** battery left/right AND case (case % is reported separately), wear state
  per bud (in ear / out / in case), charging flags, noise-control mode (off / ANC / ambient), touchpad lock and
  per-gesture enables, touch-and-hold mapping, EQ, ambient level. Updates arrive on change.
- **Commands work** (acked in ~40-80 ms): noise mode, equalizer, touchpad mapping, touchpad lock, ambient level,
  find-my-earbuds (loud). Time sync got no response. Nothing else was tried by design (no firmware/reset/debug).
- **Lots of undecoded telemetry** (debug events, usage and metering reports). Kept, not understood.
- **No motion sensors** (no accelerometer/gyroscope). Sensors: proximity/wear, touch, case Hall sensor.
- **Microphone:** 3 mics per bud, but audio arrives over the standard Bluetooth headset profile (HFP), mono, up to
  16 kHz. When the mic opens, macOS flips the buds from music mode to call mode (audible dip/delay), and back after.
  Mic audio quality/SNR numbers from the real buds have NOT been measured yet (a level-test tool exists).
- macOS only sees the buds' mic when they act as a headset; AVRCP media keys did not show up in our tests.

## What was built (two folders)
1. **`lab/`: experimentation.** Python/FastAPI local dashboard (offline). Decodes the protocol, live signal table,
   guided experiments, command panel (read-only by default, strict allowlist), mic recorder with quality metrics
   (sample rate, bandwidth, noise floor, SNR), protocol/unknown-message log, exportable capability matrix.
2. **`assistant/`: the actual project.** Gesture -> chime -> listen -> speech-to-text -> agent -> text-to-speech.
   - Speech-to-text: local Whisper (faster-whisper, base.en). Text-to-speech: macOS `say`. Fully offline.
   - Agent: **rule-based dummy** (time, date, battery, arithmetic, notes, jokes, greetings; says honestly when
     something needs the internet). Swappable behind `respond(text, ctx) -> Reply`.
   - Gestures configurable in `gestures.yaml`: double-tap left = ask (stops when you stop talking); hold left = start
     listening, hold left again = stop; hold right = dictate note (toggle); double-tap right = repeat; triple-tap
     left/right = battery/stop; tap left then right = time. New request interrupts current speech (barge-in).
   - Sticky mic session (mic stays open ~20 s so follow-ups avoid the mode flip), soft chimes instead of beeps.
   - Every exchange logged with timings (record / STT / agent); notes saved locally.
   - Tested: gesture logic, VAD, agent rules, pipeline with fakes, real say->Whisper->agent round trip.
     Works end to end with the real buds (user-confirmed). Latency numbers and mic quality not yet analysed.

## Sample usage (works today)
- Double-tap left, hear a chime, say "what time is it" -> spoken answer in the buds.
- Hold left, dictate a long question, hold left again -> answer. Hold right: "note buy milk" -> saved; "read my notes".
- Triple-tap left: spoken battery levels for left, right and case. Double-tap right: repeat last answer.
- Ask "what is the current petrol price" -> honest "I cannot look that up yet" (needs a real model with web search).

## Known limitations / open issues
- Buds keep their own default gesture actions (e.g. touch-and-hold toggles noise mode) unless remapped/locked.
- Call-mode audio quality while the mic is open (both recording and spoken answers inside the sticky window).
- Cloud vs local model not yet chosen; the brain is a dummy.
- Speaker recognition ("who is talking", name registration) is only an idea; depends on real mic quality.
- Buds allow one control client; a phone must be disconnected from them.

## Ideas discussed (not built)
Real LLM agent with web search (spoken-style short answers); voice notes with tap-marked moments; recording around a
gesture and later naming the speaker (enrollment + speaker embeddings, consent/privacy issues); context rules from
wear/case state (take one bud out = pause); gesture macros and spoken menus; meeting mode with summaries; rewind
("what did they just say?", needs an always-open mic); live translation; using taps as a remote for Mac/home devices.

## Questions for a better use case
Which single workflow would be most valuable hands-free (Q&A, capture, control, meetings)? Is the bud a trigger only,
or a full voice interface? How much delay is acceptable from question to answer? Local/private vs cloud brain?
