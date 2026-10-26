# Spec v3-A: Voice recognition ("is this me, who else, or a stranger?")

Status: written 2026-10-04 after the first real-use sessions. Owner: Sidekick. Scope: `speaker.py`, `pipeline.py`, `calibrate.py`,
enrolment API and setup screens. Out of scope: transcription quality, translation.

## 1. What the real data showed (evidence, not opinion)

1. **One person, two "voices".** The user's 7 stored enrolment embeddings fall into two groups. Inside a group cosine is 0.8-0.96;
   across groups only 0.38-0.65. Group 1 = laptop-mic enrolment, group 2 = a second recording (different mic/room/session).
   The old engine averaged all samples into ONE centroid, which sits between the groups and matches neither well.
2. **Result in use:** the same sentence by the same person came back as "Me" at 0.77-0.82 one minute and as "Speaker A" at
   0.39-0.55 the next (mic switches between the buds in Autopilot and the MacBook mic in Interpreter).
3. The threshold 0.62 was set from synthetic voices; "is you" was 0.80 (fixed to threshold+0.06 on 2026-10-04).
4. Short utterances (1-2 s) carry little speaker information; one-word turns are guesses.

Conclusion: the weakness is not the embedding network first, it is (a) the **enrolment model** (single mean), (b) **channel
mismatch**, (c) **no score normalisation**, (d) **deciding per segment** instead of per turn.

## 2. How others do it (research summary)

- **Multi-enrolment backends:** embedding averaging works only inside one condition; for mixed conditions systems keep several
  enrolment embeddings and score against the best/top-k, or cluster them into per-condition sub-profiles.
- **Score normalisation (S-norm / AS-norm):** score is re-expressed relative to a *cohort* of impostor voices (top-N of them), giving
  roughly 30% relative error reduction and the biggest gain under channel mismatch (VoxCeleb challenge systems, DKU-MSXF 2023,
  SJTU X-LANCE CNSRC 2022).
- **Better embeddings:** CAM++ and ERes2NetV2 (3D-Speaker) beat ECAPA-TDNN and ResNet34 on VoxCeleb (CAM++: ~18% lower EER than ECAPA with
  half the parameters); WeSpeaker ResNet293 is best on raw EER but heavy. All are available as sherpa-onnx ONNX files.
- **Diarisation systems (pyannote/diart):** decide on a rolling window with incremental clustering, and use enrolled voiceprints only as
  *labels for clusters* rather than per-chunk decisions.
- **Voice assistants (Siri/Google "Voice Match"):** enrol with several phrases in different conditions, keep *adapting* the profile with
  high-confidence live audio, and always say "not sure" when unsure.

## 3. Requirements

### R1. Enrolment that survives mic changes
- A person has **sub-profiles per capture source** (`laptop`, `buds`, `other`) plus the pooled samples. Each sample stores its source.
- Score against a person = **mean of the top-3 cosines to that person's samples** (kNN), falling back to the single best when fewer
  than 3. (Mean-centroid is kept only as a tie-break and for the speed of "who is this" over many people.)
- Setup asks for a **20 s recording on each microphone that will be used** (laptop mic, then buds), with a live level meter, a tiny
  playback of what was recorded, "Record again", and per-clip quality feedback (too quiet, too short, noisy).
- **Same voice, existing person:** when naming a voice (from People or the transcript) the user may choose "This is an existing person"
  and the clip is *added as new samples* instead of creating a duplicate person. Tiny recording + playback appears wherever a voice
  is named.

### R2. Score normalisation
- Keep a **cohort**: embeddings of other voices (everything unknown/other people seen, plus a built-in set of 40 synthetic voices rendered
  with the macOS voices as a floor). Normalised score = `(s - mean(topN cohort)) / std(topN cohort)` for N=20 (S-norm).
- Thresholds are applied to the normalised score; calibration chooses the operating point (target false-accept 1%).
- Falls back to raw cosine when the cohort has <10 voices.

### R3. Decide per turn, not per segment
- Consecutive segments with no gap >1.5 s and similar embeddings form a **turn**. Identity is the pooled embedding of the turn
  (duration-weighted), re-evaluated as audio grows; the label may be corrected backwards within the turn.
- A turn shorter than 1.2 s of speech inherits the neighbour turn's identity only if it is within 2.5 s AND the embedding agrees
  at >= 0.35 raw cosine; otherwise "Unsure".
- Never show "unknown" for a turn whose pooled score to the user is above `threshold - 0.08` when the previous turn was the user: it is
  labelled "Probably you" and counts as the user for gating purposes only when Autopilot is not about to speak publicly.

### R4. Adapt safely
- When a turn is matched with normalised score >= high (e.g. top 5% of calibration genuine scores) and passes quality gates
  (>=2 s speech, SNR ok), its embedding is added to the sub-profile of the capture source (cap 40 per person per source, oldest-
  lowest-quality evicted). Adaptation is reversible: "Forget the last hour of voice learning" in Settings, and every adapted sample
  is flagged with its source and time. Never adapts on `inherited` or `Unsure` turns, and never from audio of an unenrolled person.

### R5. Know how well it is doing (the user's #1 ask)
- A **Voice health** card in People: per capture source, shows genuine-score range of the user, nearest impostor score, estimated
  false-accept / false-reject, number of samples, and a plain verdict (Good / Fair / Needs another recording on <source>), with one
  button that does the right thing ("Record 20 s on the buds").
- Live: each transcript line shows a small confidence bar; tapping shows top-2 candidates with scores.
- The decision log has the *reason* for every Unsure/Unknown (too short, below threshold, ambiguous between A and B).

### R6. Model upgrade (measured, not assumed)
- Add CAM++ (3D-Speaker, sherpa-onnx `3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx`) and ERes2NetV2 as switchable embedders.
  Pick the default by running `eval/voice_bench.py` on (a) the user's own recorded sessions (labelled via corrections), (b) synthetic
  voices; keep WeSpeaker ResNet34 if no candidate wins by >= 15% relative EER. Embedding dimension is stored per sample; switching
  re-embeds from stored audio when available, otherwise asks for a new recording.

## 4. Acceptance (all measured, results written to `docs/validation/voice-eval.md`)
1. On the user's two stored enrolment groups: leave-one-group-out, the kNN score of group B against group A's samples must exceed the
   old mean-centroid score by >= 0.10 on average (offline test, uses the real DB embeddings when present).
2. Synthetic benchmark: with 6 synthetic enrolled voices + 40 cohort voices, TPR >= 95% at FAR <= 2% for clips >= 2 s, and for clips
   recorded through a simulated channel change (band-limit 300-3400 Hz + noise) TPR does not drop by more than 15 points vs clean.
3. Turn pooling: a scripted conversation with alternating speakers and 1-word interjections produces <= 1 wrong label per 20 turns.
4. The sentence that failed in real use ("I'll send the report on Friday", 0.71 on buds) is labelled as the user.
5. Every Unsure/Unknown has a stored reason; Voice health renders for each source.

## 5. Risks
- Adaptation can drift onto someone else's voice: guarded by high threshold, quality gates, cap, one-click rollback.
- Cohort of synthetic voices is not real people: acceptance 2 is a floor, not proof; real accuracy is reported honestly by Voice health.
- Re-enrolment burden: mitigated by recording only 20 s per mic and by passive adaptation.
