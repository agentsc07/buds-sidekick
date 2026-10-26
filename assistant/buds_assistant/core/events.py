"""EventBus: everything interesting is published here; the dashboard and tests subscribe."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any, Callable


class EventBus:
    def __init__(self, history: int = 800) -> None:
        self._seq = 0
        self._lock = threading.Lock()
        self.history: deque = deque(maxlen=history)
        self._cbs: list[Callable[[dict], None]] = []
        self._queues: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self.t0 = time.time()

    def publish(self, type_: str, **data: Any) -> dict:
        with self._lock:
            self._seq += 1
            ev = {"seq": self._seq, "ts": time.time(), "t": round(time.time() - self.t0, 2), "type": type_, "data": data}
            self.history.append(ev)
            cbs, queues = list(self._cbs), list(self._queues)
        for cb in cbs:
            try:
                cb(ev)
            except Exception:  # a subscriber must never break the pipeline
                pass
        for loop, q in queues:
            try:
                loop.call_soon_threadsafe(self._put, q, ev)
            except RuntimeError:
                pass
        return ev

    @staticmethod
    def _put(q: asyncio.Queue, ev: dict) -> None:
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass

    def subscribe(self, cb: Callable[[dict], None]) -> None:
        self._cbs.append(cb)

    def queue(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._queues.append((asyncio.get_running_loop(), q))
        return q

    def drop(self, q: asyncio.Queue) -> None:
        self._queues = [(l, x) for l, x in self._queues if x is not q]

    def scrub(self, drop) -> int:
        """Remove history events for which drop(event) is true (forget / delete everything)."""
        with self._lock:
            keep = [e for e in self.history if not drop(e)]
            n = len(self.history) - len(keep)
            self.history.clear()
            self.history.extend(keep)
        return n

    def recent(self, n: int = 200, types: set[str] | None = None) -> list[dict]:
        with self._lock:
            evs = list(self.history)
        if types:
            evs = [e for e in evs if e["type"] in types]
        return evs[-n:]
