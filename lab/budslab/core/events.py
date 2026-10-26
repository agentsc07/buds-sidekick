"""Normalized event model shared by every layer.

    {ts, layer, source, type, side, data, raw_hex}

layer: "A" standard bluetooth / OS, "B" Samsung RFCOMM protocol, "C" raw discovery, "S" system
type : frame | battery | touch | wear | case | anc | audio | media_key | conn | status |
       unknown | command | command_result | note | system
side : "L" | "R" | "both" | None
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any

# event types that count as "the world changed" when judging an experiment
RELEVANT_TYPES = {"touch", "wear", "case", "anc", "audio", "media_key", "command_result", "conn"}


@dataclass
class Event:
    layer: str
    source: str
    type: str
    side: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    raw_hex: str | None = None
    ts: float = field(default_factory=time.time)
    # filled in by the hub
    seq: int = 0
    t: float = 0.0                       # seconds since session start
    session_id: str = ""
    experiment_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["t"] = round(self.t, 3)
        return d
