"""Speaker-ID benchmark on real recordings.

Folder layout (made by capture_kit, or by hand):
    DIR/Alice_enrol/*.wav      enrolment clips for Alice
    DIR/Alice_0.5m/*.wav       test clips of Alice at 0.5 m   (any `Alice_<condition>` folder is a test set)
    DIR/Alice_1m/*.wav
    DIR/stranger_X/*.wav       voices that are NOT enrolled (must be rejected)

    python -m buds_assistant.eval.speaker_bench DIR [--threshold 0.62]

Reports per-condition accuracy, stranger false-accept rate, and a threshold sweep. The Phase-0 gate in the spec is
>= 90 % segment accuracy for segments >= 2 s with <= 5 % stranger false-accepts."""
from __future__ import annotations

import argparse
import json
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np

from buds_assistant.audio.capture import resample


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return resample(raw[::w.getnchannels()], w.getframerate())


def _norm(v):
    n = np.linalg.norm(v)
    return v / n if n else v


def evaluate(embs: dict[str, dict[str, list[np.ndarray]]], threshold: float = 0.62, margin: float = 0.04) -> dict:
    """embs[folder_name] = list of embeddings. Pure function (no audio/model), so it is unit-testable."""
    speakers = sorted({k.rsplit("_", 1)[0] for k in embs if k.endswith("_enrol")})
    cent = {s: _norm(np.mean([_norm(e) for e in embs[f"{s}_enrol"]], axis=0)) for s in speakers}

    def identify(e: np.ndarray, thr: float):
        e = _norm(e)
        sc = sorted(((float(e @ c), s) for s, c in cent.items()), reverse=True)
        if sc and sc[0][0] >= thr and (len(sc) == 1 or sc[0][0] - sc[1][0] >= margin):
            return sc[0][1], sc[0][0]
        return None, sc[0][0] if sc else 0.0

    genuine, imposter = [], []                       # (true speaker, embedding)
    per_condition: dict[str, list[bool]] = defaultdict(list)
    for folder, es in embs.items():
        if folder.endswith("_enrol"):
            continue
        spk = folder.rsplit("_", 1)[0]
        for e in es:
            if spk.startswith("stranger"):
                imposter.append(e)
            elif spk in cent:
                genuine.append((spk, e))
                per_condition[folder].append(identify(e, threshold)[0] == spk)
    far = [identify(e, threshold)[0] is not None for e in imposter]
    sweep = []
    for thr in np.arange(0.3, 0.9, 0.05):
        acc = np.mean([identify(e, thr)[0] == s for s, e in genuine]) if genuine else float("nan")
        fa = np.mean([identify(e, thr)[0] is not None for e in imposter]) if imposter else float("nan")
        sweep.append({"threshold": round(float(thr), 2), "accuracy": round(float(acc), 3), "stranger_false_accept": round(float(fa), 3)})
    acc_all = float(np.mean([x for v in per_condition.values() for x in v])) if per_condition else float("nan")
    far_all = float(np.mean(far)) if far else float("nan")
    return {"threshold": threshold, "speakers": speakers,
            "accuracy": round(acc_all, 3), "stranger_false_accept": round(far_all, 3),
            "per_condition": {k: {"n": len(v), "accuracy": round(float(np.mean(v)), 3)} for k, v in sorted(per_condition.items())},
            "sweep": sweep,
            "gate_passed": bool(acc_all >= 0.90 and (np.isnan(far_all) or far_all <= 0.05))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--threshold", type=float, default=0.62)
    ap.add_argument("--model", type=Path, default=None)
    ap.add_argument("--min-seconds", type=float, default=2.0, help="ignore clips shorter than this")
    a = ap.parse_args()
    from buds_assistant.core.config import Config
    from buds_assistant.speech.speaker import SherpaEmbedder, to_f32
    emb = SherpaEmbedder(a.model or Config().speaker_model)
    embs: dict[str, list] = {}
    for d in sorted(p for p in a.dir.iterdir() if p.is_dir()):
        clips = [load_wav(w) for w in sorted(d.glob("*.wav"))]
        embs[d.name] = [emb.embed(to_f32(c)) for c in clips if c.size >= a.min_seconds * 16000]
    rep = evaluate(embs, a.threshold)
    (a.dir / "report.json").write_text(json.dumps(rep, indent=2))
    print(f"speakers: {rep['speakers']}\naccuracy {rep['accuracy']:.1%}   stranger false-accept {rep['stranger_false_accept']:.1%}"
          f"   gate (>=90% / <=5%): {'PASS' if rep['gate_passed'] else 'FAIL'}")
    for k, v in rep["per_condition"].items():
        print(f"  {k:<24} n={v['n']:<3} accuracy {v['accuracy']:.1%}")
    print("threshold sweep:")
    for r in rep["sweep"]:
        print(f"  {r['threshold']:.2f}  acc {r['accuracy']:.2f}  false-accept {r['stranger_false_accept']:.2f}")


if __name__ == "__main__":
    main()
