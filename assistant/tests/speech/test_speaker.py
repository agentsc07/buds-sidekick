import numpy as np
import pytest

from buds_assistant.speech.speaker import SherpaEmbedder, SpeakerEngine
from buds_assistant.core.store import Store
from helpers import MODEL, needs_model, needs_say, synth

SENT = ["The quarterly budget needs another review before Friday", "Please send me the report when you have a moment",
        "Let us move the meeting to Thursday afternoon instead", "I think the proposal is ready for the client now",
        "Could you check the numbers on the second slide again"]


class FakeEmbedder:
    """audio[0] encodes the speaker id: one-hot embedding plus a little deterministic noise."""
    def embed(self, a):
        v = np.zeros(256, dtype=np.float32)
        v[int(abs(a[0]) * 1000) % 8] = 1.0
        return v + 0.02 * np.random.default_rng(int(abs(a[1]) * 1e6) % 999).standard_normal(256).astype(np.float32)


def clip(spk, n=16000):
    a = np.zeros(n, dtype=np.float32)
    a[0], a[1] = spk / 1000.0 + 1e-4, np.random.rand()
    return (a * 32768).astype(np.int16)


def test_engine_logic_with_fake_embedder(tmp_path):
    s = Store(tmp_path)
    eng = SpeakerEngine(FakeEmbedder(), s)
    ravi = eng.enroll("Ravi", [clip(1), clip(1)], "verbal consent")
    m = eng.identify(clip(1))
    assert m.person_id == ravi and m.confident and m.name == "Ravi"
    u1, u2 = eng.identify(clip(5)), eng.identify(clip(5))
    assert u1.person_id is None and u1.cluster == u2.cluster == "Speaker A"       # stable provisional label
    assert eng.identify(clip(6)).cluster == "Speaker B"
    assert eng.identify(clip(1, n=2000)).too_short                                  # < 0.6 s is never identified
    pid = eng.name_cluster("Speaker A", "Anita", "met at office, agreed")
    assert eng.identify(clip(5)).person_id == pid and [c["label"] for c in eng.clusters()] == ["Speaker B"]


def test_consent_required(tmp_path):
    eng = SpeakerEngine(FakeEmbedder(), Store(tmp_path))
    with pytest.raises(ValueError):
        eng.enroll("Ravi", [clip(1)], "  ")


@needs_model
@needs_say
def test_real_voices_enrol_identify_and_reject_strangers(tmp_path):
    eng = SpeakerEngine(SherpaEmbedder(MODEL), Store(tmp_path))
    known = {"Albert": "Albert", "Samantha": "Samantha"}
    pids = {n: eng.enroll(n, [synth(v, SENT[0], tmp_path / "e.wav"), synth(v, SENT[1], tmp_path / "e.wav")], "test voice")
            for n, v in known.items()}
    correct = total = 0
    for n, v in known.items():
        for t in SENT[2:]:
            total += 1
            correct += eng.identify(synth(v, t, tmp_path / "t.wav")).person_id == pids[n]
    assert correct / total >= 0.9, (correct, total)
    stranger = [eng.identify(synth("Daniel", t, tmp_path / "s.wav")) for t in SENT[2:]]
    assert all(m.person_id is None for m in stranger)                   # unenrolled voice is NOT named
    assert len({m.cluster for m in stranger}) == 1                      # ...and gets one stable provisional label


def test_similar_voices_are_flagged_at_enrolment(tmp_path):
    s = Store(tmp_path)
    eng = SpeakerEngine(FakeEmbedder(), s)
    a = eng.enroll("Ana", [clip(1), clip(1)], "ok")
    b = eng.enroll("Ben", [clip(1), clip(1)], "ok")           # same fake "voice" as Ana
    c = eng.enroll("Cy", [clip(4), clip(4)], "ok")
    assert [x["name"] for x in eng.similar_voices(b, 0.6)] == ["Ana"] and eng.similar_voices(c, 0.6) == []
