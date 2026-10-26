# Phase 0: audio reality check (fill in with real people)

Goal: find out whether the buds' microphones hear *other people* well enough for speaker identification, and which
capture source to use. Gate: >= 90 % segment accuracy (clips >= 2 s) with <= 5 % stranger false-accepts.

## Run
```bash
cd assistant
../.venv/bin/python -m buds_assistant.eval.capture_kit --out data/phase0_buds --speakers Alice,Bob --strangers Carol --distances 0.5m,1m,2m --input buds
../.venv/bin/python -m buds_assistant.eval.capture_kit --out data/phase0_mac  --speakers Alice,Bob --strangers Carol --distances 0.5m,1m,2m --input mac
../.venv/bin/python -m buds_assistant.eval.speaker_bench data/phase0_buds
../.venv/bin/python -m buds_assistant.eval.speaker_bench data/phase0_mac
```
Only record people who agreed. Wear the buds yourself; the other person talks at the stated distance.

## Results (to fill in)
| Source | Distance | Accuracy | Stranger false-accept | Notes |
|---|---|---|---|---|
| buds mic | 0.5 m | | | |
| buds mic | 1 m | | | |
| Mac mic | 1 m | | | |

Synthetic baseline (macOS voices, no noise): same voice cos 0.85-0.94, different <= 0.57; real-voice results are the point of this phase.
