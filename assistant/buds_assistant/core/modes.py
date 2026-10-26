"""Modes, memory level and placement.

Mode:      standby | listen | autopilot | interpreter | private   (exactly one; Ask is an action, not a mode)
Memory:    live (nothing saved) | remember (default) | recording (this conversation only)
Placement: ear (buds in: buds mic + buds audio) | remote (buds out: used as a clicker; Mac mic + Mac speakers)
The gesture map is the same for both placements; the contextual layer (context.py) and the anti-accident filter
(touchfilter.py) sit in front of it."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Awaitable, Callable

import yaml

from buds_assistant.controls.context import GestureContext
from buds_assistant.controls.gestures import Binding, GestureRecognizer
from buds_assistant.controls.touchfilter import TouchFilter

MODES = ("standby", "listen", "autopilot", "interpreter", "private")
MEMORY_LEVELS = ("live", "remember", "recording")
CAPTURING = ("listen", "autopilot", "interpreter")
INTERPRETER_SEG = {"end_silence": 0.45, "max_len": 7.0, "min_speech": 0.3, "min_abs": 0.003, "ratio": 2.0, "soft_len": 2.5, "soft_silence": 0.2}      # phrase-level: speak soon after each phrase
PHRASES = {"standby": "Standby", "listen": "Listening", "autopilot": "Autopilot on", "interpreter": "Interpreter",
           "private": "Private"}


# Gesture slots the editor offers (the buds give 4 gestures per side) and what each action is called in plain words.
SLOTS = ("L:single", "L:double", "L:triple", "L:hold", "R:single", "R:double", "R:triple", "R:hold")
ACTIONS = {"ask": "Ask the assistant", "replay": "Replay the last seconds", "catch_up": "Catch me up",
           "mark": "Mark this moment", "who": "Who is talking", "listen_toggle": "Listen on / off",
           "autopilot_toggle": "Autopilot on / off", "interpreter_toggle": "Interpreter on / off",
           "private_toggle": "Private on / off", "stop": "Stop speaking"}
DEFAULT_MAP = {"L:single": "ask", "L:double": "replay", "L:triple": "private_toggle", "L:hold": "interpreter_toggle",
               "R:single": "mark", "R:double": "autopilot_toggle", "R:triple": "who", "R:hold": "listen_toggle"}
HEADER = """# Sidekick gesture map (edited by the dashboard; same in the ear and as a remote). Left = talk to the assistant,
# right = control the session. Contextual gestures (stop / tell me more / not useful / undo) are handled in context.py.
sequence_timeout: 0.7
hold_debounce: 1.2

