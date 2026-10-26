"""Voice recognition v3: the same person on two microphones, score normalisation, turn pooling, safe adaptation (docs/specs/spec-v3-voice.md)."""
import numpy as np
import pytest

from buds_assistant.speech.speaker import SpeakerEngine, snorm
from buds_assistant.core.store import Store


class TwoChannelEmbedder:
    """audio[0] = speaker, audio[2] = channel. Same speaker on another channel is only ~0.2 similar (as measured on the real samples)."""
    def embed(self, a):
        spk, chan = int(round(abs(a[0]) * 1000)), int(round(abs(a[2]) * 1000))
        base = np.zeros(256, dtype=np.float32); base[spk % 16] = 1.0
        mix = np.random.default_rng(spk * 31 + chan * 7919).standard_normal(256).astype(np.float32)
        mix /= np.linalg.norm(mix)
        noise = 0.02 * np.random.default_rng(int(abs(a[1]) * 1e6) % 9973).standard_normal(256).astype(np.float32)
        return 0.45 * base + 0.89 * mix + noise


def clip(spk, chan=0, n=16000):
    a = np.zeros(n, dtype=np.float32)
    a[0], a[1], a[2] = spk / 1000.0 + 1e-4, np.random.rand(), chan / 1000.0 + 1e-4
    return (a * 32768).astype(np.int16)


@pytest.fixture
def eng(tmp_path):
    e = SpeakerEngine(TwoChannelEmbedder(), Store(tmp_path), threshold=0.85, min_seconds=0.6)
    return e


def test_one_person_enrolled_on_two_microphones_is_recognised_on_both(eng):
    me = eng.enroll("Me", [clip(1, 0) for _ in range(3)], "own voice", source="laptop")
    eng.add_clips(me, [clip(1, 1) for _ in range(3)], source="enrol:buds")
    for chan in (0, 1):
        m = eng.identify(clip(1, chan))
        assert m.person_id == me and m.confident, (chan, m.score)
    assert not eng.identify(clip(2, 0)).confident and not eng.identify(clip(2, 1)).confident


def test_a_microphone_never_enrolled_is_the_honest_gap(eng):
    me = eng.enroll("Me", [clip(1, 0) for _ in range(3)], "own voice", source="laptop")
    assert not eng.identify(clip(1, 5)).confident                  # a third room/mic the engine has never heard
    eng.add_clips(me, [clip(1, 5) for _ in range(3)], source="enrol:other")
    assert eng.identify(clip(1, 5)).person_id == me


def test_snorm_discounts_a_probe_that_is_similar_to_everybody():
    rng = np.random.default_rng(0)
    assert snorm(0.7, np.full(20, 0.65) + 0.02 * rng.standard_normal(20), np.full(20, 0.65) + 0.02 * rng.standard_normal(20)) < 2.0
    assert snorm(0.7, np.full(20, 0.10) + 0.05 * rng.standard_normal(20), np.full(20, 0.10) + 0.05 * rng.standard_normal(20)) > 5.0


def test_real_enrolment_groups_knn_beats_mean_centroid():
    """Uses the real stored embeddings when this machine has them: the user's two recording groups."""
    import sqlite3
    from pathlib import Path
    db = Path(__file__).resolve().parents[2] / "data" / "sidekick.db"
    if not db.exists():
        pytest.skip("no real data")
    rows = sqlite3.connect(db).execute("SELECT embedding FROM voice_samples WHERE person_id=1").fetchall()
    E = [np.frombuffer(r[0], dtype=np.float32) for r in rows]
    E = np.array([e / np.linalg.norm(e) for e in E if e.size == 256])
    if len(E) < 6:
        pytest.skip("not enough samples")
    old, new = [], []
    for i in range(len(E)):                                      # leave one sample out, score it against the rest
        rest = np.delete(E, i, 0)
        c = rest.mean(axis=0); c /= np.linalg.norm(c)
        old.append(float(E[i] @ c)); new.append(float(np.sort(rest @ E[i])[-3:].mean()))
    assert min(new) >= min(old) + 0.05                           # the worst-matched own sample improves (0.71 -> 0.80 on the real data)


