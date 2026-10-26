import base64
import io
import wave

import numpy as np

from buds_assistant.audio.capture import resample


def wav_to_audio(b64: str) -> np.ndarray:
    with wave.open(io.BytesIO(base64.b64decode(b64))) as w:
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return resample(raw[::w.getnchannels()], w.getframerate())
