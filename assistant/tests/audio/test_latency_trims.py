"""Latency trims that do not cost accuracy: skip work whose result nobody uses."""
import numpy as np

from buds_assistant.audio.capture import RingBuffer
from buds_assistant.core.config import Config
from buds_assistant.core.events import EventBus
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.core.pipeline import ConversationPipeline
from buds_assistant.audio.segmenter import Segment
from buds_assistant.speech.speaker import SpeakerEngine
from buds_assistant.core.store import Store
from buds_assistant.speech.transcribe import FakeTranscriber, RoutingTranscriber, WhisperEn, WhisperTe, Transcript
from test_speaker import FakeEmbedder, clip


def _pipe(tmp_path, two_way=False):
    s = Store(tmp_path)
    spk = SpeakerEngine(FakeEmbedder(), s, min_seconds=1.2)
    spk.enroll("Me", [clip(1), clip(1)], "ok")
    calls = []
    real = spk.identify
    spk.identify = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    p = ConversationPipeline(Config(data_dir=tmp_path, interpreter_two_way=two_way), s, spk, FakeTranscriber(["hello there"]), Memory(s, FakeLLM()), None, EventBus(), RingBuffer(8))
    p.conv_id = s.start_conversation("interpreter")
    p.mode = "interpreter"
    return p, calls


def test_one_way_interpreting_does_not_spend_time_identifying_the_speaker(tmp_path):
    p, calls = _pipe(tmp_path, two_way=False)
    e = p.feed_segment(Segment(0, 2, clip(1, 32000)))
    assert calls == [] and e["text"] == "hello there"
    assert e["speaker"] == "" and e["no_id"] is True                        # not "Unknown": nobody was asked who it was


def test_two_way_interpreting_still_identifies_who_is_speaking(tmp_path):
    p, calls = _pipe(tmp_path, two_way=True)
    e = p.feed_segment(Segment(0, 2, clip(1, 32000)))
    assert calls == [1] and e["speaker"] == "Me" and e["no_id"] is False


class _Model:
    def __init__(self): self.kw = None
    def transcribe(self, x, **kw):
        self.kw = kw
        class S: text = " hi"; no_speech_prob = 0.0; avg_logprob = -0.2
        class I: language_probability = 0.9
        return iter([S()]), I()


AUDIO = (np.sin(np.arange(16000) / 7) * 9000).astype(np.int16)


def test_segments_that_are_already_speech_skip_the_second_voice_activity_pass():
    m = _Model(); en = WhisperEn(model_obj=m)
    en.transcribe(AUDIO); assert m.kw["vad_filter"] is True
    en.vad = False; en.transcribe(AUDIO); assert m.kw["vad_filter"] is False
    mt = _Model(); te = WhisperTe(model_obj=mt); te.vad = False; te.transcribe(AUDIO); assert mt.kw["vad_filter"] is False


def test_interpreting_turns_the_extra_vad_pass_off_on_both_recognisers():
    en, mt = WhisperEn(model_obj=_Model()), _Model()
    r = RoutingTranscriber(en, lambda: WhisperTe(model_obj=mt), None)
    r.warm()
    r.eager = True
    assert en.vad is False and r._telugu.vad is False
    r.eager = False
    assert en.vad is True and r._telugu.vad is True


def test_the_ui_is_told_when_the_mac_is_too_busy_for_a_quick_answer():
    from buds_assistant.core.uistate import UiState
    bus = EventBus()
    ui = UiState(bus, Config())
    ui.load_fn = lambda: (40.0, 8)
    ui.refresh()
    assert ui.snapshot()["busy"] is True
    ui.load_fn = lambda: (3.0, 8)
    ui.refresh()
    assert ui.snapshot()["busy"] is False
    n = len(bus.recent(100, {"ui_state"}))
    ui.refresh()
    assert len(bus.recent(100, {"ui_state"})) == n                    # no event when nothing changed


def test_spoken_answers_from_memory_are_one_short_sentence():
    from buds_assistant.intelligence.brain import spoken_trim
    long = "No, you don't have any specific questions listed for your meeting with Ravi. You could ask about the budget."
    assert spoken_trim(long, 1) == "No, you don't have any specific questions listed for your meeting with Ravi."