class VecEmbedder:
    """The audio IS the embedding (first 256 samples), so a test controls the geometry exactly."""
    def embed(self, a):
        return np.asarray(a[:256], dtype=np.float32)


def unit(*pairs):
    v = np.zeros(256, dtype=np.float32)
    for i, w in pairs:
        v[i] += w
    return v / np.linalg.norm(v)


def vclip(v, n=16000):
    a = np.zeros(n, dtype=np.float32); a[:256] = v
    return a


@pytest.fixture
def veng(tmp_path):
    e = SpeakerEngine(VecEmbedder(), Store(tmp_path), threshold=0.62, min_seconds=0.6)
    e.me = e.enroll("Me", [vclip(unit((0, 1))) for _ in range(3)], "own voice")
    return e


def test_a_weak_segment_joins_the_turn_it_continues(veng):
    probe = vclip(unit((0, 0.6), (1, 0.8)))
    prev = {"emb": unit((0, 0.9), (2, 0.436)), "seconds": 2.0, "gap": 0.4, "person_id": veng.me}
    assert not veng.identify(probe).confident                         # alone: below the threshold
    m = veng.identify(probe, prev=prev)
    assert m.confident and m.person_id == veng.me and m.pooled


def test_pooling_never_rescues_a_stranger_or_a_long_pause(veng):
    stranger = vclip(unit((5, 1)))
    prev = {"emb": unit((0, 0.9), (2, 0.436)), "seconds": 2.0, "gap": 0.4, "person_id": veng.me}
    assert not veng.identify(stranger, prev=prev).confident           # unrelated voice: no pooling at all
    weak = vclip(unit((0, 0.6), (1, 0.8)))
    assert not veng.identify(weak, prev={**prev, "gap": 3.0}).confident   # a pause: probably a new turn


def test_adaptation_is_gated_capped_and_reversible(veng):
    good, seconds = unit((0, 0.95), (3, 0.31)), 3.0
    assert veng.adapt(veng.me, good, "buds", seconds=3.0, raw=0.9)
    assert not veng.adapt(veng.me, good, "buds", seconds=1.0, raw=0.9)         # too short to learn from
    assert not veng.adapt(veng.me, good, "buds", seconds=3.0, raw=0.64)        # not sure enough it is you
    for _ in range(60):
        veng.adapt(veng.me, good, "buds", seconds=3.0, raw=0.9)
    assert sum(1 for s in veng.store.voice_samples(veng.me) if s["source"] == "adapt:buds") == 40
    assert veng.sources(veng.me)["buds"] == 40
    removed = veng.forget_adapted(veng.me)
    assert removed == 40 and veng.sources(veng.me) == {"enrol": 3}


def test_voice_health_reports_each_microphone_and_the_nearest_stranger(veng):
    veng.add_clips(veng.me, [vclip(unit((0, 0.8), (1, 0.6))) for _ in range(3)], source="enrol-ear")
    for i in range(12):                                                         # other voices heard
        veng.cohort.append(unit((10 + i, 1)))
    h = veng.health(veng.me)
    assert set(h["sources"]) == {"enrol", "buds"} and h["sources"]["buds"]["samples"] == 3
    assert 0 <= h["nearest_stranger"] < 0.3 and h["verdict"] in ("good", "fair", "needs_more")
    assert h["advice"]


