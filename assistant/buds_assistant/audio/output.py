"""Everything the user hears goes through one arbiter: priorities, barge-in, stale-hint dropping, whisper gain,
language-specific voices, replay at speed, and routing (ear = buds, remote = Mac speakers)."""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

import numpy as np

from buds_assistant.audio.earcons import Earcons

PRIORITY = {"chime": 1, "hint": 2, "answer": 3, "replay": 3}


class Player(Protocol):
    def play(self, audio: np.ndarray, rate: int) -> None: ...   # blocking
    def stop(self) -> None: ...


class SoundDevicePlayer:
    def __init__(self, device_hint: str | int | None = None) -> None:
        self.device_hint = device_hint

    def _device(self) -> int | None:
        import sounddevice as sd
        if self.device_hint is None:
            return None
        if isinstance(self.device_hint, int):
            return self.device_hint
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and self.device_hint.lower() in d["name"].lower():
                return i
        return None

    def play(self, audio: np.ndarray, rate: int) -> None:
        import sounddevice as sd
        sd.play(audio, rate, device=self._device())
        sd.wait()

    def stop(self) -> None:
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:  # noqa: BLE001
            pass


class FakePlayer:
    def __init__(self, hold: float = 0.0) -> None:
        self.played: list[tuple[np.ndarray, int]] = []
        self.hold, self.stopped = hold, 0

    def play(self, audio, rate) -> None:
        self.played.append((audio, rate))
        end = time.time() + self.hold
        while time.time() < end and not self.stopped:
            time.sleep(0.005)

    def stop(self) -> None:
        self.stopped += 1


class SayRenderTTS:
    """macOS `say` rendered to audio (silent until played), so we control gain, device and speed."""
    def __init__(self, voices: dict[str, str], rate_wpm: int = 185) -> None:
        self.voices, self.rate_wpm = voices, rate_wpm
        self._cache: OrderedDict = OrderedDict()

    def render(self, text: str, lang: str = "en", wpm: int | None = None) -> tuple[np.ndarray, int]:
        key = (text, lang, wpm)
        if key in self._cache:
            return self._cache[key]
        voice = self.voices.get(lang)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.wav"
            cmd = ["say", "-r", str(wpm or self.rate_wpm)] + (["-v", voice] if voice else []) + \
                  ["-o", str(p), "--file-format=WAVE", "--data-format=LEI16@22050", "--", text]
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode != 0 or not p.exists():
                cmd = ["say", "-o", str(p), "--file-format=WAVE", "--data-format=LEI16@22050", "--", text]   # voice missing
                subprocess.run(cmd, check=True, capture_output=True)
            with wave.open(str(p)) as w:
                out = (np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate())
        self._cache[key] = out
        if len(self._cache) > 40:
            self._cache.popitem(last=False)
        return out


class FakeTTS:
    def __init__(self) -> None:
        self.rendered: list[tuple[str, str]] = []
        self.wpms: list = []

    def render(self, text: str, lang: str = "en", wpm: int | None = None):
        self.rendered.append((text, lang))
        self.wpms.append(wpm)
        return np.full(800, 1000, dtype=np.int16), 16000


