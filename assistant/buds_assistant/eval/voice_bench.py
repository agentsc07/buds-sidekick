"""Benchmark speaker-embedding models and scoring rules on synthetic macOS voices through a simulated microphone change.

    ../.venv/bin/python -m buds_assistant.eval.voice_bench [--models a.onnx b.onnx ...]

Enrol each voice from clean clips (optionally also from "buds-like" clips), test on buds-like clips of other sentences.
Reports equal-error-rate (EER) for mean-centroid vs top-3 scoring. Synthetic voices are a floor, not a measurement of real people."""
from __future__ import annotations

import argparse
from functools import lru_cache
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

VOICES = ["Albert", "Daniel", "Fred", "Junior", "Karen", "Kathy", "Moira", "Ralph", "Rishi", "Samantha", "Tessa", "Aman (English (India))"]
SENTENCES = ["The quarterly budget needs another review before Friday", "Please send me the report when you have a moment",
             "Let us move the meeting to Thursday afternoon instead", "I think the proposal is ready for the client now",
             "Could you check the numbers on the second slide again", "I will call the supplier tomorrow morning about the delivery",
             "We should decide who presents the results next week", "Remind me to book the room for the team lunch"]
MODELS = Path(__file__).resolve().parents[2] / "models"


@lru_cache(maxsize=None)
def synth(voice: str, text: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.wav"
        subprocess.run(["say", "-v", voice, "-o", str(p), "--file-format=WAVE", "--data-format=LEI16@16000", "--", text], check=True)
        with wave.open(str(p)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def buds_like(x: np.ndarray, seed: int) -> np.ndarray:
    """Narrow-band (300-3400 Hz), a little noise and a different level: what an in-ear mic over Bluetooth sounds like."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1 / 16000)
    y = np.fft.irfft(spec * ((f >= 300) & (f <= 3400)), n=x.size)
    rng = np.random.default_rng(seed)
    y = y + rng.standard_normal(y.size) * (np.sqrt(np.mean(y ** 2)) / 10 ** (22 / 20))
    return (0.6 * y).astype(np.float32)


def eer(gen: list[float], imp: list[float]) -> float:
    best = 1.0
    for t in np.linspace(-1, 1, 401):
        far, frr = float(np.mean(np.array(imp) >= t)), float(np.mean(np.array(gen) < t))
        best = min(best, max(far, frr))
        if far <= frr:
            return round((far + frr) / 2, 3)
    return round(best, 3)


def run(model: Path, mixed: bool) -> dict:
    from buds_assistant.speech.speaker import SherpaEmbedder, top_k
    emb = SherpaEmbedder(model)

    def e(x):
        v = emb.embed(x); return v / np.linalg.norm(v)
    clean = {v: [synth(v, s) for s in SENTENCES] for v in VOICES}
    res = {"centroid": ([], []), "top3": ([], [])}
    prof = {}
    for v in VOICES:
        enrol = [e(x) for x in clean[v][:3]]
        if mixed:
            enrol += [e(buds_like(x, i)) for i, x in enumerate(clean[v][:3])]
        prof[v] = np.array(enrol)
    for v in VOICES:
        for i, x in enumerate(clean[v][3:]):
            p = e(buds_like(x, 100 + i))
            for w in VOICES:
                m = prof[w]
                c = m.mean(axis=0); c /= np.linalg.norm(c)
                for name, s in (("centroid", float(p @ c)), ("top3", top_k(m @ p))):
                    res[name][0 if w == v else 1].append(s)
    return {k: eer(*v) for k, v in res.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=sorted(p.name for p in MODELS.glob("*.onnx")))
    a = ap.parse_args()
    print(f"{'model':58s} {'enrol on':10s} {'centroid EER':>13s} {'top-3 EER':>10s}")
    for m in a.models:
        for mixed in (False, True):
            try:
                r = run(MODELS / m, mixed)
            except Exception as exc:  # noqa: BLE001
                print(f"{m:58s} not available: {exc!r}"[:140]); break
            print(f"{m:58s} {'clean+buds' if mixed else 'clean':10s} {r['centroid']:13.3f} {r['top3']:10.3f}", flush=True)


if __name__ == "__main__":
    main()
