"""Simulator: a fake transport + Layer A source, so the dashboard works with no hardware.

Two modes
  * synthetic : behaves like a plausible FE. Periodic status frames, replies to allowlisted commands,
                and reacts to whichever guided experiment is armed (some experiments deliberately
                produce nothing / only undecodable traffic so every result state is exercised).
  * replay    : re-feeds the rx frames and Layer A events of a recorded raw.jsonl at original timing.

The synthetic behaviour is a guess at the FE, NOT evidence about it. Results produced in simulator
sessions are flagged `simulated` and are never counted as Confirmed in protocol-findings.md.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Callable

from ..core.events import Event
from ..protocol import commands as C
from ..protocol.frames import Frame, FrameCodec
from ..protocol.messages import (EXTENDED_STATUS_UPDATED, NOISE_CONTROLS_UPDATE, RESP, TOUCH_UPDATED,
                                 UNIVERSAL_ACK)
from .base import OnData, OnState, Transport
from .standard import StandardSource

# Real ExtendedStatusUpdate payload from a Buds FE (rev 2), used as the template for synthetic frames.
_TEMPLATE = bytes.fromhex(
    "0206" "3a59" "0100" "1100" "0000" "8f33" "0000" "4a01" "4a01" "0300" "0465" "0001" "0010" "0000"
    "0101" "1103" "0000" "0000" "e803" "0000" "9d0e" "1d00" "5000")
assert len(_TEMPLATE) == 46

NOISE = {"off": 0, "anc": 1, "ambient": 2}


class SimWorld:
    def __init__(self, speed: float = 1.0, seed: int | None = 7) -> None:
        self.k = 1.0 / speed
        self.rnd = random.Random(seed)
        self.codec = FrameCodec()
        self.placement = {"L": 1, "R": 1}
        self.battery = {"L": 58, "R": 89, "case": 60}
        self.noise = 0
        self.locked = False
        self.eq = 0
        self.charging_case = False
        self.on_frame: Callable[[bytes], None] = lambda b: None
        self.emit_a: Callable[[Event], None] = lambda e: None
        self.connected = False
        self.tasks: set[asyncio.Task] = set()
        self.reject = {"ambient_volume"}          # commands the fake FE refuses (exercises the rejected path)
        self.ack_style = {"ambient_volume": "ack"}

    # -- frame builders -----------------------------------------------------------
    def status_payload(self) -> bytes:
        p = bytearray(_TEMPLATE)
        p[2], p[3], p[7] = self.battery["L"], self.battery["R"], self.battery["case"]
        p[6] = (self.placement["L"] << 4) | self.placement["R"]
        p[10] = 0x0F | (0 if self.locked else 0x80)
        p[12] = self.noise
        p[9] = self.eq
        p[43] = 1 if self.charging_case else 0
        return bytes(p)

    def send_status(self) -> None:
        self.on_frame(self.codec.encode(EXTENDED_STATUS_UPDATED, self.status_payload(), type_bit=True))

    def send(self, msg_id: int, payload: bytes, type_bit: bool = True) -> None:
        self.on_frame(self.codec.encode(msg_id, payload, type_bit=type_bit))

    # -- scheduling -----------------------------------------------------------------
    def at(self, delay: float, fn: Callable[[], None]) -> None:
        async def _run():
            await asyncio.sleep(delay * self.k)
            if self.connected:
                fn()
        t = asyncio.get_running_loop().create_task(_run())
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    def set_place(self, side: str, val: int) -> None:
        self.placement[side] = val
        self.send_status()

    def media(self, key: str) -> None:
        self.emit_a(Event("A", "sim-media-key", "media_key", data={"key": key, "code": 0, "repeat": False}))

    # -- experiment reactions --------------------------------------------------------
    def on_experiment(self, exp_id: str) -> None:
        j = lambda a=0.8, b=1.6: self.rnd.uniform(a, b)   # noqa: E731
        w = self
        tap = lambda side, code: w.send(45, bytes([1 if side == "L" else 0, code, 0x20, 0xD9]))  # noqa: E731
        gestures = {"single": 1, "double": 2, "triple": 3}
        if exp_id.startswith("touch-") and exp_id.split("-")[1] in gestures and exp_id.endswith(("-l", "-r")):
            w.at(j(), lambda: tap(exp_id[-1].upper(), gestures[exp_id.split("-")[1]]))
        elif exp_id in ("touch-hold-l", "touch-hold-r"):
            side = exp_id[-1].upper()
            w.at(j(), lambda: tap(side, 5))
            w.at(j(1.6, 2.2), lambda: tap(side, 7))
        elif exp_id in ("touch-tap-playing", "touch-tap-paused"):
            w.at(j(), lambda: tap("L", 1))
        elif exp_id in ("wear-remove-l", "wear-remove-r"):
            s = "L" if exp_id.endswith("l") else "R"
            w.at(j(), lambda: w.set_place(s, 2))
            w.at(j(2.4, 3.2), lambda: w.set_place(s, 1))
        elif exp_id == "wear-remove-both":
            w.at(j(), lambda: (w.set_place("L", 2), w.set_place("R", 2)))
            w.at(j(2.4, 3.2), lambda: (w.set_place("L", 1), w.set_place("R", 1)))
        elif exp_id in ("wear-cover-prox-l", "wear-cover-prox-r"):
            s = "L" if exp_id.endswith("l") else "R"
            w.at(0.1, lambda: w.set_place(s, 2))
            w.at(j(1.2, 2.0), lambda: w.set_place(s, 1))
        elif exp_id == "case-hall":
            w.at(j(), lambda: w.set_place("L", 3))
            w.at(j(2.5, 3.0), lambda: w.send(0xF2, bytes([1])))     # pretend lid message (unknown to decoders)
        elif exp_id == "wear-one-out-of-case":
            w.at(0.05, lambda: w.set_place("L", 3))
            w.at(j(1.5, 2.2), lambda: w.set_place("L", 2))
        elif exp_id in ("case-open", "case-close"):
            w.at(j(), lambda: w.send(0xF1, bytes([1 if exp_id == "case-open" else 0])))
        elif exp_id == "case-usb-plug":
            w.at(j(), lambda: (setattr(w, "charging_case", True), w.send_status()))
        elif exp_id == "case-usb-unplug":
            w.at(j(), lambda: (setattr(w, "charging_case", False), w.send_status()))
        elif exp_id == "noise-touch-hold":
            w.at(j(), lambda: w._set_noise((w.noise + 1) % 3))
        elif exp_id == "audio-start-music":
            w.at(j(), lambda: w.emit_a(Event("A", "sim-coreaudio", "audio",
                                             data={"event": "route", "output_default": True, "input_default": False,
                                                   "output_rate": "44100"})))
        elif exp_id == "discovery-freeform":
            w.at(j(), lambda: w.send(0xF3, bytes([9, 9, 9])))
        # touch-swipe, audio-pause/codec/call, touch-tap-call: nothing (NOT_OBSERVED)

    def _set_noise(self, mode: int) -> None:
        self.noise = mode
        self.send(NOISE_CONTROLS_UPDATE, bytes([mode]))

    # -- commands from the host --------------------------------------------------------
    def on_tx(self, data: bytes) -> None:
        for f in FrameCodec().feed(data):
            if not isinstance(f, Frame) or not f.crc_ok:
                continue
            C_by_id = {c.msg_id: c for c in C.COMMANDS.values()}
            spec = C_by_id.get(f.msg_id)
            if spec is None:
                continue                                        # handshake responses etc.: silently accepted
            delay = self.rnd.uniform(0.03, 0.12)

            def reply(spec=spec, f=f):
                if spec.name in self.reject:
                    if self.ack_style.get(spec.name) == "ack":
                        self.send(RESP, bytes([f.msg_id, 6]), type_bit=False)
                    return
                if spec.name == "noise_control":
                    self._set_noise(f.payload[0])
                elif spec.name == "lock_touchpad":
                    self.locked = f.payload[0] == 0
                    self.send(TOUCH_UPDATED, bytes([1 if self.locked else 0]))
                elif spec.name == "equalizer":
                    self.eq = f.payload[0]
                self.send(RESP, bytes([f.msg_id, 0]), type_bit=False)
            self.at(delay, reply)


class SimTransport(Transport):
    name = "simulator"

    def __init__(self, world: SimWorld, replay: Path | None = None) -> None:
        self.world, self.replay = world, replay

    def describe(self) -> dict:
        return {"name": self.name, "mode": "replay" if self.replay else "synthetic", "file": str(self.replay or "")}

    async def run(self, on_data: OnData, on_state: OnState) -> None:
        w = self.world
        w.on_frame = on_data
        on_state("connecting", {})
        await asyncio.sleep(0.2 * w.k)
        w.connected = self.connected = True
        on_state("connected", self.describe())
        try:
            if self.replay:
                await self._replay(on_data)
                await asyncio.Event().wait()
            w.send_status()
            while True:
                await asyncio.sleep(5 * w.k)
                for side in ("L", "R"):
                    if w.rnd.random() < 0.15 and w.battery[side] > 1:
                        w.battery[side] -= 1
                w.send_status()
        finally:
            w.connected = self.connected = False
            for t in list(w.tasks):
                t.cancel()

    async def _replay(self, on_data: OnData) -> None:
        rows = [json.loads(l) for l in Path(self.replay).read_text().splitlines() if l.strip()]
        rows = [r for r in rows if (r["type"] == "frame" and r["data"].get("dir") == "rx" and r.get("raw_hex"))
                or (r["layer"] == "A" and r["type"] in ("media_key", "audio"))]
        if not rows:
            return
        t0 = rows[0]["ts"]
        start = time.time()
        for r in rows:
            await asyncio.sleep(max(0.0, (r["ts"] - t0) * self.world.k - (time.time() - start)))
            if r["layer"] == "A":
                self.world.emit_a(Event("A", "replay-" + r["source"], r["type"], r.get("side"), r["data"]))
            else:
                on_data(bytes.fromhex(r["raw_hex"]))

    async def send(self, data: bytes) -> None:
        if not self.connected:
            raise ConnectionError("simulator not connected")
        if not self.replay:
            self.world.on_tx(data)


class SimStandard(StandardSource):
    def __init__(self, emit, world: SimWorld) -> None:
        super().__init__(emit)
        world.emit_a = emit
        self._sys("sim", "simulated Layer A", True)

    async def run(self) -> None:
        await asyncio.Event().wait()
