"""Streaming utterance segmenter: adaptive energy VAD with pre-roll. Feeds speaker-ID and transcription."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from buds_assistant.audio.capture import RATE

FRAME = 320   # 20 ms


@dataclass
class Segment:
    t0: float            # seconds since the stream started
    t1: float
    audio: np.ndarray    # int16

    @property
    def seconds(self) -> float:
        return self.audio.size / RATE


class Segmenter:
    def __init__(self, rate: int = RATE, min_speech: float = 0.5, end_silence: float = 0.7, preroll: float = 0.25,
                 max_len: float = 20.0, min_abs: float = 0.006, ratio: float = 3.0, calibrate: float = 0.3, max_noise: float = 0.012,
                 soft_len: float | None = None, soft_silence: float = 0.2) -> None:
        self.soft_len, self.soft_silence = soft_len, soft_silence      # Interpreter: past soft_len seconds, a short pause already ends the clause
        self.rate, self.min_speech, self.end_silence, self.max_len = rate, min_speech, end_silence, max_len
        self.min_abs, self.ratio, self.calibrate, self.max_noise = min_abs, ratio, calibrate, max_noise
        self._hist: deque[float] = deque(maxlen=250)           # the last 5 s of frame levels: the quiet ones are the room
        self._buf = np.zeros(0, dtype=np.int16)
        self._pre: deque[np.ndarray] = deque(maxlen=max(1, int(preroll * rate / FRAME)))
        self._reset_state()
        self.samples = 0
        self.noise = 0.0
        self._calib: list[float] = []
        self.user_level = 0.0

    @property
    def speaking(self) -> bool:
        """True while an utterance is in progress (used to hold whispers until the next gap)."""
        return self._active

    def _reset_state(self) -> None:
        self._active = False
        self._frames: list[np.ndarray] = []
        self._voiced = 0
        self._silent = 0
        self._start = 0.0
        self._hot = 0

    @property
    def threshold(self) -> float:
        return max(self.min_abs, self.noise * self.ratio)

    def feed(self, chunk: np.ndarray) -> list[Segment]:
        out: list[Segment] = []
        self._buf = np.concatenate([self._buf, chunk])
        while self._buf.size >= FRAME:
            frame, self._buf = self._buf[:FRAME], self._buf[FRAME:]
            seg = self._frame(frame)
            if seg:
                out.append(seg)
        return out

    def _frame(self, f: np.ndarray) -> Segment | None:
        t = self.samples / self.rate
        self.samples += FRAME
        rms = float(np.sqrt(np.mean((f.astype(np.float32) / 32768.0) ** 2)))
        self.user_level = rms
        self._hist.append(rms)
        if t < self.calibrate:                                    # learn the room first
            self._calib.append(rms)
            self.noise = min(self.max_noise, float(np.median(self._calib)))
            self._pre.append(f)
            return None
        if len(self._hist) >= 25 and self.samples % (FRAME * 5) == 0:   # the room is the quiet part of the last few seconds, even if speech was already playing at the start
            self.noise = min(self.max_noise, float(np.percentile(self._hist, 15)))
        loud = rms > self.threshold
        if not self._active:
            self._pre.append(f)
            self._hot = self._hot + 1 if loud else 0
            if self._hot >= 2:                                    # 40 ms of voice starts a segment
                self._active = True
                self._frames = list(self._pre)
                self._start = t - len(self._frames) * FRAME / self.rate + FRAME / self.rate
                self._voiced, self._silent = self._hot, 0
            else:
                self.noise = min(self.max_noise, 0.97 * self.noise + 0.03 * rms)        # track slow room changes only while idle
            return None
        self._frames.append(f)
        if loud:
            self._voiced += 1
            self._silent = 0
        else:
            self._silent += 1
        dur = len(self._frames) * FRAME / self.rate
        silent_s = self._silent * FRAME / self.rate
        if silent_s >= self.end_silence or dur >= self.max_len or (self.soft_len and dur >= self.soft_len and silent_s >= self.soft_silence):
            return self._close(t + FRAME / self.rate)
        return None

    def _close(self, t_end: float) -> Segment | None:
        voiced_s = self._voiced * FRAME / self.rate
        keep = self._frames[:len(self._frames) - max(0, self._silent - 8)]    # trim trailing silence (keep 160 ms)
        audio = np.concatenate(keep) if keep else np.zeros(0, dtype=np.int16)
        start = self._start
        self._reset_state()
        self._pre.clear()
        if voiced_s < self.min_speech:
            return None
        return Segment(start, start + audio.size / self.rate, audio)

    def flush(self) -> list[Segment]:
        if self._active:
            s = self._close(self.samples / self.rate)
            return [s] if s else []
        return []
