import asyncio

import numpy as np
import pytest

from buds_assistant.speech.transcribe import LanguageGate, RoutingTranscriber, Transcript, WhisperTe
from helpers import needs_say, synth

TE_SENT = "రేపు మధ్యాహ్నం మన సమావేశం మూడు గంటలకు ఉంటుంది, దయచేసి సమయానికి రండి."


class _Model:
    def __init__(self, probs):
        self.probs = probs

    def detect_language(self, x):
        return "x", 0.0, self.probs


class _Seg:
    text = " రేపు కలుద్దాం "


class _TeModel:
    def transcribe(self, x, **kw):
        class I: language_probability = 0.93
        return iter([_Seg()]), I()


class _En:
    def transcribe(self, a, lang_hint=None):
        return Transcript("english words", "en", 0.9)


AUDIO = (np.sin(np.arange(16000) / 7) * 9000).astype(np.int16)


def test_gate_probability_restricted_to_te_vs_en():
    assert LanguageGate(model_obj=_Model([("te", 0.6), ("en", 0.2), ("hi", 0.2)])).telugu_probability(AUDIO) == pytest.approx(0.75)
    assert LanguageGate(model_obj=_Model([("hi", 1.0)])).telugu_probability(AUDIO) == 0.0       # neither: stay English
    assert LanguageGate(model_obj=_Model([("te", 1.0)])).telugu_probability(AUDIO[:100]) == 0.0    # too short


def test_router_picks_language_and_loads_telugu_lazily():
    built = []
    r = RoutingTranscriber(_En(), lambda: built.append(1) or WhisperTe(model_obj=_TeModel()),
                           LanguageGate(model_obj=_Model([("en", 0.9), ("te", 0.1)])))
    assert r.transcribe(AUDIO).lang == "en" and not built                       # Telugu model not even loaded
    r.gate = LanguageGate(model_obj=_Model([("te", 0.9), ("en", 0.1)]))
    t = r.transcribe(AUDIO)
    assert t.lang == "te" and t.experimental and "కలుద్దాం" in t.text and built == [1]
    r.transcribe(AUDIO)
    assert built == [1]                                                          # loaded once


def test_telugu_silence_returns_nothing():
    assert WhisperTe(model_obj=_TeModel()).transcribe(np.zeros(16000, dtype=np.int16)).text == ""


@pytest.mark.slow
@needs_say
def test_real_telugu_roundtrip_and_translation(tmp_path):
    pytest.importorskip("faster_whisper")
    from buds_assistant.intelligence.llm import OllamaClient
    from buds_assistant.speech.translate import Translator, detect_lang
    audio = synth("Geeta", TE_SENT, tmp_path / "te.wav")
    gate = LanguageGate("tiny")
    assert gate.telugu_probability(audio) > 0.6
    t = WhisperTe().transcribe(audio)
    assert "సమావేశం" in t.text and "మూడు" in t.text, t.text                     # key words recognised
    c = OllamaClient()
    if c.available():
        r = Translator(c).translate(t.text, "te", "en")
        assert r.ok and detect_lang(r.text) == "en" and "three" in r.text.lower() or "3" in r.text


class _Mumble:
    def transcribe(self, a, lang_hint=None):
        return Transcript("Na na na na na na na na", "en", 0.46)


def _te(built=None):
    return lambda: WhisperTe(model_obj=_TeModel())


def test_interpreting_listens_for_telugu_when_english_comes_out_as_mumbling():
    """Real session: Telugu speech went to the English model as 'na na na' because the language gate said 0.3 (< 0.6)."""
    gate = LanguageGate(model_obj=_Model([("te", 0.3), ("en", 0.7)]))
    plain = RoutingTranscriber(_Mumble(), _te(), gate)
    assert plain.transcribe(AUDIO).lang == "en"                                  # conversation mode keeps the strict gate
    eager = RoutingTranscriber(_Mumble(), _te(), gate, eager=True)
    t = eager.transcribe(AUDIO)
    assert t.lang == "te" and "కలుద్దాం" in t.text


def test_interpreting_keeps_clear_english_as_english_even_if_the_gate_is_unsure():
    gate = LanguageGate(model_obj=_Model([("te", 0.3), ("en", 0.7)]))
    eager = RoutingTranscriber(_En(), _te(), gate, eager=True)
    assert eager.transcribe(AUDIO).lang == "en"


def test_repeated_syllable_loops_are_not_transcripts():
    from buds_assistant.speech.transcribe import is_loop
    assert is_loop("nah nah nah nah nah nah nah nah nah nah") and is_loop("Na na na na na na")
    assert not is_loop("I'll send the report on Friday") and not is_loop("no no no")
