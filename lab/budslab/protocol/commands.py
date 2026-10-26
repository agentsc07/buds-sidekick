"""Command allowlist. This is the ONLY place TX payloads are built.

Only settings-type commands are here. Firmware update, factory reset, reboot/poweroff,
bonded-device/key dumps, debug/hidden modes and anything else are deliberately absent and
also listed in DENYLIST as a belt-and-braces check inside `check_tx_id`.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .messages import NOISE_CONTROLS

# ids
EQUALIZER = 134
LOCK_TOUCHPAD = 144
SET_TOUCHPAD_OPTION = 146
AMBIENT_VOLUME = 132
FIND_MY_EARBUDS_START = 160
FIND_MY_EARBUDS_STOP = 161
MUTE_EARBUD = 162
UPDATE_TIME = 167
MANAGER_INFO = 136
RESP = 81

# never sent, whatever anyone asks: reset, reboot, poweroff, FOTA*, debug/hidden/test modes,
# log/coredump, bonded device dumps, factory info, rf test
DENYLIST = {
    80, 82, 83, 86, 15, 16, 17, 18, 19, 21, 22, 23, 32, 33, 34, 35, 36, 38, 39, 42, 47, 48, 49, 50,
    51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 67, 75, 141, 142, 148, 169, 170, 171, 176, 177, 178,
    179, 180, 181, 182, 183, 185, 186, 187, 188, 189, 190, 207, 212, 213, 214, 216, 241, 242, 254, 255,
}

TOUCH_MAP = {"voice_assistant": 1, "noise_control": 2, "volume": 3}


class CommandError(ValueError):
    pass


@dataclass
class CommandSpec:
    name: str
    msg_id: int
    description: str
    risk: str                                   # "changes-settings" | "audible"
    build: Callable[[dict, dict], bytes]        # (args, device_state) -> payload
    args_schema: dict[str, Any] = field(default_factory=dict)
    confirm: str | None = None                  # warning text; requires explicit confirm
    undo: Callable[[dict, dict], tuple[str, dict] | None] | None = None

    def public(self) -> dict:
        return {"name": self.name, "msg_id": self.msg_id, "description": self.description, "risk": self.risk,
                "args": self.args_schema, "confirm": self.confirm}


def _enum(args: dict, key: str, options: dict[str, int]) -> int:
    v = args.get(key)
    if v not in options:
        raise CommandError(f"{key} must be one of {sorted(options)}")
    return options[v]


def _int(args: dict, key: str, lo: int, hi: int) -> int:
    try:
        v = int(args.get(key))
    except (TypeError, ValueError):
        raise CommandError(f"{key} must be an integer {lo}-{hi}")
    if not lo <= v <= hi:
        raise CommandError(f"{key} must be {lo}-{hi}")
    return v


def _noise(args, st):
    return bytes([_enum(args, "mode", {"off": 0, "anc": 1, "ambient": 2})])


def _noise_undo(args, st):
    prev = st.get("noise_mode")
    return ("noise_control", {"mode": prev}) if prev in ("off", "anc", "ambient") else None


def _amb_vol(args, st):
    return bytes([_int(args, "level", 0, 2)])


def _eq(args, st):
    # Buds2-family encoding per reference: 0 = off, preset+1 otherwise.
    if args.get("preset") in ("off", None):
        return bytes([0])
    return bytes([_int(args, "preset", 0, 5) + 1])


def _eq_undo(args, st):
    m = st.get("eq_mode")
    return ("equalizer", {"preset": "off" if not m else m - 1}) if m is not None else None


def _touch_opt(args, st):
    return bytes([_enum(args, "left", TOUCH_MAP), _enum(args, "right", TOUCH_MAP)])


def _touch_opt_undo(args, st):
    inv = {k: k for k in TOUCH_MAP}
    l, r = st.get("touch_option_l"), st.get("touch_option_r")
    return ("touchpad_option", {"left": l, "right": r}) if l in inv and r in inv else None


def _lock(args, st):
    need = ("touch_single_on", "touch_double_on", "touch_triple_on", "touch_hold_on",
            "touch_double_call_on", "touch_hold_call_on")
    if any(k not in st for k in need):
        raise CommandError("touchpad state not known yet; wait for a status update (needed to preserve gesture settings)")
    locked = bool(args.get("locked"))
    # byte 0 = "not locked", then the per-gesture enables, preserved from the current device state
    return bytes([0 if locked else 1] + [1 if st[k] else 0 for k in need])


def _lock_undo(args, st):
    cur = st.get("touch_locked")
    return ("lock_touchpad", {"locked": cur}) if cur is not None else None


def _mute(args, st):
    if not st.get("find_my_active"):
        raise CommandError("mute_earbud only works while Find My Earbuds is active (per reference notes)")
    return bytes([1 if args.get("left") else 0, 1 if args.get("right") else 0])


def _time(args, st):
    now = time.time()
    tz_ms = -time.timezone * 1000 + (3600000 if time.localtime().tm_isdst > 0 else 0)
    return struct.pack("<qi", int(now * 1000), tz_ms)


_FIND_WARN = ("Find My Earbuds plays a LOUD beeping sound from the buds. Remove them from your ears "
              "before confirming.")

COMMANDS: dict[str, CommandSpec] = {c.name: c for c in [
    CommandSpec("noise_control", NOISE_CONTROLS, "Set noise control mode", "changes-settings", _noise,
                {"mode": ["off", "anc", "ambient"]}, undo=_noise_undo),
    CommandSpec("ambient_volume", AMBIENT_VOLUME, "Set ambient sound level (FE max reported as 2 by reference)",
                "changes-settings", _amb_vol, {"level": "0-2"}),
    CommandSpec("equalizer", EQUALIZER, "Set equalizer preset (or off)", "changes-settings", _eq,
                {"preset": ["off", 0, 1, 2, 3, 4, 5]}, undo=_eq_undo),
    CommandSpec("touchpad_option", SET_TOUCHPAD_OPTION, "Set touch-and-hold action per side", "changes-settings",
                _touch_opt, {"left": sorted(TOUCH_MAP), "right": sorted(TOUCH_MAP)}, undo=_touch_opt_undo),
    CommandSpec("lock_touchpad", LOCK_TOUCHPAD, "Lock/unlock the touchpads (keeps current per-gesture settings)",
                "changes-settings", _lock, {"locked": "bool"}, undo=_lock_undo),
    CommandSpec("mute_earbud", MUTE_EARBUD, "Mute a bud (Find My mode only)", "audible", _mute,
                {"left": "bool", "right": "bool"}, confirm=_FIND_WARN),
    CommandSpec("find_my_start", FIND_MY_EARBUDS_START, "Start Find My Earbuds (LOUD)", "audible",
                lambda a, s: b"", {}, confirm=_FIND_WARN,
                undo=lambda a, s: ("find_my_stop", {})),
    CommandSpec("find_my_stop", FIND_MY_EARBUDS_STOP, "Stop Find My Earbuds", "changes-settings",
                lambda a, s: b"", {}),
    CommandSpec("update_time", UPDATE_TIME, "Sync clock", "changes-settings", _time, {}),
]}

ALLOWED_TX_IDS = {c.msg_id for c in COMMANDS.values()} | {RESP, MANAGER_INFO}


def check_tx_id(msg_id: int) -> None:
    if msg_id in DENYLIST or msg_id not in ALLOWED_TX_IDS:
        raise CommandError(f"message id {msg_id} is not on the TX allowlist")


def build(name: str, args: dict, state: dict) -> tuple[CommandSpec, bytes]:
    spec = COMMANDS.get(name)
    if spec is None:
        raise CommandError(f"unknown command {name!r}; allowed: {sorted(COMMANDS)}")
    payload = spec.build(args or {}, state)
    check_tx_id(spec.msg_id)
    return spec, payload


def manager_info_payload(samsung: bool = False, sdk: int = 34) -> bytes:
    return bytes([1, 1 if samsung else 2, sdk])
