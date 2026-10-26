"""ManualListener: capture one utterance (or a toggled dictation) when no conversation is running.
Keeps the microphone open for `session_seconds` afterwards (sticky session: fewer Bluetooth mode flips)."""
from __future__ import annotations

import asyncio

import numpy as np

from buds_assistant.audio.segmenter import Segmenter


class ManualListener:
    def __init__(self, source_factory, placement_getter, session_seconds: float = 20.0) -> None:
        self.source_factory, self.placement_getter, self.session_seconds = source_factory, placement_getter, session_seconds
        self._source = None
        self._placement = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._seg: Segmenter | None = None
        self._fut: asyncio.Future | None = None
        self._hold: list | None = None
        self._timer: asyncio.TimerHandle | None = None

    # ---- source lifecycle ----------------------------------------------------------------------
    def _ensure(self) -> None:
        self._loop = asyncio.get_running_loop()
        place = self.placement_getter()
        if self._source is not None and place != self._placement:
            self.close()
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._source is None:
            self._placement = place
            self._source = self.source_factory(place)
            self._source.start(lambda c: self._loop.call_soon_threadsafe(self._feed, c))

    def _arm(self) -> None:
        if self._loop and self._timer is None:
            self._timer = self._loop.call_later(self.session_seconds, self.close)

    def close(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._source is not None:
            try:
                self._source.stop()
            finally:
                self._source = None

    def _feed(self, chunk: np.ndarray) -> None:
        if self._hold is not None:
            self._hold.append(chunk)
        if self._seg is not None:
            for s in self._seg.feed(chunk):
                if self._fut and not self._fut.done():
                    self._fut.set_result(s.audio)

    # ---- API ------------------------------------------------------------------------------------------
    async def utterance(self, timeout: float = 8.0) -> np.ndarray | None:
        """The next thing the user says, or None if nothing within `timeout` seconds."""
        self._ensure()
        self._seg, self._fut = Segmenter(), self._loop.create_future()
        try:
            return await asyncio.wait_for(self._fut, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._seg = self._fut = None
            self._arm()

    def hold_start(self) -> None:
        self._ensure()
        self._hold = []

    def hold_stop(self) -> np.ndarray | None:
        chunks, self._hold = self._hold, None
        self._arm()
        return np.concatenate(chunks) if chunks else None

    @property
    def holding(self) -> bool:
        return self._hold is not None
