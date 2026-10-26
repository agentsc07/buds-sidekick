"""Numbers for the report: speech recognition word error, end-to-end latency, Autopilot precision.

    python -m buds_assistant.eval.submission_eval record               you read 14 English + 8 Telugu sentences (about 6 minutes)
    python -m buds_assistant.eval.submission_eval wer      [--clips DIR]      synthetic voices + your own clips (DIR/manifest.csv)
    python -m buds_assistant.eval.submission_eval latency [--runs 3]         speech end -> answer / whisper, real models, simulated buds
    python -m buds_assistant.eval.submission_eval autopilot [--db PATH]      precision of the whispers you rated (thumbs) in a session
    python -m buds_assistant.eval.submission_eval autopilot --script         precision on the scripted ten-minute conversation (no humans)

Results are appended to docs/validation/eval-results.json. Close other heavy programs first: a busy Mac makes everything slower.
Synthetic (macOS `say`) voices are a floor, not real people; clips recorded by a person are reported separately."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import unicodedata
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

RESULTS = Path(__file__).resolve().parents[3] / "docs" / "validation" / "eval-results.json"

EN_SENTENCES = [
    "The budget for the third quarter is two million dollars.",
    "Please send me the report by Friday afternoon.",
    "I have a meeting with the design team tomorrow at ten.",
    "Can you remind me to call my mother this evening?",
    "The parking permit expires at the end of the month.",
    "We should move the review to Thursday and walk through the numbers.",
]
TE_SENTENCES = [
    "రేపు మధ్యాహ్నం మన సమావేశం మూడు గంటలకు ఉంటుంది",
    "మీరు నాకు శుక్రవారం రిపోర్ట్ పంపగలరా",
    "ధన్యవాదాలు, నేను సమయానికి వస్తాను",
    "ఈ రోజు వాతావరణం చాలా బాగుంది",
]


def save(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(audio.astype(np.int16).tobytes())


def load_wav(path: Path) -> np.ndarray:
    from buds_assistant.audio.capture import resample
    with wave.open(str(path)) as w:
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return resample(raw[::w.getnchannels()], w.getframerate())


def norm(text: str) -> list[str]:
    keep = "".join(c if unicodedata.category(c)[0] in "LMN" or c.isspace() else " " for c in text.lower())      # keeps Telugu vowel signs (marks)
    return keep.split()


def wer(ref: str, hyp: str) -> tuple[int, int]:
    """(word errors, reference words) by edit distance."""
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)], len(r)


def _store(key: str, value: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    doc[key] = {**value, "measured": datetime.now().isoformat(timespec="minutes"), "load_average": round(os.getloadavg()[0], 1)}
    RESULTS.write_text(json.dumps(doc, indent=2, ensure_ascii=False))


# ---- word error -------------------------------------------------------------------------------------------------
def cmd_wer(a) -> None:
    from buds_assistant.audio.demo import render
    from buds_assistant.speech.transcribe import WhisperEn, WhisperTe
    en, te = WhisperEn("small.en"), WhisperTe()
    items: list[tuple[str, str, str, np.ndarray]] = []              # (set, lang, reference, audio)
    with tempfile.TemporaryDirectory() as d:
        for i, s in enumerate(EN_SENTENCES):
            for v in ("Samantha", "Daniel"):
                items.append(("synthetic", "en", s, render(v, s, Path(d) / "x.wav")))
        for s in TE_SENTENCES:
            items.append(("synthetic", "te", s, render("Geeta", s, Path(d) / "x.wav")))
    if a.clips and (Path(a.clips) / "manifest.csv").exists():
        for row in csv.DictReader(open(Path(a.clips) / "manifest.csv", encoding="utf-8")):
            items.append(("recorded", row["lang"], row["text"], load_wav(Path(a.clips) / row["file"])))
    stats: dict[str, list[int]] = {}
    for kind, lang, ref, audio in items:
        hyp = (en if lang == "en" else te).transcribe(audio, None if lang == "en" else "te").text
        e, n = wer(ref, hyp)
        k = f"{kind}_{lang}"
        stats.setdefault(k, [0, 0, 0]); stats[k][0] += e; stats[k][1] += n; stats[k][2] += 1
        print(f"[{k}] WER {e}/{n}  ref: {ref[:50]}  hyp: {hyp[:50]}")
    out = {k: {"clips": c, "words": n, "word_errors": e, "wer": round(e / max(n, 1), 3)} for k, (e, n, c) in stats.items()}
    print(json.dumps(out, indent=2)); _store("asr_wer", out)


# ---- latency ----------------------------------------------------------------------------------------------------
async def _latency(runs: int) -> dict:
    from buds_assistant.audio.capture import FileSource
    from buds_assistant.audio.demo import render
    from buds_assistant.core.config import CONFIG_DIR, Config
    from buds_assistant.sidekick import Sidekick
    cfg = Config(data_dir=Path(tempfile.mkdtemp()), autopilot_sensitivity="proactive")
    sk = Sidekick(cfg, CONFIG_DIR / "sidekick_gestures.yaml", simulate=True, silent=True)
    await sk.start()
    load0 = os.getloadavg()[0]
    rng = np.random.default_rng(3)
    quiet = lambda s: (rng.standard_normal(int(s * 16000)) * 40).astype(np.int16)   # noqa: E731
    with tempfile.TemporaryDirectory() as d:
        x = Path(d) / "x.wav"
        sk.speaker.enroll("Me", [render("Albert", t, x) for t in ("My name is the speaker you are hearing now.", "I like to plan the week on Monday morning.", "Please remember what I say in meetings.")], "evaluation")
        ravi = sk.store.add_person("Ravi", "evaluation")                  # something to remember, so Ask has a grounded answer to find
        cid, t0 = sk.store.start_conversation("listen"), time.time() - 86400
        sid = sk.store.add_segment(cid, t0, t0 + 3, ravi, None, 0.9, "I will send the Q3 report by Friday")
        sk.memory.index_segment(sid, "I will send the Q3 report by Friday")
        sk.store.add_fact(ravi, "commitment", "send the Q3 report", "Friday", sid, owner="Ravi")
        if not sk.personal.has_sample():
            sk.personal.seed_sample(datetime.now(), force=True)
        lines = [("capture", "I'll send the deck on Friday afternoon."), ("ask_llm", "Sidekick, what did Ravi promise me?"), ("ask_rule", "Sidekick, what is on my calendar today?")]
        results: dict[str, list[float]] = {k: [] for k, _ in lines}
        await sk.modes.set_mode("autopilot")
        for _ in range(runs):
            parts, ends, t = [quiet(1.0)], {}, 1.0
            for key, text in lines:
                a = render("Albert", text, x)
                parts += [a, quiet(14.0)]; t += len(a) / 16000; ends[key] = t; t += 14.0
            audio = np.concatenate(parts)
            mark = sk.events.recent(1, None)[-1]["seq"] if sk.events.recent(1, None) else 0
            t_start = time.time()
            sk.pipeline.set_source(FileSource(audio=audio, realtime=True, speed=1.0))
            await asyncio.sleep(len(audio) / 16000 + 25)
            evs = [e for e in sk.events.recent(600, {"hint", "reply"}) if e["seq"] > mark]
            if os.environ.get("EVAL_DEBUG"):
                for e in sk.events.recent(600, {"segment", "reply", "hint", "error"}):
                    if e["seq"] > mark:
                        d = e["data"]; print(f"  +{e['ts'] - t_start:6.1f}s {e['type']:8s} {d.get('text') or d.get('error') or d}"[:150])
            for key, _ in lines:
                lo, hi = t_start + ends[key], t_start + ends[key] + 12.0
                hit = next((e for e in evs if lo <= e["ts"] <= hi), None)
                if hit:
                    results[key].append(round(hit["ts"] - lo, 2))
    await sk.stop()
    names = {"capture": "autopilot_whisper", "ask_llm": "ask_model_answer", "ask_rule": "ask_quick_command"}
    out = {names[k]: {"runs": len(v), "median_s": round(statistics.median(v), 2) if v else None, "all_s": v} for k, v in results.items()}
    out["note"] = "end of speech to the start of the answer text (spoken playback not included); synthetic voice; load average at start %.1f" % load0
    return out


def cmd_latency(a) -> None:
    out = asyncio.run(_latency(a.runs))
    print(json.dumps(out, indent=2)); _store("latency", out)


# ---- autopilot precision ---------------------------------------------------------------------------------------
def cmd_autopilot(a) -> None:
    if a.script:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "support"))
        from fixtures_autopilot import SCRIPT, build, run
        with tempfile.TemporaryDirectory() as d:
            p, s, people, cfg = build(Path(d))
            said = run(SCRIPT, p, people)
        hits = [x for x in said if x[1] == x[2]]
        out = {"whispers": len(said), "as_expected": len(hits), "precision": round(len(hits) / max(len(said), 1), 3),
               "note": "rules only, scripted ten-minute conversation with labelled trigger points (no model judgement, no humans)"}
    else:
        from buds_assistant.core.store import Store
        rows = Store(Path(a.db)).q("SELECT feedback FROM hints WHERE spoken=1 AND feedback IS NOT NULL") if a.db else []
        up = sum(1 for r in rows if r["feedback"] == 1)
        out = {"rated_whispers": len(rows), "useful": up, "precision": round(up / len(rows), 3) if rows else None,
               "note": "whispers you rated with the thumbs in the dashboard (or 'tell me more' / 'not useful' taps)"}
    print(json.dumps(out, indent=2)); _store("autopilot_scripted" if a.script else "autopilot_session", out)


# ---- recording the clips (needs a person) -----------------------------------------------------------------------
EN_READ = EN_SENTENCES + ["What time is my meeting with Priya on Friday?", "Sidekick, remind me to send the deck tomorrow morning.",
                          "I think we should order the new laptops before the end of the month.", "Could you repeat that number for me please?"]
TE_READ = TE_SENTENCES + ["మనం రేపు ఉదయం తొమ్మిది గంటలకు కలుద్దాం", "నాకు ఒక కప్పు టీ కావాలి", "ఈ పని శుక్రవారంలోగా పూర్తి చేయాలి", "మీ పేరు ఏమిటి"]


def cmd_record(a) -> None:
    """Prompt for each sentence, record it from the Mac mic (or the buds if they are the system input), save wav + manifest.csv."""
    from buds_assistant.eval.capture_kit import record
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for lang, sents in (("en", EN_READ), ("te", TE_READ)):
        if a.lang in (lang, "both"):
            for i, text in enumerate(sents):
                input(f"\n[{lang} {i + 1}/{len(sents)}] Press Enter, then read this aloud:\n    {text}\n")
                audio = record(a.input, a.seconds)
                f = f"{lang}_{i + 1:02d}.wav"; save(out / f, audio); rows.append({"file": f, "lang": lang, "text": text})
    path = out / "manifest.csv"; new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["file", "lang", "text"]); new and w.writeheader(); w.writerows(rows)
    print(f"Saved {len(rows)} clips to {out}. Now run:  python -m buds_assistant.eval.submission_eval wer")


def main() -> None:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wer"); w.add_argument("--clips", default=str(Path(__file__).resolve().parents[3] / "docs" / "validation" / "clips"))
    l = sub.add_parser("latency"); l.add_argument("--runs", type=int, default=3)
    r = sub.add_parser("record"); r.add_argument("--out", default=str(Path(__file__).resolve().parents[3] / "docs" / "validation" / "clips"))
    r.add_argument("--lang", default="both", choices=["en", "te", "both"]); r.add_argument("--seconds", type=float, default=7.0); r.add_argument("--input", default="mac", choices=["mac", "buds"])
    p = sub.add_parser("autopilot"); p.add_argument("--db"); p.add_argument("--script", action="store_true")
    a = ap.parse_args()
    {"wer": cmd_wer, "latency": cmd_latency, "autopilot": cmd_autopilot, "record": cmd_record}[a.cmd](a)


if __name__ == "__main__":
    main()