def test_pipeline_learns_from_clear_turns_of_the_user_only(tmp_path):
    from buds_assistant.audio.capture import RingBuffer
    from buds_assistant.core.config import Config
    from buds_assistant.core.events import EventBus
    from buds_assistant.intelligence.llm import FakeLLM
    from buds_assistant.intelligence.memory import Memory
    from buds_assistant.core.pipeline import ConversationPipeline
    from buds_assistant.audio.segmenter import Segment
    from buds_assistant.speech.transcribe import FakeTranscriber
    from test_speaker import FakeEmbedder, clip as sclip
    s = Store(tmp_path)
    spk = SpeakerEngine(FakeEmbedder(), s, min_seconds=1.2)
    me, bob = spk.enroll("Me", [sclip(1), sclip(1)], "ok"), spk.enroll("Bob", [sclip(2), sclip(2)], "ok")
    p = ConversationPipeline(Config(data_dir=tmp_path), s, spk, FakeTranscriber(["one", "two"]), Memory(s, FakeLLM()), None, EventBus(), RingBuffer(8))
    p.conv_id = s.start_conversation("listen")
    p.source_key = "buds"
    p.feed_segment(Segment(0, 3, sclip(1, 16000 * 3)))
    p.feed_segment(Segment(5, 8, sclip(2, 16000 * 3)))
    assert spk.sources(me).get("buds") == 1 and spk.sources(bob) == {"enrol": 2}      # learned from you, never from Bob


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    from buds_assistant.core.config import Config
    from buds_assistant.dashboard.server import create_app
    from buds_assistant.intelligence.llm import FakeLLM
    from test_dashboard import _make
    sk = _make(Config(data_dir=tmp_path), FakeLLM())
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def test_a_new_recording_can_be_added_to_an_existing_person_with_its_microphone(client):
    from test_dashboard import wav_b64
    pid = client.sk.speaker.enroll("Ravi", [sclip_(1), sclip_(1)], "ok")
    before = len(client.sk.store.people())
    r = client.post("/api/v2/voices/add", json={"person_id": pid, "source": "buds", "wav_base64": wav_b64(1, seconds=6)})
    assert r.status_code == 200 and r.json()["added"] >= 1 and len(client.sk.store.people()) == before
    assert client.sk.speaker.sources(pid).get("buds", 0) >= 1
    assert client.post("/api/v2/voices/add", json={"person_id": 999, "source": "buds", "wav_base64": wav_b64(1, seconds=6)}).status_code == 404
    h = client.get(f"/api/v2/voices/{pid}/health").json()
    assert "buds" in h["sources"] and h["verdict"] in ("good", "fair", "needs_more")


def test_learned_voice_can_be_rolled_back_from_the_api(client):
    pid = client.sk.speaker.enroll("Me", [sclip_(1), sclip_(1)], "ok")
    client.sk.store.add_voice_sample(pid, np.ones(256, dtype=np.float32), "adapt:buds")
    client.sk.speaker.reload()
    assert client.post(f"/api/v2/voices/{pid}/forget-learning").json() == {"removed": 1}


def sclip_(spk):
    from test_speaker import clip as c
    return c(spk)


def test_an_unnamed_voice_has_a_short_clip_in_memory_that_can_be_played(client):
    spk = client.sk.speaker
    spk.identify(sclip_(5, ), )
    label = spk.clusters()[0]["label"]
    r = client.get(f"/api/v2/unnamed/{label}/clip")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
    assert client.get("/api/v2/unnamed/Speaker Z/clip").status_code == 404
    spk.reset_session()
    assert client.get(f"/api/v2/unnamed/{label}/clip").status_code == 404           # gone with the session: never written to disk


def test_naming_an_unnamed_voice_as_an_existing_person_adds_to_them(client):
    spk = client.sk.speaker
    ravi = spk.enroll("Ravi", [sclip_(1), sclip_(1)], "ok")
    spk.identify(sclip_(5))
    label = spk.clusters()[0]["label"]
    client.sk.pipeline.window.append({"person_id": None, "cluster": label, "text": "hi", "t0": 0, "t1": 1, "speaker": label, "seg_id": None, "experimental": False, "conf": 0.5, "lang": "en"})
    r = client.post(f"/api/v2/unnamed/{label}/name", json={"person_id": ravi})
    assert r.status_code == 200 and r.json()["person_id"] == ravi and len(client.sk.store.people()) == 1
    assert client.post(f"/api/v2/unnamed/{label}/name", json={"person_id": 12345}).status_code in (400, 404)


def test_a_new_voice_can_be_recorded_and_heard_back(client):
    from test_dashboard import wav_b64
    r = client.post("/api/v2/voices/new", json={"name": "Anita", "consent": "agreed", "source": "laptop", "wav_base64": wav_b64(3, seconds=6)})
    assert r.status_code == 200 and client.sk.store.person_by_name("Anita")["id"] == r.json()["person_id"]
    assert client.sk.speaker.sources(r.json()["person_id"]).get("laptop", 0) >= 1
    clip = client.get("/api/v2/voices/last-clip")
    assert clip.status_code == 200 and clip.content[:4] == b"RIFF"
    again = client.post("/api/v2/voices/new", json={"name": "anita", "consent": "agreed", "source": "buds", "wav_base64": wav_b64(3, seconds=6)})
    assert again.status_code == 400 and "existing" in again.json()["detail"].lower()
    assert client.post("/api/v2/voices/new", json={"name": "Bo", "consent": "", "wav_base64": wav_b64(3, seconds=6)}).status_code == 400


