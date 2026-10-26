"""Buds -> gesture tokens. Reuses the lab's transport, frame codec, decoders and state tracker."""
from __future__ import annotations

import asyncio
import time
from typing import Callable

from budslab.core.state import DeviceState
from budslab.protocol.frames import Frame, FrameCodec
from budslab.protocol.messages import decode

Token = str   # "L:single" | "R:double" | "L:hold_start" | ...


class BudsLink:
    def __init__(self, transport, on_token: Callable[[Token], None], log: Callable[[str], None] = print,
                 on_event: Callable | None = None) -> None:
        self.transport, self.on_token, self.log, self.on_event = transport, on_token, log, on_event
        self.codec, self.state = FrameCodec(), DeviceState()

    async def run(self) -> None:
        await self.transport.run(self._on_bytes, self._on_link)

    def _on_link(self, state: str, info: dict) -> None:
        if state in ("connected", "disconnected"):
            self.codec.reset()
        self.log(f"buds: {state}" + (f" ({info['error']})" if state == "error" else ""))

    def _on_bytes(self, data: bytes) -> None:
        ts = time.time()
        for item in self.codec.feed(data):
            if not isinstance(item, Frame) or not item.crc_ok:
                continue
            for ev in self.state.update(decode(item), ts):
                if self.on_event:
                    self.on_event(ev)
                if ev.type == "touch" and ev.data.get("event") == "gesture" and ev.side:
                    self.on_token(f"{ev.side}:{ev.data['gesture']}")

    def battery(self) -> dict | None:
        s = self.state.snapshot()
        if "battery_l" not in s:
            return None
        return {"left": s["battery_l"], "right": s["battery_r"], "case": s.get("battery_case", 0)}


async def keyboard_gestures(on_token: Callable[[Token], None]) -> None:
    """Dev mode without buds. Type e.g.  `L double`, `R single`, `L hold 3` (hold for 3 s)."""
    loop = asyncio.get_running_loop()
    print("keyboard mode: type gestures like  L double | R single | L triple | L hold 3   (Ctrl-D to quit)")
    while True:
        line = await loop.run_in_executor(None, input, "gesture> ")
        parts = line.split()
        if len(parts) < 2 or parts[0].upper() not in ("L", "R"):
            print("   format: <L|R> <single|double|triple|hold [seconds]>")
            continue
        side, g = parts[0].upper(), parts[1].lower()
        if g == "hold":
            on_token(f"{side}:hold_start")
            await asyncio.sleep(float(parts[2]) if len(parts) > 2 else 3.0)
            on_token(f"{side}:hold_end")
        else:
            on_token(f"{side}:{g}")
