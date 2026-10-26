"""Anti-accident filter: ignore touches right after the buds are inserted/removed and bursts of taps (pocket / adjusting)."""
from __future__ import annotations

from collections import deque


class TouchFilter:
    def __init__(self, burst_limit: int = 3, window: float = 1.0, wear_guard: float = 1.0) -> None:
        self.burst_limit, self.window, self.wear_guard = burst_limit, window, wear_guard
        self._wear = float("-inf")
        self._taps: deque[float] = deque()

    def note_wear(self, now: float) -> None:
        self._wear = now

    def accept(self, token: str, now: float) -> bool:
        if now - self._wear < self.wear_guard:
            return False
        if "hold" in token:
            return True
        while self._taps and now - self._taps[0] > self.window:
            self._taps.popleft()
        self._taps.append(now)
        return len(self._taps) <= self.burst_limit
