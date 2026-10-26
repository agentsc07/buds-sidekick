"""Microphone capture with end-of-speech detection, plus earcons (short beeps)."""
from __future__ import annotations

import queue
import re
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class EnergyVAD:
    """Adaptive energy VAD: learns the noise floor first, then tracks speech start and end."""

    def __init__(self, end_silence: float = 0.9, no_speech_timeout: float = 4.0, calibrate: float = 0.3,
                 min_abs: float = 0.006, ratio: float = 3.0) -> None:
        self.end_silence, self.no_speech_timeout, self.calibrate = end_silence, no_speech_timeout, calibrate
        self.min_abs, self.ratio = min_abs, ratio
        self.t = 0.0
        self.noise: list[float] = []
        self.heard = False
        self.last_voice = 0.0

    @property
    def threshold(self) -> float:
        floor = float(np.median(self.noise)) if self.noise else 0.0
        return max(self.min_abs, floor * self.ratio)

    def feed(self, rms: float, dt: float) -> str:
        """-> 'waiting' | 'speech' | 'done' | 'timeout'"""
        self.t += dt
        if self.t <= self.calibrate:
            self.noise.append(rms)
            return "waiting"
        if rms > self.threshold:
            self.heard = True
            self.last_voice = self.t
            return "speech"
        if not self.heard:
            return "timeout" if self.t > self.no_speech_timeout else "waiting"
        return "done" if self.t - self.last_voice >= self.end_silence else "speech"


@dataclass
class Recording:
    audio: np.ndarray            # int16 mono
    rate: int
    heard_speech: bool
    device: str
    path: Path | None = None

    def to_16k(self) -> np.ndarray:
        x = self.audio.astype(np.float32) / 32768.0
        if self.rate == 16000:
            return x
        n = int(len(x) * 16000 / self.rate)
        return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


class Recorder:
    """Microphone with a sticky session: the input stream stays open for `session_seconds` after the last use, so
    follow-up questions need no Bluetooth mode flip (buds stay in call mode) and the first word is not clipped."""

    def __init__(self, out_dir: Path, device: int | None = None, prefer_buds: bool = True,
                 max_seconds: float = 12.0, max_hold_seconds: float = 90.0, session_seconds: float = 20.0) -> None:
        self.out_dir, self.max_seconds, self.max_hold = Path(out_dir), max_seconds, max_hold_seconds
        self.device_index, self.prefer_buds, self.session_seconds = device, prefer_buds, session_seconds
        self._stream = None
        self._q: queue.Queue = queue.Queue()
        self._collect = False
        self._info: tuple[int | None, str, int] | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.RLock()

    def _device(self) -> tuple[int | None, str, int]:
        import sounddevice as sd
        if self.device_index is None and self.prefer_buds:
            from budslab import audio
            try:
                d = audio.pick_device(None)
                return d["index"], d["name"], int(d["rate"])
            except LookupError:
                print("   (buds not listed as an input; using the default microphone)")
        idx = self.device_index if self.device_index is not None else sd.default.device[0]
        info = sd.query_devices(idx)
        return idx, info["name"], int(info["default_samplerate"])

    # -- session ---------------------------------------------------------------------
    def open(self) -> None:
        """Open (or keep) the input stream. Blocking: this is where the buds flip to call mode."""
        import sounddevice as sd
        with self._lock:
            self._cancel_timer()
            if self._stream is not None:
                return
            idx, name, rate = self._device()
            self._info = (idx, name, rate)

            def cb(indata, frames, t, status):
                if self._collect:
                    self._q.put(indata[:, 0].copy())

            self._stream = sd.InputStream(samplerate=rate, channels=1, dtype="int16", blocksize=int(rate * 0.02),
                                          device=idx, callback=cb)
            self._stream.start()

    def close(self) -> None:
        with self._lock:
            self._cancel_timer()
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                finally:
                    self._stream = None

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _arm_timer(self) -> None:
        if self.session_seconds <= 0:
            self.close()
            return
        with self._lock:
            self._cancel_timer()
            self._timer = threading.Timer(self.session_seconds, self.close)
            self._timer.daemon = True
            self._timer.start()

    # -- recording ---------------------------------------------------------------------
    def record(self, stop: threading.Event | None = None, label: str = "utterance", hold: bool = False) -> Recording:
        """Blocking. hold=True (toggle / push-to-talk): records until `stop` is set. Otherwise: until the speaker
        stops talking (end-of-speech detection); setting `stop` aborts early in both modes."""
        self.open()
        idx, name, rate = self._info
        with self._lock:
            self._cancel_timer()
            while not self._q.empty():
                self._q.get_nowait()
            self._collect = True
        chunks: list[np.ndarray] = []
        vad = EnergyVAD()
        limit = self.max_hold if hold else self.max_seconds
        t0 = time.time()
        try:
            while time.time() - t0 < limit:
                try:
                    c = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
                chunks.append(c)
                rms = float(np.sqrt(np.mean((c.astype(np.float32) / 32768.0) ** 2)))
                state = vad.feed(rms, len(c) / rate)
                if stop is not None and stop.is_set() and (not hold or time.time() - t0 > 0.3):
                    break
                if not hold and state in ("done", "timeout"):
                    break
        finally:
            self._collect = False
            self._arm_timer()
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
        heard = bool(audio.size and np.max(np.abs(audio)) > 300) if hold else vad.heard
        rec = Recording(audio, rate, heard, name)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        rec.path = self.out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^a-z0-9]+', '-', label.lower())}.wav"
        with wave.open(str(rec.path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(audio.tobytes())
        return rec


# ---- cues: short pleasant chimes instead of beeps ------------------------------------------------
_SR = 16000
_CHIMES = {                                   # (frequency Hz, seconds): a soft rising arpeggio = "go ahead"
    "ready": [(784, .11), (1047, .11), (1319, .26)],      # G5 C6 E6
    "done": [(1319, .10), (988, .24)],                    # E6 B5 (falling: "got it")
    "error": [(392, .16), (330, .32)],                    # G4 E4 (low, gentle)
}
_SYSTEM = {"ready": "Pop", "done": "Tink", "error": "Basso"}


def chime(kind: str) -> np.ndarray:
    """Bell-like notes: fundamental + soft harmonics with an exponential decay, so they sound like a chime."""
    parts = []
    for f, d in _CHIMES[kind]:
        t = np.arange(int(_SR * d)) / _SR
        tone = sum(a * np.sin(2 * np.pi * f * h * t) for h, a in ((1, 1.0), (2, 0.3), (3, 0.1)))
        env = np.minimum(1, t / 0.006) * np.exp(-t * (5.0 / d) * 0.6)
        parts.append(0.16 * tone * env)
    return np.concatenate(parts).astype(np.float32)


def make_cue(mode: str = "chime", files: dict[str, str] | None = None):
    """-> callable(kind). mode: chime (synthesised) | system (macOS sounds) | off. `files` overrides per kind."""
    files = files or {}

    def cue(kind: str) -> None:
        if mode == "off" and kind not in files:
            return
        try:
            if kind in files or mode == "system":
                import subprocess
                path = files.get(kind) or f"/System/Library/Sounds/{_SYSTEM[kind]}.aiff"
                subprocess.run(["afplay", path], check=False)
            else:
                import sounddevice as sd
                sd.play(chime(kind), _SR)
                sd.wait()
        except Exception:  # noqa: BLE001  a missing sound must never break the assistant
            pass
    return cue
