"""Tracks device state from decoded messages and derives semantic events."""
from __future__ import annotations

from typing import Any

from ..protocol.messages import (EXTENDED_STATUS_UPDATED, STATUS_UPDATED, NOISE_CONTROLS_UPDATE, PLACEMENT,
                                 TOUCH_UPDATED, TOUCH_ON_BUDS, MUTE_EARBUD_STATUS_UPDATED, Decoded)
from .events import Event

SRC = "samsung-spp"


class DeviceState:
    def __init__(self) -> None:
        self.s: dict[str, Any] = {}
        self.last_status_ts: float | None = None
        self.status_intervals: list[float] = []

    def snapshot(self) -> dict[str, Any]:
        return dict(self.s)

    def update(self, d: Decoded, ts: float) -> list[Event]:
        f = d.fields
        ev: list[Event] = []

        def mk(type_, side=None, **data):
            ev.append(Event("B", SRC, type_, side, data, ts=ts))

        if d.msg_id in (STATUS_UPDATED, EXTENDED_STATUS_UPDATED) and d.known:
            first = "battery_l" not in self.s
            if self.last_status_ts is not None:
                self.status_intervals.append(ts - self.last_status_ts)
                self.status_intervals = self.status_intervals[-50:]
            self.last_status_ts = ts
            mk("battery", None, left=f["battery_l"], right=f["battery_r"], case=f["battery_case"],
               msg=d.name, initial=first)
            for side, key in (("L", "placement_l"), ("R", "placement_r")):
                new = f[key]
                old = self.s.get(key)
                if new != old:
                    st = PLACEMENT.get(new, f"state_{new}")
                    mk("wear", side, state=st, placement=new, previous=old, initial=old is None)
                    if not first or old is not None:
                        if new == 3 and old != 3:
                            mk("case", side, event="bud_in_case", initial=old is None)
                        elif old == 3 and new != 3:
                            mk("case", side, event="bud_out_of_case", initial=old is None)
            for side, key in (("L", "charging_l"), ("R", "charging_r"), ("case", "charging_case")):
                if key in f and f[key] != self.s.get(key):
                    mk("case", None if side == "case" else side, event="charging" if f[key] else "not_charging",
                       target=side, initial=key not in self.s)
            if "noise_mode" in f and f["noise_mode"] != self.s.get("noise_mode"):
                mk("anc", None, mode=f["noise_mode"], previous=self.s.get("noise_mode"), source_msg=d.name,
                   initial="noise_mode" not in self.s)
            if "touch_locked" in f and f["touch_locked"] != self.s.get("touch_locked"):
                mk("touch", None, event="touchpad_lock", locked=f["touch_locked"], source_msg=d.name,
                   initial="touch_locked" not in self.s)
            self.s.update({k: v for k, v in f.items() if not k.startswith("_")})
        elif d.msg_id == NOISE_CONTROLS_UPDATE and d.known:
            if f["mode"] != self.s.get("noise_mode"):
                mk("anc", None, mode=f["mode"], previous=self.s.get("noise_mode"), source_msg=d.name)
            self.s["noise_mode"] = f["mode"]
        elif d.msg_id == TOUCH_ON_BUDS and d.known:
            mk("touch", f["side"], event="gesture", gesture=f["gesture"], code=f["code"], msg_id=d.msg_id)
        elif d.msg_id == TOUCH_UPDATED and d.known:
            mk("touch", None, event="touchpad_lock", locked=f["touchpad_locked"], source_msg=d.name)
            self.s["touch_locked"] = f["touchpad_locked"]
        elif d.msg_id == MUTE_EARBUD_STATUS_UPDATED and d.known:
            mk("audio", None, event="mute_status", mute_l=f["mute_l"], mute_r=f["mute_r"])
        return ev
