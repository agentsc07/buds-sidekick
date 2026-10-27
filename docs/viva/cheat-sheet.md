# Cheat sheet: Buds Sidekick (read 10 minutes before)

**One line:** a private assistant on a Mac; Galaxy Buds FE = mic, speaker, remote. Listens, knows who speaks, remembers, answers, whispers hints, translates Telugu and English. Nothing leaves the Mac.

**Flow:** mic -> 20 ms chunks -> segmenter (speech vs silence) -> own voice? drop -> WHO (TitaNet voiceprint) + WHAT (Whisper small.en / Telugu Whisper) -> save (SQLite + embeddings) -> screen (WebSocket) -> "Sidekick..."=Ask, else Autopilot (rules + Gemma judge + gates) -> macOS `say` -> ear.

**Models:** TitaNet-small (speaker, 192 numbers), Whisper small.en + tiny (language gate), Telugu Whisper (`ukta-app/whisper-telugu-ct2`), Gemma 4 12B via Ollama (answers, judge, translate; one resident model on 16 GB), nomic-embed-text (memory).

**Modes:** Standby, Listen, Autopilot, Translate, Private. Ask = left tap. Left: 1 Ask, 2 Replay, 3 Private, hold Translate. Right: 1 Mark, 2 Autopilot, 3 Who, hold Listen.

**Voice tricks:** top-3 samples per person, S-norm vs other voices, turn pooling, safe adaptation, threshold 0.45, unknown voices never stored.

**Numbers (all synthetic voices unless noted):**
- Speaker EER: TitaNet 2.0% (mixed enrolment, top-3); ResNet34 7.1%; ResNet293 9.3%; CAM++ 28.8%.
- English WER 4.9% (6/122; all "$2 million" formatting). Telugu WER 9.5% (2/21; 4 clips).
- Latency (n=5, load 4.7-7.3): whisper 2.02 s, model answer 2.10 s, quick command 1.98 s (README says 2.2). Translate 5.8-6.6 s, target 2.5-3.
- Autopilot precision 8/8 scripted (circular; human-rated pending).
- Tests: 428 pass (ran 27 Oct).

**Journey highlights:** lab (29 Sep) -> v0 -> v1 spec (1 Oct) -> v2 rebuild after "Autopilot is silent" (2 Oct) -> voice v3 after one person scored as two (4 Oct) -> TitaNet 7.1% -> 2.0% -> Autopilot judge + latency work (5 Oct) -> packaging, eval, site (26 Oct) -> Translate hidden then restored (v1.0.2).
Rejected: stock Whisper for Telugu, whisper.cpp GPU, 6-8 threads, "sticky" language gate, qwen for Telugu->English.

**Deployed:** GitHub repo (public) + Release v1.0.2 .dmg (371 KB launcher) + Vercel site and /demo (fixtures, no models). Assistant runs locally: Apple silicon, 16 GB, Ollama.

**Honest weak spots:** synthetic-only numbers; Autopilot 100% circular; Translate misses latency; wake word has NO speaker check; "Recording" not built; no encryption; consent note unverified; defaults noisier than spec (proactive, 8 s, 40/hr); docs say qwen 4B but code uses Gemma 12B; .dmg untested on a clean Mac recorded nowhere.

**Do not claim:** real-person accuracy, audio recording, wearer-only voice commands, encryption, that you wrote the code unaided.

**Q&A anchors:** Why local = privacy of other people. Why open-set = strangers exist. Why top-3 = two mics. Why Gemma = only one that did en->te. Why launcher not py2app = fragile wheels.
