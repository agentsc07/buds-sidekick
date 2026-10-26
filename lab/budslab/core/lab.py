"""Lab: wires transport, decoding, state, store, runner and commands together."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..protocol import commands as C
from ..protocol.frames import Frame, FrameCodec, Junk
from ..protocol.messages import decode
from ..transport.base import Transport
from ..transport.simulator import SimStandard, SimTransport, SimWorld
from ..transport.standard import StandardSource, make_standard
from .commands import CommandService
from .events import Event
from .experiments import Runner, load_catalog
from .hub import Hub
from .state import DeviceState
from .store import Store

log = logging.getLogger("budslab")


@dataclass
class Config:
    data_dir: Path = Path("data")
    catalog: Path = Path("experiments.yaml")
    simulate: bool = False
    replay: Path | None = None
    sim_speed: float = 1.0
    device: str | None = "auto"
    channel: int | None = None
    handshake: bool = False          # send MANAGER_INFO once after connect (off: fully passive)
    pretend_samsung: bool = False
    legacy_framing: bool = False     # only if the probe shows the FE uses the older SOM 0xFE framing


class Lab:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.mode = "replay" if cfg.replay else "simulator" if cfg.simulate else "hardware"
        self.session_id = time.strftime("%Y%m%d-%H%M%S")
        self.store = Store(cfg.data_dir, self.session_id, self.mode, cfg.device or "")
        self.hub = Hub(self.store)
        self.state = DeviceState()
        self.codec = FrameCodec(*( (0xFE, 0xEE, True) if cfg.legacy_framing else () ))
        self.rx_codec = FrameCodec(*( (0xFE, 0xEE, True) if cfg.legacy_framing else () ))
        self.link = "disconnected"
        self.link_info: dict = {}
        self._idle_seen: dict[int, list[float]] = defaultdict(list)
        self.world: SimWorld | None = None
        self.transport: Transport = self._make_transport()
        self.standard: StandardSource | None = None
        self.commands = CommandService(self.hub, self.state, self.codec, self._send_bytes,
                                       lambda: self.transport.connected, self._log_tx)
        self.catalog = load_catalog(cfg.catalog)
        self.runner = Runner(self.hub, self.catalog, self.commands, self.is_background,
                             sim_notify=(lambda e: self.world.on_experiment(e.id)) if self.world else None)
        self._tasks: list[asyncio.Task] = []
        self.discovery: dict = {}
        self.hub.listeners.append(self._on_event_for_idle)

    # -- setup --------------------------------------------------------------------
    def _make_transport(self) -> Transport:
        if self.cfg.simulate or self.cfg.replay:
            self.world = SimWorld(speed=self.cfg.sim_speed)
            return SimTransport(self.world, self.cfg.replay)
        from ..transport.rfcomm import make_rfcomm
        return make_rfcomm(self.cfg.device, self.cfg.channel, sdp_dump=self.store.session_dir / "sdp.json")

    async def start(self) -> None:
        self.hub.emit(Event("S", "lab", "system", data={"event": "session_start", "mode": self.mode,
                                                        "transport": self.transport.describe()}))
        if self.world:
            self.standard = SimStandard(self.hub.emit, self.world)
        else:
            self.standard = make_standard(self.hub.emit, lambda: getattr(self.transport, "address", None))
        self.runner.start()
        self._tasks.append(asyncio.create_task(self.transport.run(self._on_bytes, self._on_link), name="transport"))
        if self.standard:
            self._tasks.append(asyncio.create_task(self.standard.run(), name="layer-a"))

    async def stop(self) -> None:
        if self.commands.find_my_active and self.commands.enabled:
            try:
                await self.commands.send("find_my_stop", {}, confirm=True, undo=True)
            except Exception:  # noqa: BLE001
                pass
        await self.runner.stop()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await self.transport.close()
        except Exception:  # noqa: BLE001
            pass
        self.hub.emit(Event("S", "lab", "system", data={"event": "session_end"}))
        self.store.close()

    # -- link / bytes ----------------------------------------------------------------
    def _on_link(self, state: str, info: dict) -> None:
        self.link, self.link_info = state, info
        if state in ("connected", "disconnected"):
            self.rx_codec.reset()
        self.hub.emit(Event("A" if state != "error" else "S", "rfcomm", "conn",
                            data={"event": state, **{k: v for k, v in info.items() if k != "sdp_records"}}))
        if state == "connected" and self.cfg.handshake:
            asyncio.get_running_loop().create_task(self._handshake())
        self.hub.broadcast({"kind": "status"})

    async def _handshake(self) -> None:
        payload = C.manager_info_payload(self.cfg.pretend_samsung)
        raw = self.codec.encode(C.MANAGER_INFO, payload)
        self._log_tx(raw, Frame(C.MANAGER_INFO, payload, False, False, True, raw), "handshake")
        await self._send_bytes(raw)

    async def _send_bytes(self, data: bytes) -> None:
        # Last line of defence: nothing leaves this process unless every frame in it is allowlisted.
        for f in FrameCodec(self.codec.som, self.codec.eom, self.codec.legacy).feed(data):
            if not isinstance(f, Frame):
                raise C.CommandError("refusing to send unparseable bytes")
            C.check_tx_id(f.msg_id)
        await self.transport.send(data)

    def _log_tx(self, raw: bytes, f: Frame, why: str) -> None:
        self.hub.counters["frames_tx"] += 1
        self.hub.emit(Event("B", "host", "frame", data={
            "dir": "tx", "msg_id": f.msg_id, "name": decode(f).name, "known": True, "why": why, "size": len(raw),
            "payload_hex": f.payload.hex(), "crc_ok": True}, raw_hex=raw.hex()))

    def _on_bytes(self, data: bytes) -> None:
        ts = time.time()
        for item in self.rx_codec.feed(data):
            if isinstance(item, Junk):
                self.hub.emit(Event("C", "rfcomm", "frame", data={"dir": "rx", "junk": True, "reason": item.reason,
                                                                   "msg_id": -1, "known": False,
                                                                   "size": len(item.raw)}, raw_hex=item.raw_hex, ts=ts))
                continue
            d = decode(item)
            self.hub.counters["frames_rx"] += 1
            self.hub.emit(Event("B" if d.known else "C", "samsung-spp", "frame", data={
                "dir": "rx", "msg_id": item.msg_id, "name": d.name, "known": d.known, "confidence": d.confidence,
                "crc_ok": item.crc_ok, "type_bit": item.type_bit, "flags": f"0x{item.flags:04x}", "size": len(item.raw),
                "payload_hex": item.payload.hex(), "fields": d.fields, "error": d.error}, raw_hex=item.raw_hex, ts=ts))
            if item.crc_ok:
                for ev in self.state.update(d, ts):
                    self.hub.emit(ev)
                self.commands.on_frame(item)

    # -- background (periodic) unknown ids -------------------------------------------
    def _on_event_for_idle(self, ev: Event) -> None:
        if ev.type == "frame" and ev.data.get("dir") == "rx" and not ev.data.get("known") and not ev.experiment_id:
            lst = self._idle_seen[ev.data.get("msg_id", -1)]
            lst.append(ev.ts)
            del lst[:-6]

    def is_background(self, msg_id: int) -> bool:
        """An undecoded ID seen >=3 times while no experiment was armed is treated as periodic noise."""
        recent = [t for t in self._idle_seen.get(msg_id, []) if time.time() - t < 600]
        return len(recent) >= 3

    # -- status ----------------------------------------------------------------------
    def status(self) -> dict:
        return {
            "session_id": self.session_id, "mode": self.mode, "t0": self.hub.t0, "server_now": time.time(),
            "link": self.link, "link_info": {k: v for k, v in self.link_info.items() if k != "sdp_records"},
            "transport": self.transport.describe() if self.mode == "hardware" else self.transport.describe(),
            "commands_enabled": self.commands.enabled, "find_my_active": self.commands.find_my_active,
            "counters": self.hub.counters, "device_state": self.state.snapshot(),
            "layer_a": getattr(self.standard, "status", {}) if self.standard else {"info": "no Layer A source"},
            "status_interval_s": (sum(self.state.status_intervals) / len(self.state.status_intervals)
                                  if self.state.status_intervals else None),
            "experiments_total": len(self.catalog),
            "experiments_verified": sum(1 for r in self.runner.results.values() if r["status"] == "VERIFIED"),
        }
