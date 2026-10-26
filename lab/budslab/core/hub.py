"""Event hub: one shared clock, sequence numbers, persistence, fan-out."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from .events import Event
from .store import Store


class Hub:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.session_id = store.session_id
        self.t0 = time.time()
        self.seq = 0
        self.active_experiment: Callable[[], str | None] = lambda: None
        self.listeners: list[Callable[[Event], None]] = []
        self.queues: set[asyncio.Queue] = set()
        self.counters = {"events": 0, "frames_rx": 0, "frames_tx": 0}

    def emit(self, ev: Event) -> Event:
        self.seq += 1
        ev.seq = self.seq
        ev.t = ev.ts - self.t0
        ev.session_id = self.session_id
        ev.experiment_id = self.active_experiment()
        self.counters["events"] += 1
        self.store.add_event(ev)
        for fn in list(self.listeners):
            try:
                fn(ev)
            except Exception:  # a listener must never break capture
                import logging
                logging.getLogger("budslab").exception("listener failed")
        self.broadcast({"kind": "event", "event": ev.to_dict()})
        return ev

    def broadcast(self, msg: dict[str, Any]) -> None:
        for q in list(self.queues):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                self.queues.discard(q)   # slow client; it will reconnect and resync

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self.queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.queues.discard(q)
