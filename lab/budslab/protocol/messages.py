"""Message registry and decoders.

Decoders exist only for messages documented by the community reference for Buds2-family
devices. Unknown IDs decode to raw payloads and never raise. `confidence` here is what the
*reference* says; the findings generator upgrades a message to Confirmed once it has been
decoded from real hardware traffic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .frames import Frame
from .msg_ids import MSG_NAMES

# --- IDs we act on (names per reference) -------------------------------------------
STATUS_UPDATED = 96
EXTENDED_STATUS_UPDATED = 97
RESP = 81
UNIVERSAL_ACK = 66
NOISE_CONTROLS_UPDATE = 119
NOISE_CONTROLS = 120
TOUCH_UPDATED = 145
MUTE_EARBUD_STATUS_UPDATED = 163
AMBIENT_MODE_UPDATED = 129
VERSION_INFO = 99
MAIN_CHANGE = 112
DEBUG_SERIAL_NUMBER = 41
DEBUG_BUILD_INFO = 40
TOUCH_ON_BUDS = 45

PLACEMENT = {0: "disconnected", 1: "in_ear", 2: "out", 3: "case", 4: "case_charging?"}
NOISE_MODES = {0: "off", 1: "anc", 2: "ambient", 3: "adaptive"}
TOUCH_ACTIONS = {1: "voice_assistant", 2: "noise_control", 3: "volume", 4: "spotify", 5: "other_l", 6: "other_r"}
RESULT_CODES = {0: "SUCCESS", 1: "FAILED", 2: "FATAL_ERROR", 3: "NO_RESOURCES", 4: "RESOURCE_BUSY",
                5: "ERROR_TIMEOUT", 6: "NOT_FOUND", 7: "END_OF_STREAM", 8: "ALREADY_CREATED"}


@dataclass
class Decoded:
    msg_id: int
    name: str
    known: bool                       # a decoder exists
    confidence: str                   # "Likely" (from reference) | "Unknown"
    fields: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def name_of(msg_id: int) -> str:
    return MSG_NAMES.get(msg_id, f"UNKNOWN_{msg_id}")


def _bit(v: int, n: int) -> bool:
    return bool(v & (1 << n))


def _printable(b: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)


def _dec_status(p: bytes) -> dict:
    # rev, battL, battR, coupled, main, placement(hi=L, lo=R), case, charging
    f = {"revision": p[0], "battery_l": p[1], "battery_r": p[2], "coupled": bool(p[3]),
         "main": "L" if p[4] == 1 else "R", "placement_l": (p[5] >> 4) & 15, "placement_r": p[5] & 15,
         "battery_case": p[6]}
    if len(p) > 7:
        f.update(charging_l=_bit(p[7], 4), charging_r=_bit(p[7], 2), charging_case=_bit(p[7], 0))
    return f


def _dec_ext_status(p: bytes) -> dict:
    # Layout for Buds2 Pro / FE class devices; cross-checked with the reference's FE test frame.
    f: dict[str, Any] = {
        "revision": p[0], "battery_l": p[2], "battery_r": p[3], "coupled": bool(p[4]),
        "main": "L" if p[5] == 1 else "R", "placement_l": (p[6] >> 4) & 15, "placement_r": p[6] & 15,
        "battery_case": p[7], "adjust_sound_sync": bool(p[8]), "eq_mode": p[9],
    }
    lock = p[10]
    f.update(touch_hold_on=_bit(lock, 0), touch_triple_on=_bit(lock, 1), touch_double_on=_bit(lock, 2),
             touch_single_on=_bit(lock, 3), touch_double_call_on=_bit(lock, 4),
             touch_hold_call_on=_bit(lock, 5), touch_locked=not _bit(lock, 7), touch_lock_raw=lock)
    f["touch_option_l"] = TOUCH_ACTIONS.get((p[11] >> 4) & 15, f"raw_{(p[11] >> 4) & 15}")
    f["touch_option_r"] = TOUCH_ACTIONS.get(p[11] & 15, f"raw_{p[11] & 15}")
    f["noise_mode"] = NOISE_MODES.get(p[12], f"raw_{p[12]}")
    if len(p) > 23:
        f["ambient_volume"] = p[23]
    if len(p) > 24:
        f["noise_reduction_level"] = p[24]
    if len(p) > 44:  # FE tail: ... hearing test(40) amplify(41) headtracking(42) charging(43)
        ch = p[43]
        f.update(charging_l=_bit(ch, 4), charging_r=_bit(ch, 2), charging_case=_bit(ch, 0))
    f["_len"] = len(p)
    return f


def _dec_resp(p: bytes) -> dict:
    return {"action": p[0], "action_name": name_of(p[0]), "result": p[1],
            "result_name": RESULT_CODES.get(p[1], f"code_{p[1]}"),
            **({"extra": list(p[2:])} if len(p) > 2 else {})}


def _dec_ack(p: bytes) -> dict:
    return {"action": p[0], "action_name": name_of(p[0]), "params_hex": p[1:].hex()}


def _dec_noise_update(p: bytes) -> dict:
    return {"mode": NOISE_MODES.get(p[0], f"raw_{p[0]}"), **({"wear_raw": p[1]} if len(p) > 1 else {})}


def _dec_touch_update(p: bytes) -> dict:
    return {"touchpad_locked": bool(p[0]), "raw": p.hex()}


def _dec_mute(p: bytes) -> dict:
    return {"mute_l": bool(p[0]), "mute_r": bool(p[1])}


def _dec_ambient(p: bytes) -> dict:
    return {"ambient_on": bool(p[0])}


GESTURES = {1: "single", 2: "double", 3: "triple", 5: "hold_start", 7: "hold_end"}


def _dec_touch_on_buds(p: bytes) -> dict:
    # Observed on a real FE (not in the reference docs): [side, gesture, 0x20, 0xd9].
    # side 1 = left, 0 = right (inferred from tapping each bud); gesture 5/7 bracket a touch-and-hold.
    return {"side": "L" if p[0] == 1 else "R", "gesture": GESTURES.get(p[1], f"code_{p[1]}"), "code": p[1],
            "tail": p[2:].hex()}


def _dec_text(p: bytes) -> dict:
    return {"text": _printable(p)}


_DECODERS: dict[int, Callable[[bytes], dict]] = {
    STATUS_UPDATED: _dec_status,
    EXTENDED_STATUS_UPDATED: _dec_ext_status,
    RESP: _dec_resp,
    UNIVERSAL_ACK: _dec_ack,
    NOISE_CONTROLS_UPDATE: _dec_noise_update,
    TOUCH_UPDATED: _dec_touch_update,
    MUTE_EARBUD_STATUS_UPDATED: _dec_mute,
    AMBIENT_MODE_UPDATED: _dec_ambient,
    TOUCH_ON_BUDS: _dec_touch_on_buds,
    VERSION_INFO: _dec_text,
    DEBUG_SERIAL_NUMBER: _dec_text,
    DEBUG_BUILD_INFO: _dec_text,
}


def decode(frame: Frame) -> Decoded:
    fn = _DECODERS.get(frame.msg_id)
    if fn is None:
        return Decoded(frame.msg_id, name_of(frame.msg_id), False, "Unknown", {"payload_hex": frame.payload.hex()})
    try:
        return Decoded(frame.msg_id, name_of(frame.msg_id), True, "Likely", fn(frame.payload))
    except (IndexError, ValueError) as exc:
        return Decoded(frame.msg_id, name_of(frame.msg_id), False, "Unknown",
                       {"payload_hex": frame.payload.hex()}, error=f"decode failed: {exc!r}")
