"""Voice calibration: how well do we tell you apart from other voices on THIS microphone, and where should the match threshold sit?

Held-out clips of you are scored against your voiceprint; other voices (synthetic macOS voices, standing in for strangers) are scored
the same way. The threshold goes between the two groups. If they overlap, we say so instead of pretending."""
from __future__ import annotations

import numpy as np


def evaluate(spk, pid: int, self_clips: list[np.ndarray], impostor_clips: list[np.ndarray]) -> dict:
    me = [spk.score(a, pid) for a in self_clips]
    other = [spk.score(a, pid) for a in impostor_clips]
    self_min, imp_max = (min(me) if me else 0.0), (max(other) if other else 0.0)
    gap = self_min - imp_max
    if gap >= 0.08:
        verdict, threshold = "good", (self_min + imp_max) / 2
    elif gap > 0:
        verdict, threshold = "fair", (self_min + imp_max) / 2
    else:
        verdict, threshold = "poor", imp_max + 0.02                       # stricter: better "unsure" than the wrong name
    threshold = float(min(max(threshold, 0.3), 0.9))
    r = {"verdict": verdict, "threshold": round(threshold, 2), "self_min": round(self_min, 2), "self_mean": round(float(np.mean(me)) if me else 0.0, 2),
         "impostor_max": round(imp_max, 2), "gap": round(gap, 2), "self_scores": [round(x, 2) for x in me], "impostor_scores": [round(x, 2) for x in other]}
    r["summary"] = {
        "good": f"Recognition works well on this microphone: you score at least {r['self_min']}, other voices at most {r['impostor_max']}.",
        "fair": f"Recognition works, but close calls are possible: you score at least {r['self_min']}, other voices up to {r['impostor_max']}. Uncertain voices will be shown as unsure.",
        "poor": f"I cannot reliably tell you apart from other voices on this microphone (you score {r['self_min']} at worst, others up to {r['impostor_max']}). "
                "I will name people only when very sure. Try the other microphone, a quieter room, or a longer voice sample.",
    }[verdict]
    return r
