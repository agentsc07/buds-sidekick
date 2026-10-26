"""Turn raw touch tokens ("L:double", "R:hold_start", ...) into named actions.

Bindings (gestures.yaml):
  - {name, gesture: "L:double", action}                        one gesture
  - {name, sequence: ["L:single", "R:single"], action}         several gestures within `sequence_timeout`
  - {name, gesture: "L:hold", mode: toggle, action}            hold once = ON, hold again = OFF (one continuous hold
                                                               produces a burst of hold events; a burst counts once)
  - {name, gesture: "L:hold", mode: hold, action}              raw press-and-hold: `start` on hold_start, `end` on hold_end

The buds already tell single/double/triple apart, so a token is a complete gesture.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Binding:
    name: str
    pattern: tuple[str, ...]
    action: str
    mode: str = "tap"          # "tap" | "toggle" | "hold"


@dataclass(frozen=True)
class Match:
    binding: Binding
    phase: str                 # "fire" (tap) | "toggle" | "start" | "end" (hold)


def load_bindings(path: Path) -> tuple[list[Binding], float, float]:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    out = []
    for b in doc.get("bindings", []):
        pat = tuple(b["sequence"]) if "sequence" in b else (b["gesture"],)
        out.append(Binding(b["name"], pat, b["action"], b.get("mode", "tap")))
    return out, float(doc.get("sequence_timeout", 0.7)), float(doc.get("hold_debounce", 1.2))


@dataclass
class GestureRecognizer:
    bindings: list[Binding]
    sequence_timeout: float = 0.7
    hold_debounce: float = 1.2           # hold events closer together than this belong to the same hold
    _buf: list[str] = field(default_factory=list)
    _hold_last: dict = field(default_factory=dict)
    _last: float = 0.0

    def _tap(self) -> list[Binding]:
        return [b for b in self.bindings if b.mode == "tap"]

    def _exact(self) -> Binding | None:
        for b in self._tap():
            if b.pattern == tuple(self._buf):
                return b
        return None

    def _has_longer(self) -> bool:
        n = len(self._buf)
        return any(len(b.pattern) > n and b.pattern[:n] == tuple(self._buf) for b in self._tap())

    def feed(self, token: str, t: float) -> list[Match]:
        if token.endswith(("hold_start", "hold_end")):
            side, phase = token.split(":")[0], token.split(":")[1]
            key = f"{side}:hold"
            self._buf.clear()
            toggles = [b for b in self.bindings if b.mode == "toggle" and b.pattern == (key,)]
            if toggles and phase == "hold_end":
                return []                                     # releasing a long hold must not toggle a second time
            last = self._hold_last.get(side)
            self._hold_last[side] = t
            if toggles:
                new_hold = last is None or t - last > self.hold_debounce
                return [Match(b, "toggle") for b in toggles] if new_hold else []
            return [Match(b, "start" if phase == "hold_start" else "end")
                    for b in self.bindings if b.mode == "hold" and b.pattern == (key,)]
        if self._buf and t - self._last > self.sequence_timeout:
            self._buf.clear()
        self._buf.append(token)
        self._last = t
        out = self._resolve()
        if not out and not self._has_longer() and self._buf != [token]:
            self._buf = [token]                       # wrong continuation: token may start a fresh pattern
            out = self._resolve()
        if not out and not self._has_longer():
            self._buf.clear()
        return out

    def _resolve(self) -> list[Match]:
        exact = self._exact()
        if exact and not self._has_longer():
            self._buf.clear()
            return [Match(exact, "fire")]
        return []

    def poll(self, t: float) -> list[Match]:
        """Call regularly: fires an exact match that was waiting for a longer sequence."""
        if self._buf and t - self._last >= self.sequence_timeout:
            exact = self._exact()
            self._buf.clear()
            if exact:
                return [Match(exact, "fire")]
        return []
