"""Short-lived gesture meanings (spec 4.3). Precedence: speaking > whisper > noted > replay > base map."""
from __future__ import annotations

TTL = {"whisper": 4.0, "noted": 5.0, "replay": 6.0}


class GestureContext:
    def __init__(self) -> None:
        self._open: dict[str, float] = {}

    def open(self, kind: str, now: float, ttl: float | None = None) -> None:
        self._open[kind] = now + (TTL[kind] if ttl is None else ttl)

    def close(self, kind: str) -> None:
        self._open.pop(kind, None)

    def _live(self, kind: str, now: float) -> bool:
        return self._open.get(kind, 0.0) >= now

    def intercept(self, gesture: str, now: float, speaking: bool) -> str | None:
        kind = gesture.split(":", 1)[1] if ":" in gesture else gesture
        if speaking and kind == "single":
            return "stop"
        if self._live("whisper", now):
            if kind == "single":
                self.close("whisper")
                return "tell_more"
            if kind == "double":
                self.close("whisper")
                return "not_useful"
        if self._live("noted", now) and kind == "double":
            self.close("noted")
            return "undo_commitment"
        if self._live("replay", now) and gesture == "L:double":
            self.close("replay")
            return "catch_up"
        return None
