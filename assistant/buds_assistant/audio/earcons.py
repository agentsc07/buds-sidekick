"""The designed sound set (spec 4.4): short, soft, generated locally, pre-rendered so playback starts instantly."""
from __future__ import annotations

import numpy as np

RATE = 22050
# name -> (notes [(freq_hz, ms)], amplitude 0..1)
SOUNDS: dict[str, tuple[list[tuple[float, int]], float]] = {
    "mode_on": ([(523, 90), (659, 130)], 0.30),
    "mode_off": ([(659, 90), (523, 130)], 0.30),
    "listen_start": ([(700, 100)], 0.30),
    "listen_stop": ([(500, 100)], 0.30),
    "accepted": ([(880, 60)], 0.25),
    "command": ([(988, 70), (1175, 90)], 0.30),
    "whisper": ([(440, 120)], 0.18),
    "noted": ([(784, 80), (988, 110)], 0.28),
    "error": ([(330, 140), (262, 180)], 0.32),
    "reminder": ([(659, 80), (659, 80)], 0.25),
    "thinking": ([(600, 50)], 0.18),
    "never_mind": ([(440, 80), (330, 120)], 0.25),
}
NAMES = tuple(SOUNDS)


def render(name: str, rate: int = RATE) -> np.ndarray:
    notes, amp = SOUNDS[name]
    parts = []
    for freq, ms in notes:
        n = int(rate * ms / 1000)
        t = np.arange(n) / rate
        env = np.minimum(1.0, t / 0.008) * np.exp(-3.0 * t / (ms / 1000))          # 8 ms attack, soft decay
        parts += [np.sin(2 * np.pi * freq * t) * env * amp, np.zeros(int(rate * 0.015))]
    return (np.concatenate(parts[:-1]) * 32767).astype(np.int16)


class Earcons:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[np.ndarray, int]] = {}

    def get(self, name: str) -> tuple[np.ndarray, int]:
        if name not in self._cache:
            self._cache[name] = (render(name), RATE)
        return self._cache[name]
