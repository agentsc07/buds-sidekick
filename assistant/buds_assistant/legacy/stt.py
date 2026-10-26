"""Speech to text. Local Whisper (faster-whisper) by default: audio never leaves the machine."""
from __future__ import annotations

from typing import Protocol

import numpy as np


class STT(Protocol):
    needs_audio: bool

    def transcribe(self, audio16k: np.ndarray | None) -> str: ...


class WhisperSTT:
    needs_audio = True

    def __init__(self, model: str = "base.en") -> None:
        from faster_whisper import WhisperModel      # first use downloads the model (~140 MB for base.en)
        self.model = WhisperModel(model, device="cpu", compute_type="int8")

    def transcribe(self, audio16k: np.ndarray | None) -> str:
        if audio16k is None or audio16k.size < 1600:
            return ""
        segs, _ = self.model.transcribe(audio16k.astype(np.float32), language="en", beam_size=1,
                                        vad_filter=True, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip()


class TypedSTT:
    """Dev fallback: no microphone, you type what you would have said."""
    needs_audio = False

    def transcribe(self, audio16k: np.ndarray | None) -> str:
        try:
            return input("   you (typed) > ").strip()
        except EOFError:
            return ""


def make_stt(kind: str, model: str = "base.en") -> STT:
    if kind == "typed":
        return TypedSTT()
    return WhisperSTT(model)
