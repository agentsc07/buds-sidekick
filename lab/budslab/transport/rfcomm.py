"""RFCOMM (SPP) transports: macOS via IOBluetooth (pyobjc), Linux via AF_BLUETOOTH sockets.

Neither can be exercised without the real buds; `python -m budslab.probe` exists to validate the
link before the dashboard is trusted. Windows is not implemented (needs PyBluez/WinRT).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import subprocess
import sys
import time
import uuid as uuidlib
from pathlib import Path

from .base import OnData, OnState, SPP_UUID_NEW, Transport

log = logging.getLogger("budslab.rfcomm")


def make_rfcomm(address: str | None, channel: int | None = None, uuid: str = SPP_UUID_NEW,
                sdp_dump: Path | None = None) -> Transport:
    if sys.platform == "darwin":
        return MacRfcomm(address, channel, uuid, sdp_dump)
    if sys.platform.startswith("linux"):
        if not address or address == "auto":
            raise SystemExit("On Linux pass --device AA:BB:CC:DD:EE:FF (see `bluetoothctl devices`).")
        return LinuxRfcomm(address, channel, uuid, sdp_dump)
    raise SystemExit("RFCOMM transport is only implemented for macOS and Linux. "
                     "Windows needs a PyBluez/WinRT backend (see README).")


class _Backoff:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> float:
        self.n += 1
        return min(2 * self.n, 15)

    def reset(self) -> None:
        self.n = 0


# ------------------------------------------------------------------------- macOS
_DELEGATE_CLS = None


def _delegate_class():
    """Objective-C classes can only be defined once per process, so build it lazily and reuse it."""
    global _DELEGATE_CLS
    if _DELEGATE_CLS is not None:
        return _DELEGATE_CLS
    import objc
    from Foundation import NSObject

    class BudsLabRfcommDelegate(NSObject):
        owner = None

        def rfcommChannelOpenComplete_status_(self, ch, status):  # noqa: N802
            o = self.owner
            if o and o._loop:
                o._loop.call_soon_threadsafe(
                    lambda: o._open_result and not o._open_result.done() and o._open_result.set_result(status))

        # The explicit signature is essential: without it PyObjC does not deliver the data callback
        # (verified on real hardware: no bytes ever arrived until this was declared).
        @objc.typedSelector(b"v@:@^vQ")
        def rfcommChannelData_data_length_(self, ch, data, length):  # noqa: N802
            o = self.owner
            try:
                b = bytes(data[:length])
            except Exception:  # noqa: BLE001
                b = bytes(memoryview(data)[:length])
            if o and o._on_data:
                o._loop.call_soon_threadsafe(o._on_data, b)

        def rfcommChannelClosed_(self, ch):  # noqa: N802
            o = self.owner
            if o and o._loop:
                o._loop.call_soon_threadsafe(lambda: o._closed_evt and o._closed_evt.set())

    _DELEGATE_CLS = BudsLabRfcommDelegate
    return _DELEGATE_CLS


class MacRfcomm(Transport):
    name = "macos-iobluetooth"

    def __init__(self, address: str | None, channel: int | None, uuid: str, sdp_dump: Path | None) -> None:
        self.address = None if address in (None, "auto") else address.replace(":", "-").lower()
        self.channel, self.uuid, self.sdp_dump = channel, uuid, sdp_dump
        self._chan = None
        self._delegate = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_data: OnData | None = None
        self._closed_evt: asyncio.Event | None = None
        self._open_result: asyncio.Future | None = None
        self.resolved: dict = {}

    def describe(self) -> dict:
        return {"name": self.name, "address": self.address, "uuid": self.uuid, **self.resolved}

    # -- main run loop (see budslab/runloop.py) ---------------------------------
    def _call(self, fn):
        """Run fn on the IOBluetooth thread and await its result."""
        fut = self._loop.create_future()

        def wrapper():
            try:
                res = fn()
                self._loop.call_soon_threadsafe(lambda: fut.done() or fut.set_result(res))
            except Exception as exc:  # noqa: BLE001
                self._loop.call_soon_threadsafe(lambda: fut.done() or fut.set_exception(exc))
        from .. import runloop
        runloop.post(wrapper)
        return fut

    # -- helpers ------------------------------------------------------------------
    def _make_delegate(self):
        cls = _delegate_class()
        d = cls.alloc().init()
        d.owner = self
        return d

    def _find_address(self) -> str:
        from IOBluetooth import IOBluetoothDevice
        devs = IOBluetoothDevice.pairedDevices() or []
        names = []
        for d in devs:
            n = d.name() or ""
            names.append(n)
            if re.search(r"buds\s*fe|sm-r400", n, re.I):
                self.resolved["device_name"] = n
                return d.addressString()
        raise RuntimeError(f"no paired 'Buds FE' found (paired: {names}). Pair the buds in System Settings "
                           "> Bluetooth or pass --device AA:BB:CC:DD:EE:FF")

    def _dump_sdp(self, dev) -> list[dict]:
        out = []
        try:
            for rec in dev.services() or []:
                item: dict = {"name": None, "rfcomm_channel": None, "uuids": []}
                try:
                    item["name"] = rec.getServiceName()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    st, ch = rec.getRFCOMMChannelID_(None)
                    if st == 0:
                        item["rfcomm_channel"] = int(ch)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    el = str(rec.getAttributeDataElement_(0x0001))
                    for kind, hexs in re.findall(r"uuid(128|32|16)\(([0-9a-f ]+)\)", el):
                        raw = bytes.fromhex(hexs.replace(" ", ""))
                        item["uuids"].append(str(uuidlib.UUID(bytes=raw)) if kind == "128" else "0x" + raw.hex())
                except Exception:  # noqa: BLE001
                    item["uuids_error"] = True
                out.append(item)
        except Exception:  # noqa: BLE001
            log.exception("SDP dump failed")
        return out

    def _resolve_channel(self, dev) -> int:
        """Runs on the IOBluetooth thread."""
        from IOBluetooth import IOBluetoothSDPUUID
        if self.channel:
            return self.channel
        u = IOBluetoothSDPUUID.uuidWithBytes_length_(uuidlib.UUID(self.uuid).bytes, 16)
        rec = dev.getServiceRecordForUUID_(u)
        if rec is None:
            dev.performSDPQuery_(None)
            t_end = time.time() + 6
            from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop
            while time.time() < t_end and rec is None:
                NSRunLoop.currentRunLoop().runMode_beforeDate_(NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.1))
                rec = dev.getServiceRecordForUUID_(u)
        sdp = self._dump_sdp(dev)
        self.resolved["sdp_records"] = sdp
        if self.sdp_dump:
            self.sdp_dump.write_text(json.dumps({"device": self.address, "records": sdp}, indent=2))
        if rec is None:
            raise RuntimeError(f"SDP: service {self.uuid} not found (see sdp.json / Protocol view). "
                               "Try --channel N from the SDP dump, or check no other app holds the link.")
        st, ch = rec.getRFCOMMChannelID_(None)
        if st != 0:
            raise RuntimeError(f"could not read RFCOMM channel from SDP record (status {st})")
        return int(ch)

    # -- Transport API ----------------------------------------------------------
    async def run(self, on_data: OnData, on_state: OnState) -> None:
        self._loop = asyncio.get_running_loop()
        self._on_data = on_data
        backoff = _Backoff()
        try:
            while True:
                on_state("connecting", {})
                try:
                    if not self.address:
                        self.address = await self._call(self._find_address)
                        self.address = self.address.replace(":", "-").lower()
                    from IOBluetooth import IOBluetoothDevice
                    dev = await self._call(lambda: IOBluetoothDevice.deviceWithAddressString_(self.address))
                    if not await self._call(dev.isConnected):
                        rc = await self._call(dev.openConnection)
                        if rc != 0:
                            raise RuntimeError(
                                f"the buds are NOT connected to this Mac and it could not connect (IOReturn {rc}). "
                                "Open System Settings > Bluetooth and click Connect on the buds (they are probably "
                                "connected to your phone, or in the case). Turn the phone's Bluetooth off first.")
                    channel = await self._call(lambda: self._resolve_channel(dev))
                    self.resolved["rfcomm_channel"] = channel
                    self._delegate = self._make_delegate()
                    self._closed_evt = asyncio.Event()
                    self._open_result = self._loop.create_future()

                    def open_chan():
                        st, ch = dev.openRFCOMMChannelAsync_withChannelID_delegate_(None, channel, self._delegate)
                        return st, ch
                    st, self._chan = await self._call(open_chan)
                    if st != 0:
                        raise RuntimeError(f"openRFCOMMChannelAsync failed (IOReturn {st})")
                    status = await self._wait_open()
                    if status != 0:
                        raise RuntimeError(f"RFCOMM open completed with error (IOReturn {status}). "
                                           "Another client (phone/Galaxy Wearable) may hold the channel.")
                    self.connected = True
                    backoff.reset()
                    on_state("connected", self.describe())
                    while not self._closed_evt.is_set():
                        try:
                            await asyncio.wait_for(self._closed_evt.wait(), 2)
                        except asyncio.TimeoutError:
                            if not await self._call(dev.isConnected):
                                break
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError:
                    on_state("error", {"error": "timed out opening RFCOMM (15 s): another client may hold the "
                                                "channel, or the buds are in the case / out of range"})
                except Exception as exc:  # noqa: BLE001
                    on_state("error", {"error": str(exc) or repr(exc)})
                finally:
                    was = self.connected
                    self.connected = False
                    await self._close_channel()
                    if was:
                        on_state("disconnected", {})
                await asyncio.sleep(backoff.next())
        finally:
            await self._close_channel()

    async def _wait_open(self) -> int:
        """Wait for the open callback; also poll isOpen() in case callbacks are not delivered."""
        end = time.time() + 15
        while time.time() < end:
            if self._open_result.done():
                return self._open_result.result()
            ch = self._chan
            if ch is not None and await self._call(ch.isOpen):
                return 0
            await asyncio.sleep(0.4)
        raise asyncio.TimeoutError()

    async def _close_channel(self) -> None:
        ch, self._chan = self._chan, None
        if ch is not None and self._loop:
            try:
                await asyncio.wait_for(self._call(lambda: ch.closeChannel()), 3)
            except Exception:  # noqa: BLE001
                pass

    async def send(self, data: bytes) -> None:
        if not self._chan or not self.connected:
            raise ConnectionError("RFCOMM not connected")
        ch = self._chan
        rc = await self._call(lambda: ch.writeSync_length_(data, len(data)))
        if rc != 0:
            raise ConnectionError(f"RFCOMM write failed (IOReturn {rc})")

    async def close(self) -> None:
        await self._close_channel()


# ------------------------------------------------------------------------- Linux
class LinuxRfcomm(Transport):
    name = "linux-rfcomm-socket"

    def __init__(self, address: str, channel: int | None, uuid: str, sdp_dump: Path | None) -> None:
        self.address, self.channel, self.uuid, self.sdp_dump = address, channel, uuid, sdp_dump
        self._sock: socket.socket | None = None
        self.resolved: dict = {}

    def describe(self) -> dict:
        return {"name": self.name, "address": self.address, "uuid": self.uuid, **self.resolved}

    def _sdp_channel(self) -> int | None:
        try:
            out = subprocess.run(["sdptool", "browse", self.address], capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        records = []
        for block in out.split("Service Name:")[1:]:
            ch = re.search(r"Channel:\s*(\d+)", block)
            records.append({"name": block.splitlines()[0].strip(), "rfcomm_channel": int(ch.group(1)) if ch else None,
                            "uuids": re.findall(r"UUID 128:\s*([0-9a-f-]+)", block)})
        self.resolved["sdp_records"] = records
        if self.sdp_dump:
            self.sdp_dump.write_text(json.dumps({"device": self.address, "records": records}, indent=2))
        for r in records:
            if self.uuid.lower() in [u.lower() for u in r["uuids"]] and r["rfcomm_channel"]:
                return r["rfcomm_channel"]
        return None

    def _connect_blocking(self) -> socket.socket:
        channels = [self.channel] if self.channel else []
        if not channels:
            ch = self._sdp_channel()
            channels = [ch] if ch else list(range(1, 13))   # fall back to probing
        last: Exception | None = None
        for ch in channels:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.settimeout(8)
            try:
                s.connect((self.address, ch))
                s.settimeout(None)
                self.resolved["rfcomm_channel"] = ch
                return s
            except OSError as exc:
                last = exc
                s.close()
        raise ConnectionError(f"could not open RFCOMM to {self.address}: {last}")

    async def run(self, on_data: OnData, on_state: OnState) -> None:
        loop = asyncio.get_running_loop()
        backoff = _Backoff()
        try:
            while True:
                on_state("connecting", {})
                try:
                    self._sock = await loop.run_in_executor(None, self._connect_blocking)
                    self.connected = True
                    backoff.reset()
                    on_state("connected", self.describe())
                    sock = self._sock
                    while True:
                        data = await loop.run_in_executor(None, sock.recv, 1024)
                        if not data:
                            break
                        on_data(data)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    on_state("error", {"error": str(exc) or repr(exc)})
                finally:
                    was = self.connected
                    self.connected = False
                    if self._sock:
                        try:
                            self._sock.close()
                        except OSError:
                            pass
                        self._sock = None
                    if was:
                        on_state("disconnected", {})
                await asyncio.sleep(backoff.next())
        finally:
            if self._sock:
                self._sock.close()

    async def send(self, data: bytes) -> None:
        if not self._sock or not self.connected:
            raise ConnectionError("RFCOMM not connected")
        await asyncio.get_running_loop().run_in_executor(None, self._sock.sendall, data)

    async def close(self) -> None:
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
