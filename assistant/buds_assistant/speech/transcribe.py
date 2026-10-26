"""Segment transcription. English is first-class; Telugu speech is an EXPERIMENTAL backend (measured: unusable with
Whisper small/medium on this machine), kept behind a flag so a better model can be dropped in."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np


@dataclass
class Transcript:
    text: str
    lang: str = "en"
    conf: float = 0.0
    experimental: bool = False


class SegmentTranscriber(Protocol):
    def transcribe(self, audio: np.ndarray, lang_hint: str | None = None) -> Transcript: ...


def _f32(a: np.ndarray) -> np.ndarray:
    return a.astype(np.float32) / 32768.0 if a.dtype == np.int16 else a.astype(np.float32)


def boost(x: np.ndarray, target: float = 0.5, max_gain: float = 20.0) -> np.ndarray:
    """Level up quiet speech (a video heard across the room, a far-away voice): Whisper does much better at a normal level."""
    peak = float(np.abs(x).max()) if x.size else 0.0
    if peak < 1e-4 or peak >= 0.3:
        return x
    return x * min(max_gain, target / peak)


HALLUCINATIONS = ("thank you for watching", "thanks for watching", "see you in the next video", "see you next time",
                  "like and subscribe", "please subscribe", "subscribe to my channel", "subtitles by", "amara.org")


def is_loop(text: str) -> bool:
    """A model stuck repeating one syllable ('na na na na ...') is not a transcript."""
    w = [x.strip(".,!?").lower() for x in text.split()]
    return len(w) >= 6 and len(set(w)) <= 2


def has_telugu(text: str) -> bool:
    return any("\u0c00" <= c <= "\u0c7f" for c in text)


VOCAB = "Hey Sidekick, remind me. Sidekick, what is on my calendar? Autopilot."      # spelling hint: the assistant's own name is not in Whisper's vocabulary


class WhisperEn:
    def __init__(self, model: str = "small.en", model_obj=None) -> None:
        if model_obj is None:
            from faster_whisper import WhisperModel
            try:
                model_obj = WhisperModel(model, device="cpu", compute_type="int8")
            except Exception:  # noqa: BLE001  not downloaded and offline: the small fast model is better than nothing
                model_obj = WhisperModel("base.en", device="cpu", compute_type="int8")
        self.model = model_obj
        self.vad = True                                   # our segmenter already cut speech out; Interpreter turns this second pass off to save time

    def transcribe(self, audio: np.ndarray, lang_hint: str | None = None) -> Transcript:
        x = _f32(audio)
        if x.size < 3200 or float(np.sqrt(np.mean(x ** 2))) < 0.003:       # silence: never invent words
            return Transcript("", "en", 0.0)
        segs, _ = self.model.transcribe(boost(x), language="en", beam_size=1, vad_filter=self.vad, condition_on_previous_text=False,
                                        no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4,
                                        initial_prompt=VOCAB)
        parts, probs = [], []
        for s in segs:
            low = s.text.lower()
            if getattr(s, "no_speech_prob", 0.0) > 0.6 or getattr(s, "avg_logprob", -0.3) < -1.0 or any(h in low for h in HALLUCINATIONS):
                continue                                  # silence, a guess nobody would stand behind, or a stock video outro
            parts.append(s.text.strip())
            probs.append(math.exp(min(0.0, getattr(s, "avg_logprob", -0.3))))
        text = " ".join(parts).strip()
        if is_loop(text):
            return Transcript("", "en", 0.0)
        return Transcript(text, "en", float(np.mean(probs)) if probs else 0.0)


class WhisperTe:
    """Telugu speech via a Telugu-tuned Whisper (CTranslate2). Stock Whisper small/medium produced garbage on our test
    clip; `ukta-app/whisper-telugu-ct2` transcribed it correctly in ~2 s. Verified on CLEAN SYNTHETIC speech only, so
    results stay flagged `experimental`: shown and translatable, but never stored as memory or used for hints."""
    def __init__(self, model: str = "ukta-app/whisper-telugu-ct2", model_obj=None) -> None:
        if model_obj is None:
            from faster_whisper import WhisperModel
            model_obj = WhisperModel(model, device="cpu", compute_type="int8")
        self.model = model_obj
        self.vad = True

    def transcribe(self, audio: np.ndarray, lang_hint: str | None = None) -> Transcript:
        x = _f32(audio)
        if x.size < 3200 or float(np.sqrt(np.mean(x ** 2))) < 0.003:
            return Transcript("", "te", 0.0, True)
        segs, info = self.model.transcribe(boost(x), language="te", beam_size=1, vad_filter=self.vad, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segs).strip()
        return Transcript(text, "te", float(getattr(info, "language_probability", 0.0)), True)


WhisperTeExperimental = WhisperTe          # backwards-compatible name


class LanguageGate:
    """Tiny multilingual Whisper used only to decide Telugu vs English (~0.1 s per segment)."""
    def __init__(self, model: str = "tiny", model_obj=None) -> None:
        if model_obj is None:
            from faster_whisper import WhisperModel
            model_obj = WhisperModel(model, device="cpu", compute_type="int8")
        self.model = model_obj

    def telugu_probability(self, audio: np.ndarray) -> float:
        x = _f32(audio)
        if x.size < 3200:
            return 0.0
        _, _, probs = self.model.detect_language(boost(x))
        d = dict(probs)
        te, en = d.get("te", 0.0), d.get("en", 0.0)
        return te / (te + en) if te + en > 0 else 0.0


class RoutingTranscriber:
    """English by default; Telugu when the language gate says so. Lazy-loads the Telugu model on first use."""
    def __init__(self, english: SegmentTranscriber, telugu_factory: Callable[[], SegmentTranscriber],
                 gate: LanguageGate | None = None, threshold: float = 0.6, eager: bool = False) -> None:
        self.english, self._factory, self.gate, self.threshold = english, telugu_factory, gate, threshold
        self._telugu: SegmentTranscriber | None = None
        self.eager = eager                                 # interpreting: also try Telugu when English comes out weak

    @property
    def eager(self) -> bool:
        return self._eager

    @eager.setter
    def eager(self, on: bool) -> None:
        self._eager = on
        for t in (self.english, self._telugu):             # interpreting: segments are already speech, skip the recognisers' own VAD pass
            if t is not None and hasattr(t, "vad"):
                t.vad = not on

    def warm(self) -> None:
        """Load the Telugu model now (the first Telugu phrase should not wait for it)."""
        self._te()

    def transcribe(self, audio: np.ndarray, lang_hint: str | None = None) -> Transcript:
        use_te, p = lang_hint == "te", 0.0
        if lang_hint is None and self.gate is not None:
            p = self.gate.telugu_probability(audio)
            use_te = p >= self.threshold
        if not use_te:
            en = self.english.transcribe(audio)
            weak = en.conf < 0.6 or not en.text or is_loop(en.text)
            if not (self.eager and lang_hint is None and p >= 0.1 and weak):
                return en
            te = self._te().transcribe(audio)
            return te if has_telugu(te.text) else en
        return self._te().transcribe(audio)

    def _te(self):
        if self._telugu is None:
            self._telugu = self._factory()
            if hasattr(self._telugu, "vad"):
                self._telugu.vad = not self._eager
        return self._telugu


class FakeTranscriber:
    """Deterministic: returns scripted lines in order (or calls a function with the audio)."""
    def __init__(self, script: list[str] | Callable[[np.ndarray], str]) -> None:
        self.script, self.i = script, 0

    def transcribe(self, audio: np.ndarray, lang_hint: str | None = None) -> Transcript:
        if callable(self.script):
            return Transcript(self.script(audio), "en", 0.9)
        text = self.script[self.i % len(self.script)] if self.script else ""
        self.i += 1
        return Transcript(text, "en", 0.9)
