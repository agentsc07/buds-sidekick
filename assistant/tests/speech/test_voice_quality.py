"""Voice and person detection: what the first real-hardware session showed was wrong (synthetic demo voices answering for real
people, one huge enrolment clip, guessing on one-word utterances, whisper inventing 'thank you for watching')."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from buds_assistant.speech.calibrate import evaluate
from buds_assistant.audio.capture import RingBuffer
from buds_assistant.core.config import Config, simulator_dir
from buds_assistant.dashboard.server import create_app
from buds_assistant.core.events import EventBus
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.core.pipeline import ConversationPipeline
from buds_assistant.audio.segmenter import Segment
from buds_assistant.speech.speaker import SpeakerEngine, chunks
from buds_assistant.core.store import Store
from buds_assistant.speech.transcribe import FakeTranscriber, WhisperEn
from test_dashboard import _make, wav_b64
from test_speaker import FakeEmbedder, clip


@pytest.fixture
def client(tmp_path):
    sk = _make(Config(data_dir=tmp_path), FakeLLM())
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def test_simulator_never_shares_the_real_data_folder(tmp_path):
    assert simulator_dir(tmp_path / "data") == tmp_path / "data-sim"


def test_demo_voices_only_load_in_simulator_mode(client):
    client.sk.simulate = False
    r = client.post("/api/people/demo")
    assert r.status_code == 400 and "simulator" in r.json()["detail"]


def test_chunks_split_long_audio_with_overlap():
    a = np.arange(16000 * 12, dtype=np.int16)
    c = chunks(a, seconds=4.0, overlap=1.0)
    assert len(c) == 4 and all(x.size == 16000 * 4 for x in c[:3]) and c[-1].size >= 16000 * 2
    assert chunks(np.zeros(16000, dtype=np.int16), 4.0, 1.0)[0].size == 16000            # short audio stays one chunk


def test_enrolment_stores_several_voiceprints_from_one_recording(client):
    r = client.post("/api/v2/setup/enroll-self", json={"wav_base64": wav_b64(1, seconds=12)})
    assert r.status_code == 200
    me = client.sk.store.person_by_name("Me")
    assert len(client.sk.store.voice_samples(me["id"])) >= 3                              # one 20 s clip made one fragile voiceprint


def test_more_voice_samples_can_be_added_later_from_another_microphone(client):
    assert client.post("/api/v2/setup/add-voice-sample", json={"wav_base64": wav_b64(1, seconds=6)}).status_code == 400   # not enrolled yet
    client.post("/api/v2/setup/enroll-self", json={"wav_base64": wav_b64(1, seconds=6)})
    me = client.sk.store.person_by_name("Me")["id"]
    before = len(client.sk.store.voice_samples(me))
    assert client.post("/api/v2/setup/add-voice-sample", json={"wav_base64": wav_b64(1, seconds=6)}).status_code == 200
    assert len(client.sk.store.voice_samples(me)) > before


def build(tmp_path, texts=("hello there",)):
    cfg = Config(data_dir=tmp_path)
    s = Store(tmp_path)
    spk = SpeakerEngine(FakeEmbedder(), s, min_seconds=1.2)
    ana = spk.enroll("Ana", [clip(1), clip(1)], "ok")
    p = ConversationPipeline(cfg, s, spk, FakeTranscriber(list(texts)), Memory(s, FakeLLM()), None, EventBus(), RingBuffer(8))
    p.conv_id = s.start_conversation("listen")
    return s, p, ana


def test_a_one_word_utterance_continues_the_previous_speaker(tmp_path):
    s, p, ana = build(tmp_path, ["I will send the report", "okay"])
    a = p.feed_segment(Segment(0, 2, clip(1, 16000 * 2)))
    b = p.feed_segment(Segment(2.3, 2.9, clip(1, 8000)))                                  # 0.5 s: too short to identify
    assert a["speaker"] == "Ana" and b["speaker"] == "Ana" and b["inherited"] is True and b["is_self"] is False


def test_a_one_word_utterance_after_a_long_pause_is_marked_unsure(tmp_path):
    s, p, ana = build(tmp_path, ["I will send the report", "okay"])
    p.feed_segment(Segment(0, 2, clip(1, 16000 * 2)))
    p.current_speaker["t"] -= 60                                                          # a minute of silence since
    b = p.feed_segment(Segment(70, 70.5, clip(1, 8000)))
    assert b["speaker"] == "Unsure" and b["person_id"] is None


def test_calibration_separates_you_from_other_voices_and_sets_the_threshold(tmp_path):
    s = Store(tmp_path)
    spk = SpeakerEngine(FakeEmbedder(), s)
    me = spk.enroll("Me", [clip(1), clip(1)], "ok")
    r = evaluate(spk, me, [clip(1, 16000 * 3) for _ in range(4)], [clip(k, 16000 * 3) for k in (2, 3, 4, 5, 6)])
    assert r["verdict"] == "good" and r["impostor_max"] < r["threshold"] < r["self_min"]
    assert "works well" in r["summary"]


def test_calibration_admits_when_it_cannot_tell_voices_apart(tmp_path):
    s = Store(tmp_path)
    spk = SpeakerEngine(FakeEmbedder(), s)
    me = spk.enroll("Me", [clip(1), clip(1)], "ok")
    r = evaluate(spk, me, [clip(1, 16000 * 3), clip(2, 16000 * 3)], [clip(1, 16000 * 3), clip(2, 16000 * 3)])    # impostors sound like me
    assert r["verdict"] == "poor" and "cannot" in r["summary"].lower()


def test_whisper_does_not_invent_youtube_outros():
    class Seg:
        def __init__(s, t, p=0.0, lp=-0.3): s.text, s.no_speech_prob, s.avg_logprob = t, p, lp

    class Model:
        def __init__(s, text, lp=-0.3): s.text, s.lp = text, lp
        def transcribe(s, *a, **k): return [Seg(s.text, 0.0, s.lp)], None
    loud_noise = (np.random.default_rng(0).standard_normal(16000 * 3) * 800).astype(np.int16)
    assert WhisperEn(model_obj=Model("Thank you for watching, and I will see you in the next video")).transcribe(loud_noise).text == ""
    assert WhisperEn(model_obj=Model("Thanks for watching!")).transcribe(loud_noise).text == ""
    assert WhisperEn(model_obj=Model("Please send the report")).transcribe(loud_noise).text == "Please send the report"
    assert WhisperEn(model_obj=Model("blah", -1.8)).transcribe(loud_noise).text == ""             # a very low-confidence guess is dropped


def test_a_voice_that_passed_the_match_threshold_counts_as_you_at_the_buds_mic_scores():
    """Real session: 'I'll send the report on Friday' scored 0.71 as Me and was held back as unsure_voice because
    'is you' needed 0.80. Being matched as Me already needed the speaker threshold, so a small margin above it is enough."""
    cfg = Config()
    assert cfg.is_you(0.71) and cfg.is_you(0.74)
    assert not cfg.is_you(cfg.speaker_threshold)
    cfg.speaker_threshold = 0.8                                  # a calibrated, stricter threshold raises the bar with it
    assert not cfg.is_you(0.71) and cfg.is_you(0.9)
