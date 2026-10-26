# Phase 0 (v2): diagnosis and hardware checklist

## Autopilot diagnosis (code-verified, from `buds_assistant/policy.py`, `modes.py`, `sidekick_gestures.yaml`)
1. **Unknown or unnamed voices can never produce a hint.** `Policy.on_segment` returns `None` when `person_id is None`; a new user has nobody enrolled, so every trigger is dead.
2. **Every trigger needs stored data.** Identity needs a known person, commitment reminders need stored commitments, question answers need a memory hit of score >= 0.35. Nothing captures the wearer's *own* new commitments.
3. **Enabling Autopilot in the ear profile was a two-step sequence** (`R:single` then `L:single`, within 0.7 s) that collides with the `mark` sequence (`L:single`, `R:single`).
4. **Suppressed candidates left no trace** (`_allowed` returned False silently), so silence could not be told apart from breakage.
5. Not yet checked (needs hardware): the buds mic hearing other people clearly; the mode switch completing on real buds.

Fixes: single-slot gesture (Task 1), decision log with reasons (Task 9), commitment capture needing no history (Task 9).

## Needs hardware (run in parallel, does not block Phase 1)
1. Do single/double/triple taps reach macOS as media keys? Pair the buds, run the lab Layer A, tap, record yes/no.
2. Mic comparison: someone speaks at 1 m; record via buds mic and Mac mic with `assistant/buds_assistant/eval/capture_kit.py`; compare with `speaker_bench`.
3. Speaker accuracy with 3+ real people (`docs/validation/phase0.md`).
4. Real Telugu: 3 speakers x 20 sentences; word error rate and a meaning-preserved rating.
5. Hold remap: in the lab, set the touchpad option, confirm the hold no longer toggles noise mode, confirm restore.

## Results
| Check | Result | Date |
|---|---|---|
| Baseline test suite | 99 passed, 3 slow deselected | 2026-10-02 |
| Simulator run (`--simulate --silent`, demo conversation, Autopilot on) | whispers "Ravi." (identity) and "Noted: check it, Friday" (capture); `ui_state` feed filled with 2 decisions; models chat/embed ready | 2026-10-02 |
| Scripted 10-minute conversation gate | with memory: 8 whispers, 100 % on-label, rate within limits; cold start (only "Me" enrolled): 3 captures | 2026-10-02 |
| Bug found only by the simulator run | the engine was built without the event bus, so decisions never reached the UI feed (fixed + test) | 2026-10-02 |
