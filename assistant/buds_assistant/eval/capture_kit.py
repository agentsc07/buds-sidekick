"""Guided recording for the Phase-0 measurement: record real people through a chosen microphone.

    python -m buds_assistant.eval.capture_kit --out data/phase0 --speakers Alice,Bob --strangers Carol \
        --distances 0.5m,1m,2m --input buds        # or --input mac for the room microphone

Each speaker records enrolment clips, then test clips at each distance. Then run speaker_bench on the folder.
Only record people who have agreed. Files stay local."""
from __future__ import annotations

import argparse
import time
import wave
from pathlib import Path

import numpy as np

from buds_assistant.audio.capture import MicSource

PROMPTS = ["Please talk naturally about what you did yesterday.", "Describe your favourite meal and how it is made.",
           "Explain how you get to work or school each day.", "Tell me about a place you would like to visit.",
           "Talk about a project you are working on.", "Describe the room you are sitting in right now."]


def record(prefer, seconds: float) -> np.ndarray:
    chunks: list[np.ndarray] = []
    src = MicSource(prefer)
    src.start(chunks.append)
    try:
        time.sleep(seconds)
    finally:
        src.stop()
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)


def save(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(audio.tobytes())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--speakers", default="", help="comma separated names of people to enrol and test")
    ap.add_argument("--strangers", default="", help="people who will NOT be enrolled (must be rejected)")
    ap.add_argument("--distances", default="0.5m,1m")
    ap.add_argument("--input", default="buds", help="buds | mac")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--enrol-clips", type=int, default=3)
    ap.add_argument("--test-clips", type=int, default=3)
    a = ap.parse_args()
    plan = [(s, "enrol", a.enrol_clips) for s in a.speakers.split(",") if s] + \
           [(s, d, a.test_clips) for s in a.speakers.split(",") if s for d in a.distances.split(",")] + \
           [("stranger_" + s, d, a.test_clips) for s in a.strangers.split(",") if s for d in a.distances.split(",")]
    for who, cond, n in plan:
        label = who.replace("stranger_", "")
        where = "talk at the microphone as you normally would" if cond == "enrol" else f"stand/sit about {cond} from the {a.input} microphone"
        for i in range(n):
            input(f"\n[{label} / {cond} / clip {i + 1} of {n}] {where}. Prompt: {PROMPTS[i % len(PROMPTS)]}\n  Press Enter, then talk for {a.seconds:.0f} s… ")
            audio = record(a.input, a.seconds)
            save(a.out / f"{who}_{cond}" / f"clip{i + 1}.wav", audio)
            print(f"  saved ({audio.size / 16000:.1f} s, peak {int(np.max(np.abs(audio))) if audio.size else 0})")
    print(f"\nDone. Now run:  python -m buds_assistant.eval.speaker_bench {a.out}")


if __name__ == "__main__":
    main()
