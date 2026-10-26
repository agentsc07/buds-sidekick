"""Mic check: how clearly does a microphone hear someone speaking? Speech level against the room's noise floor."""
from __future__ import annotations

import numpy as np

FRAME = 320                                   # 20 ms at 16 kHz


def measure(audio: np.ndarray) -> dict:
    """{level_db, snr_db}: loudest-10% frame level, and how far it sits above the quietest-10% (the noise floor)."""
    a = audio.astype(np.float32) / 32768.0
    n = a.size // FRAME
    if n < 10:
        return {"level_db": -90.0, "snr_db": 0.0}
    rms = np.sqrt(np.mean(a[: n * FRAME].reshape(n, FRAME) ** 2, axis=1)) + 1e-6
    lo, hi = float(np.percentile(rms, 10)), float(np.percentile(rms, 90))
    return {"level_db": round(20 * np.log10(hi), 1), "snr_db": round(max(0.0, 20 * np.log10(hi / lo)), 1)}
