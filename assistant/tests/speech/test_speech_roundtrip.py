"""Real components: macOS `say` renders speech to a file (silent), Whisper transcribes it, the agent answers."""
import shutil
import subprocess
import wave
from datetime import datetime

import numpy as np
import pytest

from buds_assistant.intelligence.agent import RuleAgent

pytestmark = pytest.mark.skipif(not shutil.which("say"), reason="needs macOS say")


def synth(tmp_path, text):
    p = tmp_path / "s.wav"
    subprocess.run(["say", "-o", str(p), "--file-format=WAVE", "--data-format=LEI16@16000", "--", text], check=True)
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


@pytest.fixture(scope="module")
def stt():
    pytest.importorskip("faster_whisper")
    from buds_assistant.legacy.stt import WhisperSTT
    try:
        return WhisperSTT("base.en")
    except Exception as exc:  # model not downloadable offline
        pytest.skip(f"whisper model unavailable: {exc}")


@pytest.mark.parametrize("phrase,intent", [("What is twelve plus seven", "math"), ("What time is it", "time"),
                                            ("What is the current petrol price", "needs_online")])
def test_say_whisper_agent(tmp_path, stt, phrase, intent):
    text = stt.transcribe(synth(tmp_path, phrase))
    assert text, "empty transcript"
    reply = RuleAgent(tmp_path / "n.jsonl").respond(text, {"now": datetime(2026, 1, 1, 9, 30)})
    assert reply.intent == intent, (text, reply)
