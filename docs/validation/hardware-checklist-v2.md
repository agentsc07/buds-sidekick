# Hardware checklist, Sidekick v2 (phases 0-2)

Run with the real buds paired to the Mac (phone Bluetooth off). Record results below.

- [ ] Each of the 8 gestures does the right thing, in the ear and with both buds out (remote).
- [ ] Insert / remove a bud: no stray action fires for ~1 s. Shake the buds in a pocket: bursts are ignored.
- [ ] Every mode change plays its earcon and says its short phrase (Listening / Autopilot on / Interpreter / Private / Standby); the sounds are soft and distinct.
- [ ] Autopilot in a real 10-minute conversation with a friend: at least one useful whisper; none while someone is speaking; check `store.decisions()` for the held-back reasons.
- [ ] Double tap right after a whisper = "not useful" (does not toggle Autopilot); single tap after a whisper = tell me more; double after "Noted:" = undo.
- [ ] Interpreter on while Autopilot is on: Autopilot pauses; off again: Autopilot returns.
- [ ] Cold start: first answer after launch is within budget (no 10-25 s stall); `/api/v2/state` models show chat+embed ready.
- [ ] `button_remap: true`: hold no longer toggles noise mode; exit normally and with `kill -9`: the next start restores the original mapping.

## Dashboard v2 on the real buds
- [ ] First launch redirects to Setup; Health shows real Ollama/model state; "Connect" shows the real battery.
- [ ] Mic check with a person 1 m away gives sensible dB values for both mics and a recommendation.
- [ ] "Record 20 seconds" enrols you; Settings > Gestures > Try it shows each real tap and does nothing.
- [ ] Home shows who is talking (avatar pulse) and whispers appear beside the line that triggered them; the thumbs and Undo work.
- [ ] Close the tab while Try it is on: gestures work again within 60 s.
