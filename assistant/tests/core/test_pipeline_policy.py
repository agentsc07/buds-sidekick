"""Per-person keep policy: none = not stored, transcript = text only, audio = text + wav (deleted on forget)."""
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
from buds_assistant.speech.transcribe import FakeTranscriber
from test_speaker import FakeEmbedder, clip


def build(tmp_path):
    cfg = Config(data_dir=tmp_path)
    s = Store(tmp_path)
    spk = SpeakerEngine(FakeEmbedder(), s)
    ids = {n: spk.enroll(n, [clip(i + 1), clip(i + 1)], "ok") for i, n in enumerate(["Ana", "Ben", "Cy"])}
    pipe = ConversationPipeline(cfg, s, spk, FakeTranscriber(["hello from ana", "hello from ben", "hello from cy"]),
                                Memory(s, FakeLLM()), None, EventBus(), RingBuffer(8))
    pipe.conv_id = s.start_conversation("conversation")
    return s, pipe, ids


def test_policies_none_transcript_audio_and_forget_removes_audio_file(tmp_path):
    s, pipe, ids = build(tmp_path)
    s.set_policy(ids["Ana"], "none")
    s.set_policy(ids["Ben"], "transcript")
    s.set_policy(ids["Cy"], "audio")
    for spk_no in (1, 2, 3):
        pipe.feed_segment(Segment(0, 1, clip(spk_no, 16000 * 2)))
    stored = {x["speaker"]: x for x in s.segments()}
    assert set(stored) == {"Ben", "Cy"}                                   # "none": not stored at all
    assert stored["Ben"]["audio_ref"] is None and stored["Cy"]["audio_ref"]
    wav = stored["Cy"]["audio_ref"]
    assert __import__("pathlib").Path(wav).exists()
    assert len(pipe.window) == 3                                           # all three still shown live (RAM)
    s.forget(ids["Cy"])
    assert not __import__("pathlib").Path(wav).exists()                    # forgetting deletes the recording too
