import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

MODEL = Path(__file__).resolve().parents[2] / "models" / "wespeaker_en_voxceleb_resnet34_LM.onnx"
needs_say = pytest.mark.skipif(not shutil.which("say"), reason="needs macOS say")
needs_model = pytest.mark.skipif(not MODEL.exists(), reason="speaker model not downloaded")


def synth(voice: str, text: str, path: Path, rate: int = 16000) -> np.ndarray:
    """Render speech with macOS `say` -> int16 mono 16 kHz. Silent: writes a file, does not play."""
    subprocess.run(["say", "-v", voice, "-o", str(path), "--file-format=WAVE", f"--data-format=LEI16@{rate}", "--", text],
                   check=True)
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
