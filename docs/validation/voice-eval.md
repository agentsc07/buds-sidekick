# Voice recognition evaluation (2026-10-04)

## What was measured and how
- `assistant/buds_assistant/eval/voice_bench.py`: 12 macOS voices x 8 sentences. Each voice is enrolled from 3 clean clips (optionally also
  3 "buds-like" clips: 300-3400 Hz band-limit, noise at 22 dB SNR, lower level) and tested on buds-like clips of other sentences against
  every enrolled voice. EER = point where false accepts equal false rejects. **Synthetic voices are a floor, not real people.**
- The user's own stored enrolment embeddings (real data) were analysed offline: two recording groups matched each other at 0.80-0.96
  inside a group but only 0.38-0.65 across groups, so one mean voiceprint matched neither (spec section 1).

## Results (EER, lower is better)
| Model | enrol clean only: centroid / top-3 | enrol clean + buds: centroid / top-3 |
|---|---|---|
| WeSpeaker ResNet34 (old default) | 0.293 / 0.291 | 0.138 / 0.071 |
| WeSpeaker ResNet293 | 0.426 / 0.425 | 0.227 / 0.093 |
| 3D-Speaker CAM++ (en, VoxCeleb) | 0.327 / 0.341 | 0.331 / 0.288 |
| **NeMo TitaNet-small (new default)** | **0.120 / 0.124** | **0.017 / 0.020** |

Top-3 scoring on mixed-condition enrolment halves the ResNet34 error (0.138 -> 0.071). TitaNet-small is a further ~6x better
(0.071 -> 0.011 in a longer run), 3x faster (0.035 s vs 0.10 s per clip) and spreads voices out: mean score of a *different* voice
is 0.36 (ResNet34: 0.67), which is why ResNet34 mixed people up while TitaNet should not.
Decision rule from the spec (>= 15% relative EER win): TitaNet-small adopted; ResNet34 files stay on disk and old samples stay in the database
(switch back with `speaker_model`); people enrolled with ResNet34 are asked to record again (20 s).

## Not measured (needs the user)
Real people on the real buds mic. Voice health (People > your voice) reports per-microphone sample counts, own-score range and the
nearest stranger it has heard; "Check recognition" in Setup places the threshold from real held-out speech.
