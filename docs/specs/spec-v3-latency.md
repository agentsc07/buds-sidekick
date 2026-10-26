# Spec v3-C: Latency (where the time goes, what we tried, what we kept)

Status: 2026-10-05. Machine: MacBook Air, Apple M3 (**4 performance + 4 efficiency cores**), 16 GB. Measured with `eval/latency_bench.py`
(end to end, synthetic speech), `eval/voice_bench.py` and ad-hoc timers. Load average is recorded because it changes every number below.

## 0. The rule that explains most of what you feel
The Telugu recogniser is CPU-bound and the M3 has only **4 fast cores**. When other programs use them (a browser, VS Code, other
Claude sessions, a recording script) the same pass takes 3-10x longer: 20-40 s were measured at load average 16-65 for a 5 s clip, 1.8-3 s at
load 3-5. Everything below is "on a quiet Mac" unless stated. The app now says so when the Mac is busy (banner at load > 2 x cores).
**Closing other heavy apps is the single biggest latency lever.**

## 1. The two paths and their stages
### Interpreter (phrase heard -> translation starts playing)
| # | Stage | Quiet Mac | Notes |
|---|---|---|---|
| 1 | Wait for the speaker to pause (`end_silence`) | 0.45 s | Past 2.5 s of speech a 0.2 s dip also ends the clause (soft split) |
| 2 | Queue wait: earlier phrase still being recognised | 0-3 s | Recognition runs about as fast as people talk, so back-to-back speech queues |
| 3 | Speaker identification | 0 (skipped one-way) / 0.1-0.25 s | Not needed to translate |
| 4 | Language gate (tiny Whisper) | 0.3 s | Decides Telugu or English |
| 5 | Speech recognition | 1.8-3.1 s | ~1.3 s fixed (30 s window) + ~0.25 s per second of speech |
| 6 | Translation (gemma4 12B) | 1.2-1.7 s (3.5 cold) | Output tokens dominate |
| 7 | Speech synthesis (`say`) render | 0.35-0.55 s | Process start ~0.35 s |
| 8 | Playback of the translation | 2.5-4 s long | The listener waits for the end |
Median measured end to end: 5.8-6.6 s at load 3-4 (target 2.5-3.0 s; **not met**). Cold start of Translate: 19-20 s (model load + warm-up).

### Ask (you speak -> answer starts)
| Stage | Quiet Mac |
|---|---|
| Pause detection | 0.7 s |
| Recognition (small.en) | 0.8-1.2 s |
| Answer: rules (calendar, to-dos, reminders) | < 0.05 s |
| Answer: language model | 1-2.5 s |
| Speech render + start | 0.5 s |
| Playback | 2-4 s -> now one short sentence |

### Autopilot judgement (a thought ends -> whisper starts)
Debounce 1.5 s + model 1-2.5 s + gap wait. Acceptable for a whisper; it never runs while the assistant is speaking.

## 2. Levers: measured and decided
| Lever | Expected | Measured | Decision |
|---|---|---|---|
| Machine busy | 3-10x | 3-10x (load 16-65) | **Adopted: banner**; ask the user to close heavy apps |
| Skip speaker ID in one-way Translate | -0.1-0.25 s/phrase | not separately measurable | **Adopted** (`no_id`; lines show their language, not "Unknown") |
| Skip the recogniser's own VAD pass | -0.1-0.3 s | within noise (2.9 vs 2.97 s) | **Adopted** (harmless, segments are already speech) |
| Level up quiet speech before recognition | accuracy, not speed | n/a | **Adopted** (`boost`) |
| Soft clause split (2.5 s + 0.2 s dip) | tail latency of long sentences -1 s | splits observed (sentence 1 became two clauses) | **Adopted** |
| Merge queued phrases into one recognition pass | -1.3 s per merged phrase when behind | not triggered in the bench (phrases did not queue); unit-tested | **Adopted** (only when behind, one-way, <= 12 s, < 1.5 s gaps) |
| Speak the translation faster (185 -> 205 wpm) | -0.3-0.4 s | by definition | **Adopted** |
| Spoken answers: one short sentence | -1-2 s of playback | by definition | **Adopted** |
| Stale/duplicate answers dropped | removes bursts | n/a | **Adopted** (also fixed "answers after closing the tab") |
| Shorter chat timeout (25 s) | bounds bad cases | n/a | **Adopted** |
| Skip the language gate after Telugu ("sticky") | -0.3 s | **wrong**: an English reply came out as Telugu letters | **Rejected, reverted** (test documents why) |
| whisper.cpp + Metal GPU, Telugu *base* | 3-5x | 1.1 s (2 s clip) / 2.5-3.2 s (5.6 s clip): **no faster than CPU**, and a spelling error; *small* GGML gave unrelated text | **Rejected**. The Telugu decoder emits ~3 tokens per Telugu letter, so decoding, not the GPU-friendly encoder, is the cost |
| More CPU threads (6, 8) | faster | **slower** (4 threads best; 8 gave 3-15 s) | **Rejected**; stay at 4 (= the fast cores) |
| Turn off VAD + timestamps in the recogniser | -0.2 s | 2.9 vs 2.7 s: noise | Kept off in Translate only |
| `qwen3.5:4b` instead of gemma for Telugu -> English | -0.5 s | 0.6-1.2 s vs 1.2-1.7 s, same quality on 4 sentences | **Rejected**: both models resident does not fit 16 GB; English -> Telugu needs gemma anyway |
| Shorter translation prompt | -0.1 s | -0.1 s | **Rejected**: the long prompt exists because short ones left weekdays and times in English |

## 3. Ideas not done (with the reason)
1. **Streaming speech synthesis** (AVSpeechSynthesizer buffers instead of `say`): -0.3 s, needs PyObjC audio plumbing. Next candidate.
2. **Incremental recognition while the person is still speaking** (decode the first 2-3 s early): the real fix for the fixed cost, but needs a
   streaming recogniser; Whisper is not one. Candidate: a Telugu streaming Conformer (AI4Bharat IndicConformer) in sherpa-onnx; unverified for Telugu quality.
3. **Telugu recogniser on the Neural Engine** (Core ML): offloads the CPU so busy-Mac slowdowns shrink; needs a Core ML build of the fine-tuned model.
4. **Two recognition workers**: only helps with more fast cores; on 4 cores it just contends.
5. **Pre-load the translator at app start**: removes the 19 s cold start but holds 8 GB; memory-bound on 16 GB.

## 4. Acceptance and how to measure
- On a quiet Mac (load < 2): `../.venv/bin/python -m buds_assistant.eval.latency_bench` after stopping the app. Record median end-to-end.
  Target 2.5-3.0 s; today 5.8-6.6 s. Honest status: **not met**; the remaining gap is the Telugu recognition pass (1.8-3.1 s) plus translation (1.2-1.7 s).
- Unit tests pin each adopted trim (`tests/test_latency_trims.py`, `tests/test_segmenter.py`, `tests/test_answer_hygiene.py`).
- A change is kept only if it is faster **and** does not lose accuracy on the synthetic Telugu/English set (the sticky-gate experiment is the example).