class Dim8Embedder(VecEmbedder):
    dim = 8
    def embed(self, a):
        return np.asarray(a[:8], dtype=np.float32)


def test_samples_from_another_model_are_kept_but_not_used_and_the_person_needs_a_new_recording(tmp_path):
    s = Store(tmp_path)
    old = SpeakerEngine(VecEmbedder(), s, threshold=0.62)
    me = old.enroll("Me", [vclip(unit((0, 1))) for _ in range(3)], "own voice")          # 256-dim samples from the previous model
    new = SpeakerEngine(Dim8Embedder(), s, threshold=0.62)
    assert not new.ready_for(me) and new.identify(vclip(unit((0, 1)))).person_id is None
    assert len(s.voice_samples(me)) == 3                                                 # nothing was deleted: switching back works
    new.add_clips(me, [vclip(unit((0, 1)))[:16000] for _ in range(2)], source="enrol:laptop")
    assert new.ready_for(me)


def test_a_person_who_needs_a_new_recording_can_record_again_from_setup(client):
    from test_dashboard import wav_b64
    sk = client.sk
    sk.speaker.dim = 1                                                                   # pretend the model changed: nothing matches
    pid = sk.store.add_person("Me", "own voice")
    sk.store.add_voice_sample(pid, np.ones(256, dtype=np.float32), "enrol")
    sk.speaker.reload()
    assert client.get("/api/v2/setup/status").json()["me_ready"] is False
    sk.speaker.dim = None
    sk.speaker.reload()
    assert client.get("/api/v2/setup/status").json()["me_ready"] is True


def noisy(rng, w0, w1, noise=0.7):
    """One utterance of a voice that is only moderately close to the enrolled one (another microphone), plus its own noise."""
    n = rng.standard_normal(256).astype(np.float32); n[:3] = 0
    v = np.zeros(256, dtype=np.float32); v[0], v[1] = w0, w1
    v = v + noise * n / np.linalg.norm(n)
    return vclip(v / np.linalg.norm(v))


def test_a_cluster_of_the_same_voice_is_labelled_as_the_person_once_enough_of_it_is_heard(tmp_path):
    """Real session: the user, on a different microphone, scored 0.51-0.59 per segment (< threshold) and became Speaker A, B, C, D.
    Diarisation systems cluster first and label the whole cluster from its pooled voice: more speech, less noise."""
    rng = np.random.default_rng(3)
    eng = SpeakerEngine(VecEmbedder(), Store(tmp_path), threshold=0.62, min_seconds=0.6, cluster_threshold=0.4)
    me = eng.enroll("Me", [vclip(unit((0, 1))) for _ in range(3)], "own voice")
    got = [eng.identify(noisy(rng, 0.5, 0.5)) for _ in range(8)]
    assert got[0].person_id is None                                          # one noisy segment alone is not enough
    assert any(m.person_id == me and m.promoted for m in got)                # the cluster is recognised as Me once pooled
    assert got[-1].person_id == me and got[-1].confident                     # and stays Me
    assert eng.identify(noisy(rng, 0.0, 1.0)).person_id is None              # someone unrelated is not swept in


def test_unrelated_strangers_never_get_promoted_to_the_user(tmp_path):
    rng = np.random.default_rng(4)
    eng = SpeakerEngine(VecEmbedder(), Store(tmp_path), threshold=0.62, min_seconds=0.6, cluster_threshold=0.4)
    eng.enroll("Me", [vclip(unit((0, 1))) for _ in range(3)], "own voice")
    got = [eng.identify(noisy(rng, 0.1, 0.9, noise=0.4)) for _ in range(12)]
    assert all(m.person_id is None for m in got)