bindings:
"""


def write_gestures(path: Path, mapping: dict[str, str]) -> None:
    lines = []
    for g in SLOTS:
        a = mapping[g]
        toggle = ", mode: toggle" if g.endswith("hold") else ""
        lines.append(f'  - {{name: {g.replace(":", "-")}, gesture: "{g}"{toggle}, action: {a}}}')
    Path(path).write_text(HEADER + "\n".join(lines) + "\n")


def read_gestures(path: Path) -> dict[str, str]:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    return {b["gesture"]: b["action"] for b in doc.get("bindings", []) if "gesture" in b}


def load_profiles(path: Path) -> dict[str, tuple[list[Binding], float, float]]:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    timeout, deb = float(doc.get("sequence_timeout", 0.7)), float(doc.get("hold_debounce", 1.2))

    def parse(items) -> list[Binding]:
        out = []
        for b in items or []:
            pat = tuple(b["sequence"]) if "sequence" in b else (b["gesture"],)
            out.append(Binding(b["name"], pat, b["action"], b.get("mode", "tap")))
        return out
    ear = parse(doc.get("bindings"))
    remote = parse(doc["remote_bindings"]) if "remote_bindings" in doc else ear
    return {"ear": (ear, timeout, deb), "remote": (remote, timeout, deb)}


class ModeManager:
    def __init__(self, cfg, events, output, ring, pipeline, policy, store, source_factory: Callable[[str], object],
                 profiles: dict, handlers: dict[str, Callable[..., Awaitable]] | None = None,
                 ambient: Callable[[bool], Awaitable] | None = None) -> None:
        self.cfg, self.events, self.output, self.ring = cfg, events, output, ring
        self.pipeline, self.policy, self.store = pipeline, policy, store
        self.source_factory, self.handlers, self.ambient = source_factory, handlers if handlers is not None else {}, ambient
        self.profiles = profiles
        self.mode, self.placement, self.memory_level = "standby", "ear", "remember"
        self.recognizers = {n: GestureRecognizer(b, t, d) for n, (b, t, d) in profiles.items()}
        self.context, self.touch = GestureContext(), TouchFilter()
        self._wear = {"L": None, "R": None}
        self._ambient_on = False
        self._resume_autopilot = False
        self._lock = asyncio.Lock()                           # one mode/placement change at a time (stops and starts can take seconds)
        self.models = None                                    # ModelManager (optional): residency per mode

    def reload_profiles(self, path: Path) -> None:
        """Hot-reload the gesture map (the dashboard's gesture editor)."""
        self.profiles = load_profiles(path)
        self.recognizers = {n: GestureRecognizer(b, t, d) for n, (b, t, d) in self.profiles.items()}

    @property
    def recognizer(self) -> GestureRecognizer:
        return self.recognizers.get(self.placement) or next(iter(self.recognizers.values()))

    @property
    def capturing(self) -> bool:
        return self.mode in CAPTURING

    def state(self) -> dict:
        return {"mode": self.mode, "memory_level": self.memory_level, "placement": self.placement,
                "route": self.output.route, "conversation_id": self.pipeline.conv_id,
                "ring_seconds": round(self.ring.seconds, 1), "autopilot": self.policy.enabled,
                "interpreter_two_way": bool(getattr(self.cfg, "interpreter_two_way", False)),
                "live_translation": bool(getattr(self.cfg, "live_translation", False))}

    def _publish(self) -> None:
        self.events.publish("mode", **self.state())

    # ---- placement --------------------------------------------------------------------------------------
    async def on_wear(self, side: str, placement_code: int) -> None:
        """placement_code: 1 = in ear, otherwise out / in case / disconnected."""
        if self._wear[side] is not None and self._wear[side] != placement_code:
            self.touch.note_wear(time.monotonic())            # inserting/removing a bud makes the pads fire: ignore them
        self._wear[side] = placement_code
        if self.cfg.placement != "auto" or None in self._wear.values():
            return
        new = "ear" if 1 in self._wear.values() else "remote"
        await self.set_placement(new)

    def _capture_placement(self) -> str:
        return "remote" if self.mode == "interpreter" else self.placement      # interpreter defaults to the Mac mic

    async def set_placement(self, new: str) -> None:
        async with self._lock:
            await self._set_placement(new)

    async def _set_placement(self, new: str) -> None:
        if new == self.placement:
            return
        self.placement = new
        self.output.set_route(new)
        if self.pipeline.source is not None:                 # keep the conversation going on the other microphone
            self.pipeline.placement = new
            self.pipeline.set_source(self.source_factory(self._capture_placement()))
        self._publish()

    # ---- modes ---------------------------------------------------------------------------------------------
    async def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(mode)
        if mode == "interpreter" and not getattr(self.cfg, "live_translation", False):
            raise ValueError("Live translation is switched off in this version. Use the Translate box on Home, or say \"translate to Telugu: ...\".")
        async with self._lock:
            changed = await self._set_mode(mode)
        if changed:
            self._announce(self.mode)

    async def _set_mode(self, mode: str) -> bool:
        prev = self.mode
        if prev == "private" and mode != "private":
            mode = "standby"                                  # leaving private never goes straight back to listening
        if prev == "interpreter" and mode == "listen" and self._resume_autopilot:
            mode = "autopilot"                                # interpreter paused autopilot: give it back
        if mode == prev:
            return False
        loop = asyncio.get_running_loop()
        self.pipeline.seg_kwargs = dict(INTERPRETER_SEG) if mode == "interpreter" else {}
        if mode == "interpreter" and self.models is not None:
            if self.models.state().get("translate") != "ready":
                self.output.earcon("mode_on")
                asyncio.ensure_future(self._phrase("Starting interpreter"))
            self.events.publish("mode_pending", mode="interpreter")      # the models take a while: the UI shows "getting ready" instead of the old mode
            try:
                await loop.run_in_executor(None, self.models.enter, mode)
            finally:
                self.events.publish("mode_pending", mode=None)
        if prev == "interpreter" and mode != "interpreter" and self.models is not None:
            loop.run_in_executor(None, self.models.leave, "interpreter")
        if mode == "private":
            self.policy.enabled = False                       # before anything else: the last utterance must not raise a whisper
            self.output.stop()
            await loop.run_in_executor(None, lambda: self.pipeline.stop(extract=False, discard=True))
            self.ring.clear()
            self.policy.enabled = False
            self.cfg.interpreter = False
            self._resume_autopilot = False
            await self._ambient(False)
        elif mode in CAPTURING:
            self.mode = mode                                  # _capture_placement reads the new mode
            if prev not in CAPTURING:
                self.pipeline.persist = self._saves(mode)
                self.pipeline.start(self.source_factory(self._capture_placement()), mode, self.placement)
                if self.placement == "ear":
                    await self._ambient(True)
            elif (mode == "interpreter") != (prev == "interpreter"):
                self.pipeline.set_source(self.source_factory(self._capture_placement()))
            self.pipeline.persist = self._saves(mode)         # Translate saves nothing, whatever the memory switch says
            if mode == "interpreter":
                self._resume_autopilot = prev == "autopilot"
            elif prev == "interpreter":
                self._resume_autopilot = False
            self.policy.enabled = mode == "autopilot"
            self.cfg.interpreter = mode == "interpreter"
        else:                                                # standby: no live capture
            if prev in CAPTURING:
                await loop.run_in_executor(None, self.pipeline.stop)
                await self._ambient(False)
            self.policy.enabled = False
            self.cfg.interpreter = False
            self._resume_autopilot = False
        self.mode = mode
        if not self.capturing and self.memory_level == "recording":
            self.memory_level = "remember"                   # recording is per conversation
        self.store.audit("mode", {"from": prev, "to": mode, "placement": self.placement})
        self._publish()
        return True

    def _announce(self, mode: str) -> None:
        """Earcon first (instant), then a short phrase so a mode change is audible without looking."""
        self.output.earcon("mode_off" if mode in ("standby", "private") else "mode_on")
        asyncio.ensure_future(self._phrase(PHRASES[mode]))

    async def _phrase(self, text: str) -> None:
        await asyncio.sleep(0.3)                              # let the earcon finish (one player, one sound at a time)
        await self.output.say(text, "en", "chime", whisper=True)

    def _saves(self, mode: str) -> bool:
        return self.memory_level != "live" and mode != "interpreter"

    async def set_memory_level(self, level: str) -> None:
        if level not in MEMORY_LEVELS:
            raise ValueError(level)
        if level == "recording" and not self.capturing:
            raise ValueError("Recording needs Listen, Autopilot or Interpreter to be on.")
        prev, self.memory_level = self.memory_level, level
        self.pipeline.persist = self._saves(self.mode)            # live only: nothing is stored
        self.store.audit("recording_start" if level == "recording" else "memory_level", {"from": prev, "to": level})
        self._publish()

    async def _ambient(self, on: bool) -> None:
        if self.ambient is None or on == self._ambient_on:
            return
        try:
            await self.ambient(on)
            self._ambient_on = on
        except Exception as exc:  # noqa: BLE001  buds commands are best effort
            self.events.publish("error", where="ambient", error=repr(exc))

    # ---- actions (gesture or voice) ------------------------------------------------------------------------------
    async def dispatch(self, action: str, **kw) -> None:
        self.events.publish("action", action=action, placement=self.placement, **kw)
        if self.mode == "private" and action in ("ask", "who", "catch_up", "replay", "tell_more"):
            self.output.earcon("error")                          # private means the mic stays closed, even for a question
            return
        if action == "listen_toggle":
            await self.set_mode("standby" if self.mode in ("listen", "autopilot") else "listen")
        elif action == "autopilot_toggle":
            await self.set_mode("listen" if self.mode == "autopilot" else "autopilot")
        elif action == "interpreter_toggle":
            if not getattr(self.cfg, "live_translation", False):
                self.output.earcon("error")                      # live translation is frozen out of this release
                return
            await self.set_mode("listen" if self.mode == "interpreter" else "interpreter")
        elif action == "private_toggle":
            await self.set_mode("standby" if self.mode == "private" else "private")
        elif action == "replay":
            audio = self.ring.last(self.cfg.ring_seconds) if self.capturing else None
            if audio is None or audio.size == 0:
                text = "Nothing to replay. Listen first." if not self.capturing else "Nothing to replay yet."
                await self.output.say(text, "en", "answer")
            else:
                self.context.open("replay", time.monotonic())
                await self.output.play_audio(audio, 16000, speed=kw.get("speed", 1.0))
        elif action == "mark":
            sp = self.pipeline.current_speaker or {}
            self.store.add_bookmark(self.pipeline.conv_id, time.time(), sp.get("person_id"), kw.get("note", ""))
            self.events.publish("bookmark", speaker=sp.get("name") or sp.get("cluster"))
            self.output.earcon("noted")
        elif action == "stop":
            self.output.stop()
        elif action in self.handlers:
            await self.handlers[action](**kw)
        else:
            self.events.publish("error", where="dispatch", error=f"unknown action {action}")

    async def on_token(self, token: str, now: float) -> None:
        for m in self.recognizer.feed(token, now):
            await self._fire(m, now)

    async def poll(self, now: float) -> None:
        for m in self.recognizer.poll(now):
            await self._fire(m, now)

    async def _fire(self, m, now: float) -> None:
        gesture = m.binding.pattern[0] if len(m.binding.pattern) == 1 else ""
        if not self.touch.accept(gesture or m.binding.pattern[-1], now):
            self.events.publish("gesture_ignored", name=m.binding.name, placement=self.placement)
            return
        ctx_action = self.context.intercept(gesture, now, self.output.speaking) if gesture else None
        action = ctx_action or m.binding.action
        self.events.publish("gesture", name=m.binding.name, action=action, phase=m.phase, placement=self.placement)
        if action not in ("mark", "listen_toggle", "autopilot_toggle", "interpreter_toggle", "private_toggle", "stop"):
            self.output.earcon("accepted")                    # mode toggles and mark have their own sounds
        await self.dispatch(action, phase=m.phase)


ModeController = ModeManager
