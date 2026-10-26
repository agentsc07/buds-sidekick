import numpy as np

from buds_assistant.speech.transcribe import FakeTranscriber, WhisperEn
from helpers import needs_say, synth


class _Seg:
    def __init__(self, text, nsp=0.0, lp=-0.2):
        self.text, self.no_speech_prob, self.avg_logprob = text, nsp, lp


class _Model:
    def __init__(self, segs):
        self.segs, self.called = segs, 0

    def transcribe(self, x, **kw):
        self.called += 1
        return iter(self.segs), None


def test_silence_never_reaches_the_model():
    m = _Model([_Seg("Thank you.")])
    t = WhisperEn(model_obj=m)
    assert t.transcribe(np.zeros(16000, dtype=np.int16)).text == "" and m.called == 0     # no hallucinated words
    quiet = (np.random.default_rng(0).standard_normal(16000) * 20).astype(np.int16)
    assert t.transcribe(quiet).text == "" and m.called == 0


def test_no_speech_segments_dropped():
    audio = (np.sin(np.arange(16000) / 5) * 8000).astype(np.int16)
    t = WhisperEn(model_obj=_Model([_Seg("real words", 0.1), _Seg("ghost", 0.9)]))
    r = t.transcribe(audio)
    assert r.text == "real words" and 0 < r.conf <= 1


def test_fake_transcriber():
    f = FakeTranscriber(["one", "two"])
    assert [f.transcribe(np.zeros(1)).text for _ in range(3)] == ["one", "two", "one"]


@needs_say
def test_real_say_roundtrip(tmp_path):
    import pytest
    pytest.importorskip("faster_whisper")
    r = WhisperEn("base.en").transcribe(synth("Samantha", "Please send me the report on Friday", tmp_path / "a.wav"))
    assert "report" in r.text.lower() and "friday" in r.text.lower()
