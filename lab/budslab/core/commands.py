"""Guarded command sending: toggle + allowlist + confirmation + response/latency tracking."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from ..protocol import commands as C
from ..protocol.frames import Frame, FrameCodec
from ..protocol.messages import RESP, UNIVERSAL_ACK
from .events import Event
from .hub import Hub
from .state import DeviceState

RESPONSE_TIMEOUT = 3.0


class CommandService:
    def __init__(self, hub: Hub, state: DeviceState, codec: FrameCodec,
                 send_bytes: Callable[[bytes], Awaitable[None]], is_connected: Callable[[], bool],
                 log_tx: Callable[[bytes, Frame, str], None]) -> None:
        self.hub, self.state, self.codec = hub, state, codec
        self._send_bytes, self._is_connected, self._log_tx = send_bytes, is_connected, log_tx
        self.enabled = False
        self.find_my_active = False
        self._pending: dict[int, asyncio.Future] = {}

    # called by the lab for every rx frame
    def on_frame(self, f: Frame) -> None:
        if f.msg_id in (RESP, UNIVERSAL_ACK) and f.payload:
            fut = self._pending.get(f.payload[0])
            if fut and not fut.done():
                fut.set_result(f)

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        self.hub.emit(Event("S", "commands", "system", data={"event": "commands_enabled", "enabled": self.enabled}))
        self.hub.broadcast({"kind": "status"})

    def catalog(self) -> list[dict]:
        return [c.public() for c in C.COMMANDS.values()]

    def undo_for(self, name: str, args: dict) -> tuple[str, dict] | None:
        spec = C.COMMANDS.get(name)
        if spec and spec.undo:
            try:
                return spec.undo(args, self._state())
            except C.CommandError:
                return None
        return None

    def _state(self) -> dict:
        st = self.state.snapshot()
        st["find_my_active"] = self.find_my_active
        return st

    async def send(self, name: str, args: dict | None = None, *, confirm: bool = False,
                   experiment_id: str | None = None, undo: bool = False) -> dict[str, Any]:
        args = args or {}
        if not self.enabled:
            raise C.CommandError("command sending is disabled (read-only). Enable it in the Commands view.")
        spec, payload = C.build(name, args, self._state())
        if spec.confirm and not confirm:
            raise C.CommandError(f"confirmation required: {spec.confirm}")
        if not self._is_connected():
            raise C.CommandError("buds are not connected")
        frame_bytes = self.codec.encode(spec.msg_id, payload, type_bit=False)
        frame = Frame(spec.msg_id, payload, False, False, True, frame_bytes)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[spec.msg_id] = fut
        t_send = time.perf_counter()
        ts = time.time()
        self._log_tx(frame_bytes, frame, f"command:{name}")
        await self._send_bytes(frame_bytes)
        status, result, latency = "no_response", {}, None
        try:
            resp: Frame = await asyncio.wait_for(fut, RESPONSE_TIMEOUT)
            latency = (time.perf_counter() - t_send) * 1000
            if resp.msg_id == RESP and len(resp.payload) > 1 and resp.payload[1] != 0:
                status, result = "rejected", {"result_code": resp.payload[1]}
            else:
                status, result = "acked", {"via": "RESP" if resp.msg_id == RESP else "ACK"}
        except asyncio.TimeoutError:
            pass
        finally:
            self._pending.pop(spec.msg_id, None)
        if status == "acked":
            if name == "find_my_start":
                self.find_my_active = True
            elif name == "find_my_stop":
                self.find_my_active = False
        data = {"name": name, "args": args, "status": status,
                "latency_ms": round(latency, 1) if latency is not None else None, "msg_id": spec.msg_id,
                "undo": undo, **result}
        ev = self.hub.emit(Event("B", "command", "command_result", data=data, ts=time.time()))
        self.hub.store.add_command(ts, ev.t, name, args, status, data["latency_ms"], result, ev.experiment_id)
        return data
