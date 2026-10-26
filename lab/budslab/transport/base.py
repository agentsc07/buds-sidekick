"""Transport interface. Platform specifics live behind this."""
from __future__ import annotations

import abc
from typing import Callable

OnData = Callable[[bytes], None]
OnState = Callable[[str, dict], None]     # ("connecting"|"connected"|"disconnected"|"error", info)

# Samsung's custom SPP service UUID used by the Buds2 family / FE (per reference)
SPP_UUID_NEW = "2e73a4ad-332d-41fc-90e2-16bef06523f2"
SPP_UUID_LEGACY = "00001102-0000-1000-8000-00805f9b34fd"


class Transport(abc.ABC):
    name = "transport"
    connected = False

    @abc.abstractmethod
    async def run(self, on_data: OnData, on_state: OnState) -> None:
        """Connect (and reconnect with backoff) until cancelled. Must clean up on cancellation."""

    @abc.abstractmethod
    async def send(self, data: bytes) -> None:
        """Write raw bytes to the link. Only the guarded lab code calls this."""

    async def close(self) -> None:  # optional
        return None

    def describe(self) -> dict:
        return {"name": self.name}
