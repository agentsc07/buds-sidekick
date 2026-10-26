"""Galaxy Buds SPP framing.

Frame layout for the Buds2-era / FE family (per community notes, verified against a
real Buds FE ExtendedStatusUpdate frame in tests/):

    SOM(0xFD) | header(2, LE) | msg_id | payload... | CRC16(2, LE) | EOM(0xDD)

    header  = size | flags;  size = 1 (id) + len(payload) + 2 (crc), low 10 bits
              0x2000 = fragment flag, 0x1000 = "type" bit (see `Frame.type_bit`)
    CRC16   = CRC-16/XMODEM (poly 0x1021, init 0) over msg_id + payload

Older models (Buds+ etc.) use SOM 0xFE / EOM 0xEE and a 1-byte type + 1-byte size header;
`FrameCodec(legacy=True)` supports that in case the probe shows the FE behaves that way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SOM = 0xFD
EOM = 0xDD
LEGACY_SOM = 0xFE
LEGACY_EOM = 0xEE

FLAG_TYPE = 0x1000
FLAG_FRAGMENT = 0x2000
SIZE_MASK = 0x03FF


def _make_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        table.append(crc & 0xFFFF)
    return table


_TABLE = _make_table()


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = _TABLE[((crc >> 8) ^ b) & 0xFF] ^ ((crc << 8) & 0xFFFF)
    return crc


@dataclass
class Frame:
    msg_id: int
    payload: bytes
    type_bit: bool = False      # header bit 0x1000. Set on frames the buds send unprompted
    fragment: bool = False      # and on frames the host sends as "responses" (per reference).
    crc_ok: bool = True
    raw: bytes = b""
    flags: int = 0              # all header bits above the 10-bit size (0x0800 was seen on a rev-3 FE frame)

    @property
    def raw_hex(self) -> str:
        return self.raw.hex()


@dataclass
class Junk:
    """Bytes that could not be parsed as a frame (kept for raw capture)."""
    raw: bytes
    reason: str

    @property
    def raw_hex(self) -> str:
        return self.raw.hex()


@dataclass
class FrameCodec:
    som: int = SOM
    eom: int = EOM
    legacy: bool = False
    _buf: bytearray = field(default_factory=bytearray, repr=False)

    # ---- encode -------------------------------------------------------------
    def encode(self, msg_id: int, payload: bytes = b"", *, type_bit: bool = False,
               fragment: bool = False) -> bytes:
        size = 1 + len(payload) + 2
        crc = crc16_xmodem(bytes([msg_id]) + payload)
        out = bytearray([self.som])
        if self.legacy:
            out += bytes([1 if type_bit else 0, size & 0xFF])
        else:
            header = size & SIZE_MASK
            if fragment:
                header |= FLAG_FRAGMENT
            if type_bit:
                header |= FLAG_TYPE
            out += header.to_bytes(2, "little")
        out.append(msg_id)
        out += payload
        out += crc.to_bytes(2, "little")
        out.append(self.eom)
        return bytes(out)

    # ---- decode -------------------------------------------------------------
    def feed(self, data: bytes) -> list[Frame | Junk]:
        """Feed raw stream bytes; returns complete frames (and junk) found so far."""
        self._buf += data
        out: list[Frame | Junk] = []
        while True:
            # resync to SOM
            idx = self._buf.find(self.som)
            if idx < 0:
                if self._buf:
                    out.append(Junk(bytes(self._buf), "no SOM"))
                    self._buf.clear()
                break
            if idx > 0:
                out.append(Junk(bytes(self._buf[:idx]), "bytes before SOM"))
                del self._buf[:idx]
            if len(self._buf) < 3:
                break
            if self.legacy:
                type_bit = bool(self._buf[1])
                fragment = False
                flags = 0
                size = self._buf[2]
            else:
                header = int.from_bytes(self._buf[1:3], "little")
                type_bit = bool(header & FLAG_TYPE)
                flags = header & 0xFC00
                fragment = bool(header & FLAG_FRAGMENT)
                size = header & SIZE_MASK
            total = 1 + 2 + size + 1
            if size < 3:
                out.append(Junk(bytes(self._buf[:1]), f"bad size {size}"))
                del self._buf[:1]
                continue
            if len(self._buf) < total:
                break
            raw = bytes(self._buf[:total])
            if raw[-1] != self.eom:
                out.append(Junk(raw[:1], "bad EOM"))
                del self._buf[:1]
                continue
            msg_id = raw[3]
            payload = raw[4:4 + size - 3]
            wire_crc = int.from_bytes(raw[total - 3:total - 1], "little")
            crc_ok = wire_crc == crc16_xmodem(bytes([msg_id]) + payload)
            out.append(Frame(msg_id, payload, type_bit, fragment, crc_ok, raw, flags))
            del self._buf[:total]
        return out

    def reset(self) -> None:
        self._buf.clear()
