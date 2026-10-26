"""One reactive state object for the dashboard: the backend owns the truth, the UI renders the last snapshot.

Reduces bus events into a snapshot and republishes it as a `ui_state` event after every change, so the dashboard never polls."""
from __future__ import annotations

from typing import Any
import os

WEAR = {1: "in_ear", 2: "out", 3: "in_case"}
UP = ("connected",)
DOWN = ("error", "disconnected", "not connected", "timed out", "connecting")


class UiState:
    def __init__(self, events, cfg) -> None:
        self.events, self.cfg = events, cfg
        self.load_fn = lambda: (os.getloadavg()[0], os.cpu_count() or 4)      # one-minute load average and core count
        self._busy = False
        self.voice_ready_fn = lambda: True                 # set by Sidekick: can the user's voice be recognised by the current model?
        self._s: dict[str, Any] = {
            "mode": "standby", "memory_level": "remember", "placement": "ear", "route": "ear", "conversation_id": None,
            "ring_seconds": 0.0, "buds": {"battery": None, "wear": {"L": None, "R": None}},
            "models": {"chat": "unloaded", "embed": "unloaded", "translate": "unloaded", "telugu": "unloaded"}, "interpreter": {"two_way": False}, "live_translation": False, "pending_mode": None,
            "autopilot": {"enabled": False, "feed": []}, "banner": None, "self_name": cfg.self_name}
        self._reducers = {"mode": self._mode, "battery": self._battery, "wear": self._wear, "model_state": self._models,
                          "autopilot_decision": self._decision, "buds": self._buds, "mode_pending": lambda d: self._s.__setitem__("pending_mode", d.get("mode")),
                          "enrolled": lambda d: None, "forgotten": lambda d: None, "cluster_named": lambda d: None}
        events.subscribe(self._on_event)

    def snapshot(self) -> dict:
        s = {k: (dict(v) if isinstance(v, dict) else v) for k, v in self._s.items()}
        s["buds"] = {"battery": dict(self._s["buds"]["battery"]) if self._s["buds"]["battery"] else None, "wear": dict(self._s["buds"]["wear"])}
        s["models"] = dict(self._s["models"])
        s["self_name"] = self.cfg.self_name
        s["voice_ready"] = bool(self.voice_ready_fn())
        s["busy"] = self._busy
        s["autopilot"] = {**self._s["autopilot"], "feed": list(self._s["autopilot"]["feed"]),
                          "sensitivity": self.cfg.autopilot_sensitivity}
        return s

    def refresh(self) -> None:
        """Re-check how busy the Mac is (everything is slow when other apps use all the cores); publish only on a change."""
        load, cores = self.load_fn()
        busy = load > cores * 2
        if busy != self._busy:
            self._busy = busy
            self.events.publish("ui_state", **self.snapshot())

    def _on_event(self, ev: dict) -> None:
        fn = self._reducers.get(ev["type"])
        if fn is None:
            return
        fn(ev["data"])
        self.events.publish("ui_state", **self.snapshot())

    def scrub(self, drop=None) -> None:
        """Remove decisions from the feed (forget a person: drop(d) is true for theirs; no predicate clears everything)."""
        feed = self._s["autopilot"]["feed"]
        feed[:] = [] if drop is None else [d for d in feed if not drop(d)]
        self.events.publish("ui_state", **self.snapshot())

    # ---- reducers ---------------------------------------------------------------------------------------------
    def _mode(self, d: dict) -> None:
        for k in ("mode", "memory_level", "placement", "route", "conversation_id", "ring_seconds"):
            if k in d:
                self._s[k] = d[k]
        self._s["autopilot"]["enabled"] = bool(d.get("autopilot"))
        self._s["interpreter"] = {"two_way": bool(d.get("interpreter_two_way"))}
        self._s["live_translation"] = bool(d.get("live_translation"))

    def _battery(self, d: dict) -> None:
        self._s["buds"]["battery"] = {k: d.get(k) for k in ("left", "right", "case")}

    def _wear(self, d: dict) -> None:
        self._s["buds"]["wear"][d["side"]] = WEAR.get(d.get("placement"), "out")

    def _models(self, d: dict) -> None:
        self._s["models"] = {k: d[k] for k in ("chat", "embed", "translate", "telugu") if k in d}

    def _decision(self, d: dict) -> None:
        feed = self._s["autopilot"]["feed"]
        if d.get("hint_id") and any(x.get("hint_id") == d["hint_id"] for x in feed):          # a later verdict on the same whisper
            feed[:] = [dict(d) if x.get("hint_id") == d["hint_id"] else x for x in feed]
        else:
            feed.append(dict(d))
        del feed[:-30]

    def _buds(self, d: dict) -> None:
        msg = str(d.get("message", "")).lower()
        if any(w in msg for w in UP) and "disconnected" not in msg:
            self._s["banner"] = None
        elif any(w in msg for w in DOWN):
            self._s["banner"] = "Buds not connected. Mode features that need them are paused until they reconnect."
