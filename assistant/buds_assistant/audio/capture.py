"""Audio capture: sources (mic / file) and the RAM-only replay ring buffer. All audio is 16 kHz mono int16."""
from __future__ import annotations

import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

RATE = 16000
CHUNK = 320          # 20 ms


def resample(x: np.ndarray, src: int, dst: int = RATE) -> np.ndarray:
    if src == dst or x.size == 0:
        return x.astype(np.int16, copy=False)
    if src % dst == 0:                                    # e.g. 48k -> 16k: average (crude anti-alias)
        k = src // dst
        n = (x.size // k) * k
        return x[:n].reshape(-1, k).astype(np.float32).mean(axis=1).astype(np.int16)
    n = int(x.size * dst / src)
    return np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x.astype(np.float32)).astype(np.int16)


class RingBuffer:
    """The last N seconds of audio, in RAM only. Never written to disk by this class."""

    def __init__(self, seconds: float = 8.0, rate: int = RATE) -> None:
        self.rate, self.capacity = rate, int(seconds * rate)
        self._chunks: deque[np.ndarray] = deque()
        self._n = 0
        self._lock = threading.Lock()

    def resize(self, seconds: float) -> None:
        with self._lock:
            self.capacity = int(min(max(seconds, 5), 60) * self.rate)
            self._trim()

    def push(self, x: np.ndarray) -> None:
        with self._lock:
            self._chunks.append(x)
            self._n += x.size
            self._trim()

    def _trim(self) -> None:
        while self._n - self._chunks[0].size >= self.capacity if self._chunks else False:
            self._n -= self._chunks.popleft().size

    def last(self, seconds: float) -> np.ndarray:
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.int16)
            data = np.concatenate(list(self._chunks))
        return data[-int(seconds * self.rate):] if seconds * self.rate < data.size else data

    @property
    def seconds(self) -> float:
        return self._n / self.rate

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._n = 0


class CaptureSource(Protocol):
    rate: int
    name: str

    def start(self, on_chunk: Callable[[np.ndarray], None]) -> None: ...
    def stop(self) -> None: ...


class FileSource:
    """Plays a WAV as if it were a microphone. realtime=False delivers it as fast as possible (tests/simulator)."""
    name = "file"
    rate = RATE

    def __init__(self, path: Path | None = None, audio: np.ndarray | None = None, realtime: bool = False,
                 speed: float = 1.0, tail_silence: float = 1.0) -> None:
        if audio is None:
            with wave.open(str(path)) as w:
                raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                audio = resample(raw[::w.getnchannels()], w.getframerate())
        self.audio = np.concatenate([audio, np.zeros(int(tail_silence * RATE), dtype=np.int16)])
        self.realtime, self.speed = realtime, speed
        self.done = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, on_chunk: Callable[[np.ndarray], None]) -> None:
        def run():
            t0 = time.monotonic()
            for i in range(0, self.audio.size, CHUNK):
                if self._stop.is_set():
                    break
                on_chunk(self.audio[i:i + CHUNK])
                if self.realtime:                                  # schedule against the clock: summing sleeps drifts ~5% on macOS
                    time.sleep(max(0.0, t0 + (i + CHUNK) / RATE / self.speed - time.monotonic()))
            self.done.set()
        self._thread = threading.Thread(target=run, daemon=True, name="file-source")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2)


class MicSource:
    """sounddevice input. `prefer`: 'buds' (in-ear), 'mac' (built-in mic, for remote mode) or an explicit index."""

    def __init__(self, prefer: str | int = "buds") -> None:
        self.prefer, self.rate, self.name = prefer, RATE, "mic"
        self._stream = None

    def _pick(self) -> dict:
        from budslab import audio
        devs = audio.list_inputs()
        if isinstance(self.prefer, int):
            return next(d for d in devs if d["index"] == self.prefer)
        if self.prefer == "buds":
            for d in devs:
                if d["is_buds"]:
                    return d
        for d in devs:                                    # built-in mic
            if "macbook" in d["name"].lower() or "built-in" in d["name"].lower():
                return d
        if not devs:
            raise RuntimeError("no input devices")
        return next((d for d in devs if d["is_default"]), devs[0])

    def start(self, on_chunk: Callable[[np.ndarray], None]) -> None:
        import sounddevice as sd
        d = self._pick()
        self.name = d["name"]
        src = int(d["rate"])
        block = int(src * 0.02)

        def cb(indata, frames, t, status):
            on_chunk(resample(indata[:, 0].copy(), src))

        self._stream = sd.InputStream(samplerate=src, channels=1, dtype="int16", blocksize=block, device=d["index"],
                                      callback=cb)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
