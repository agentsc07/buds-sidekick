"""A scripted three-person conversation rendered with macOS voices: for the simulator and demos (no humans needed)."""
from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

SCRIPT = [("Albert", "The budget for the third quarter is two million dollars"),
          ("Samantha", "That sounds fine, when can you send me the full report"),
          ("Daniel", "Excuse me, I have a question about the parking permit"),
          ("Albert", "I will send you the report by Friday afternoon"),
          ("Daniel", "The permit expires at the end of the month"),
          ("Samantha", "Thank you, I will check it on Friday")]


SCRIPT_TE = [("Geeta", "రేపు మధ్యాహ్నం మన సమావేశం మూడు గంటలకు ఉంటుంది, దయచేసి సమయానికి రండి."),
             ("Albert", "Thanks, I will be there on time tomorrow"),
             ("Geeta", "మీరు నాకు శుక్రవారం మధ్యాహ్నం వరకు రిపోర్ట్ పంపగలరా?")]


def render(voice: str, text: str, path: Path) -> np.ndarray:
    subprocess.run(["say", "-v", voice, "-o", str(path), "--file-format=WAVE", "--data-format=LEI16@16000", "--", text], check=True)
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def demo_audio(gap: float = 1.2, language: str = "en") -> tuple[np.ndarray, list[tuple[str, str]]]:
    script = SCRIPT_TE if language == "te" else SCRIPT
    rng = np.random.default_rng(1)
    quiet = lambda s: (rng.standard_normal(int(s * 16000)) * 40).astype(np.int16)   # noqa: E731
    parts = [quiet(1.0)]
    with tempfile.TemporaryDirectory() as d:
        for v, t in script:
            parts += [render(v, t, Path(d) / "x.wav"), quiet(gap)]
    return np.concatenate(parts), script


def enrol_demo_voices(speaker, names: dict[str, str] | None = None) -> None:
    """Enrol 'Me' (Samantha) and 'Ravi' (Albert) from short renderings, for demos."""
    names = names or {"Samantha": "Me", "Albert": "Ravi"}
    lines = {"Samantha": ["We should call the client tomorrow morning", "I prefer to meet on Wednesday afternoon"],
             "Albert": ["Let us review the schedule for next week", "Please confirm the delivery address again"]}
    with tempfile.TemporaryDirectory() as d:
        for voice, name in names.items():
            speaker.enroll(name, [render(voice, t, Path(d) / "e.wav") for t in lines[voice]], "demo voice (synthetic)")