def test_quiet_speech_is_levelled_up_before_recognition():
    from buds_assistant.speech.transcribe import boost
    quiet = (np.sin(np.arange(16000) / 7) * 0.04).astype(np.float32)
    loud = boost(quiet)
    assert 0.4 < float(np.abs(loud).max()) <= 0.6
    normal = (np.sin(np.arange(16000) / 7) * 0.5).astype(np.float32)
    assert np.allclose(boost(normal), normal)
    assert float(np.abs(boost(np.zeros(16000, dtype=np.float32))).max()) == 0.0


def test_the_ear_route_plays_on_the_buds_even_when_the_mac_default_is_the_speakers(monkeypatch):
    import sys, types
    from buds_assistant.audio.output import SoundDevicePlayer
    devs = [{"name": "Sai's Buds FE", "max_output_channels": 0}, {"name": "Sai's Buds FE", "max_output_channels": 2},
            {"name": "MacBook Air Speakers", "max_output_channels": 2}]
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(query_devices=lambda: devs))
    assert SoundDevicePlayer("buds")._device() == 1                       # the output side of the buds, not their microphone entry
    assert SoundDevicePlayer("speakers")._device() == 2
    assert SoundDevicePlayer("nonexistent")._device() is None             # not connected as audio: fall back to the default output


def test_the_language_gate_is_asked_for_every_phrase():
    """Tried and rejected: skipping the gate after Telugu saved 0.3 s but a spoken English reply was then 'recognised' by the Telugu model as
    Telugu letters (a transliteration), which is worse than the delay. Two people alternating languages is exactly the Interpreter's use."""
    class Gate:
        calls = 0
        def telugu_probability(self, a): Gate.calls += 1; return 0.95
    r = RoutingTranscriber(_Eng(), lambda: _TeOK(), Gate())
    r.transcribe(AUDIO); r.transcribe(AUDIO); r.transcribe(AUDIO)
    assert Gate.calls == 3


class _Eng:
    def transcribe(self, a, lang_hint=None): return Transcript("english words", "en", 0.9)


class _TeOK:
    def transcribe(self, a, lang_hint=None): return Transcript("రేపు కలుద్దాం", "te", 0.9, True)


def test_the_translation_voice_speaks_a_little_faster_than_conversation():
    from buds_assistant.speech.interpreter import Interpreter
    assert Interpreter.WPM >= 200


class _Counting:
    def __init__(self): self.sizes = []
    def transcribe(self, a, lang_hint=None):
        self.sizes.append(len(a)); return Transcript("hello there", "en", 0.9)


def test_when_behind_queued_phrases_are_recognised_in_one_pass():
    """Every recognition pass costs ~1.3 s before it reads a single word (the model always looks at a 30 s window), so a backlog of
    three phrases takes 3 passes. Merging them into one pass shares that cost."""
    s = Store.__new__(Store)
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    s = Store(tmp)
    spk = SpeakerEngine(FakeEmbedder(), s, min_seconds=1.2)
    tr = _Counting()
    p = ConversationPipeline(Config(data_dir=tmp), s, spk, tr, Memory(s, FakeLLM()), None, EventBus(), RingBuffer(8))
    p.conv_id = s.start_conversation("interpreter"); p.mode = "interpreter"
    segs = [Segment(0, 2, clip(1, 32000)), Segment(2.5, 4.5, clip(1, 32000)), Segment(5.0, 7.0, clip(1, 32000))]
    out = p.merge_queued(segs[0], [segs[1], segs[2]])
    assert out.t0 == 0 and out.t1 == 7.0 and len(out.audio) >= 3 * 32000 and len(out.audio) < 3 * 32000 + 16000      # joined with short silences
    far = Segment(40.0, 42.0, clip(1, 32000))
    out2 = p.merge_queued(segs[0], [far])
    assert out2.t1 == 2 and len(out2.audio) == 32000                                                     # a long pause is a new turn: not merged
    big = [Segment(0, 6, clip(1, 96000)), Segment(6.2, 12, clip(1, 96000)), Segment(12.2, 18, clip(1, 96000))]
    out3 = p.merge_queued(big[0], big[1:])
    assert out3.t1 <= 12.0                                                                              # never more than ~12 s in one pass
