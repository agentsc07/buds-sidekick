"""Layer A: standard Bluetooth / OS level signals.

macOS implementation:
  * connection state   - IOBluetoothDevice.isConnected() polled every 2 s
  * AVRCP media keys   - a listen-only CGEventTap for system-defined (media key) events. Needs
                         Terminal/your IDE in System Settings > Privacy & Security > Input Monitoring.
  * audio route        - `system_profiler SPAudioDataType` polled every 5 s: is the buds' output/input
                         the default device, and at what sample rate (44.1/48 kHz ~ A2DP, 8/16 kHz ~ HFP)

A2DP codec / stream state and HFP call events are NOT exposed by public macOS APIs; those experiments
will report NOT_OBSERVED on macOS (documented in the README). Linux (BlueZ D-Bus) is not implemented.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import threading
import time
from typing import Callable

from ..core.events import Event

log = logging.getLogger("budslab.standard")

MEDIA_KEYS = {16: "play_pause", 17: "next", 18: "previous", 19: "fast_forward", 20: "rewind",
              0: "volume_up", 1: "volume_down", 7: "mute"}


class StandardSource:
    """Base: emits Layer A events through `emit`."""

    def __init__(self, emit: Callable[[Event], None]) -> None:
        self.emit = emit
        self.status: dict[str, str] = {}

    async def run(self) -> None:  # pragma: no cover - overridden
        await asyncio.Event().wait()

    def _sys(self, source: str, msg: str, ok: bool) -> None:
        self.status[source] = "ok" if ok else msg
        self.emit(Event("S", source, "system", data={"event": "layer_a_source", "ok": ok, "message": msg}))


class MacStandard(StandardSource):
    def __init__(self, emit, address_getter: Callable[[], str | None], name_hint: str = "Buds FE") -> None:
        super().__init__(emit)
        self.address_getter, self.name_hint = address_getter, name_hint
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_conn: bool | None = None
        self._last_route: dict | None = None

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        threading.Thread(target=self._media_key_thread, name="mediakeys", daemon=True).start()
        await asyncio.gather(self._poll_connection(), self._poll_audio())

    # -- connection -----------------------------------------------------------------
    def _is_connected(self) -> bool | None:
        try:
            from IOBluetooth import IOBluetoothDevice
            addr = self.address_getter()
            dev = IOBluetoothDevice.deviceWithAddressString_(addr) if addr else None
            if dev is None:
                for d in IOBluetoothDevice.pairedDevices() or []:
                    if self.name_hint.lower() in (d.name() or "").lower():
                        dev = d
                        break
            return bool(dev.isConnected()) if dev is not None else None
        except Exception:  # noqa: BLE001
            return None

    async def _poll_connection(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            c = await loop.run_in_executor(None, self._is_connected)
            if c is not None and c != self._last_conn:
                self.emit(Event("A", "iobluetooth", "conn", data={"event": "connected" if c else "disconnected",
                                                                     "initial": self._last_conn is None}))
                self._last_conn = c
            await asyncio.sleep(2)

    # -- audio route ----------------------------------------------------------------
    def _audio_route(self) -> dict | None:
        try:
            out = subprocess.run(["system_profiler", "SPAudioDataType", "-json"], capture_output=True, text=True,
                                 timeout=15).stdout
            items = json.loads(out)["SPAudioDataType"][0].get("_items", [])
        except Exception:  # noqa: BLE001
            return None
        route = {"output_default": False, "input_default": False, "output_rate": None, "input_rate": None}
        for it in items:
            if self.name_hint.lower() not in it.get("_name", "").lower():
                continue
            if it.get("coreaudio_default_audio_output_device") == "spaudio_yes":
                route["output_default"], route["output_rate"] = True, it.get("coreaudio_device_srate")
            if it.get("coreaudio_default_audio_input_device") == "spaudio_yes":
                route["input_default"], route["input_rate"] = True, it.get("coreaudio_device_srate")
        return route

    async def _poll_audio(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            r = await loop.run_in_executor(None, self._audio_route)
            if r is not None and r != self._last_route:
                first = self._last_route is None
                self._last_route = r
                kind = "hfp" if r["input_default"] else "route"
                self.emit(Event("A", "coreaudio", "audio", data={"event": kind, **r, "initial": first}))
            await asyncio.sleep(5)

    # -- media keys -----------------------------------------------------------------
    def _media_key_thread(self) -> None:
        try:
            import Quartz
            from AppKit import NSEvent
        except ImportError:
            self._post_status("Quartz/AppKit not installed (pip install pyobjc-framework-Quartz)", False)
            return

        def cb(proxy, etype, event, refcon):
            try:
                if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                    Quartz.CGEventTapEnable(tap, True)
                    return event
                ns = NSEvent.eventWithCGEvent_(event)
                if ns is not None and ns.subtype() == 8:
                    d1 = ns.data1()
                    code, flags = (d1 & 0xFFFF0000) >> 16, d1 & 0xFFFF
                    down = ((flags & 0xFF00) >> 8) == 0xA
                    key = MEDIA_KEYS.get(code)
                    if key and down:
                        ev = Event("A", "media-key-tap", "media_key",
                                   data={"key": key, "code": code, "repeat": bool(flags & 1)})
                        self._loop.call_soon_threadsafe(self.emit, ev)
            except Exception:  # noqa: BLE001
                log.exception("media key callback")
            return event

        tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                      Quartz.kCGEventTapOptionListenOnly, 1 << 14, cb, None)
        if tap is None:
            self._post_status("media keys unavailable: grant Input Monitoring to your terminal/IDE "
                              "(System Settings > Privacy & Security), then restart", False)
            return
        src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self._post_status("media key tap active", True)
        Quartz.CFRunLoopRun()

    def _post_status(self, msg: str, ok: bool) -> None:
        self._loop.call_soon_threadsafe(self._sys, "media-key-tap", msg, ok)


def make_standard(emit, address_getter) -> StandardSource | None:
    if sys.platform == "darwin":
        return MacStandard(emit, address_getter)
    return None   # Linux/Windows Layer A: not implemented (see README)