class OutputArbiter:
    def __init__(self, tts, players: dict[str, Player], events=None, hint_ttl: float = 6.0) -> None:
        self.tts, self.players, self.events, self.hint_ttl = tts, players, events, hint_ttl
        self.route = "ear"
        self._cur_prio = 0
        self._cur_task: asyncio.Task | None = None
        self._pending: list[tuple[float, str, str, bool]] = []
        self.last_duration = 0.0
        self._spans: list[tuple[float, float]] = []            # when our own voice was playing (wall clock): the mic hears it too
        self._open: float | None = None
        self.log: list[dict] = []
        self.earcons = Earcons()

    def set_route(self, route: str) -> None:
        if route not in self.players:
            raise ValueError(f"unknown route {route}")
        self.stop()
        self.route = route
        self._emit("route", route=route)

    def _emit(self, kind: str, **d) -> None:
        self.log.append({"kind": kind, **d})
        del self.log[:-200]
        if self.events:
            self.events.publish("audio_out", kind=kind, **d)

    def earcon(self, name: str) -> None:
        """Play a designed sound now (fire and forget). Skipped while speech is playing, except errors."""
        if self.busy and name != "error":
            return
        audio, rate = self.earcons.get(name)
        asyncio.get_running_loop().run_in_executor(None, self.players[self.route].play, audio, rate)
        self._emit("earcon", name=name)

    def overlap_fraction(self, t0: float, t1: float, tail: float = 0.6) -> float:
        """How much of [t0, t1] (wall clock) was our own voice playing (plus a short room tail): 1 = all of it. Used so the assistant never
        hears itself and takes its own words for a conversation."""
        if t1 <= t0:
            return 0.0
        spans = list(self._spans) + ([(self._open, time.time())] if self._open else [])
        covered = 0.0
        for a, b in sorted((a, b + tail) for a, b in spans):
            covered += max(0.0, min(b, t1) - max(a, t0))
        return min(1.0, covered / (t1 - t0))

    @property
    def speaking(self) -> bool:
        """Real speech (an answer, a whisper, a replay) is playing. A mode phrase or earcon does not count."""
        return self.busy and self._cur_prio >= PRIORITY["hint"]

    @property
    def busy(self) -> bool:
        return self._cur_task is not None and not self._cur_task.done()

    def stop(self) -> None:
        self._pending.clear()
        for p in self.players.values():
            p.stop()
        if self._cur_task and not self._cur_task.done():
            self._cur_task.cancel()
        self._cur_prio = 0

    async def say(self, text: str, lang: str = "en", priority: str = "answer", whisper: bool = False,
                  route: str | None = None, wpm: int | None = None) -> bool:
        """Speak `text`. Returns False if it was dropped (a more important sound is playing and it is not a hint)."""
        prio = PRIORITY[priority]
        if not text.strip():
            return False
        if self.busy and prio < self._cur_prio:
            if priority == "hint":                                # queue it, but only for a short time
                self._pending.append((time.time() + self.hint_ttl, text, lang, whisper))
            else:
                self._emit("dropped", text=text, priority=priority)
            return False
        if self.busy:
            self.players[self.route].stop()
            self._cur_task.cancel()
            await asyncio.gather(self._cur_task, return_exceptions=True)
        self._cur_prio = prio
        self._cur_task = asyncio.create_task(self._speak(text, lang, whisper, priority, route, wpm))
        try:
            await self._cur_task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
        finally:
            if not self.busy:
                self._cur_prio = 0
        await self._drain()
        return True

    async def _speak(self, text: str, lang: str, whisper: bool, priority: str, route: str | None = None, wpm: int | None = None) -> None:
        loop = asyncio.get_running_loop()
        route = route or self.route
        self._emit("speak", text=text, lang=lang, priority=priority, whisper=whisper, route=route)
        audio, rate = await loop.run_in_executor(None, lambda: self.tts.render(text, lang, 165 if whisper else wpm))
        if whisper:
            audio = (audio.astype(np.float32) * 0.35).astype(np.int16)
        self.last_duration = audio.size / rate
        self._open = time.time()
        try:
            await loop.run_in_executor(None, self.players[route].play, audio, rate)
        finally:
            self._spans.append((self._open, time.time()))
            del self._spans[:-60]
            self._open = None
        self._emit("speak_done", text=text)

    async def _drain(self) -> None:
        while self._pending and not self.busy:
            deadline, text, lang, whisper = self._pending.pop(0)
            if time.time() > deadline:
                self._emit("dropped", text=text, priority="hint", reason="stale")
                continue
            await self.say(text, lang, "hint", whisper)

    async def play_audio(self, audio: np.ndarray, rate: int = 16000, speed: float = 1.0, priority: str = "replay") -> bool:
        if audio.size == 0:
            return False
        if speed != 1.0:
            n = int(audio.size / speed)
            audio = np.interp(np.linspace(0, audio.size - 1, n), np.arange(audio.size), audio.astype(np.float32)).astype(np.int16)
        self.stop()
        self._cur_prio = PRIORITY[priority]
        loop = asyncio.get_running_loop()
        self._emit("replay", seconds=round(audio.size / rate, 2), speed=speed, route=self.route)
        self._cur_task = asyncio.ensure_future(loop.run_in_executor(None, self.players[self.route].play, audio, rate))
        try:
            await self._cur_task
        except asyncio.CancelledError:
            pass
        finally:
            self._cur_prio = 0
        return True
