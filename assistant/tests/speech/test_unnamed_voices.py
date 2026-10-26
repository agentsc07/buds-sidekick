"""Voices I couldn't name are kept for a while (RAM before) so the People page can ask about them after the conversation is over."""
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from buds_assistant.audio.capture import RingBuffer
from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.core.events import EventBus
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.core.pipeline import ConversationPipeline
from buds_assistant.audio.segmenter import Segment
from buds_assistant.speech.speaker import SpeakerEngine
from buds_assistant.core.store import Store
from buds_assistant.speech.transcribe import FakeTranscriber
from test_dashboard import _make
from test_speaker import FakeEmbedder, clip


def vec(i):
    v = np.zeros(256, dtype=np.float32); v[i] = 1.0
    return v


def test_store_keeps_lists_expires_and_wipes_unnamed_voices(tmp_path):
    s = Store(tmp_path)
    a = s.upsert_unnamed(1, "Speaker A", vec(1), np.ones(16000, dtype=np.int16), "hello there", 3.0)
    assert s.upsert_unnamed(1, "Speaker A", vec(1), np.ones(8000, dtype=np.int16), "and again", 2.0) == a      # same voice in the same conversation: one row
    rows = s.unnamed_voices()
    assert len(rows) == 1 and rows[0]["count"] == 2 and rows[0]["seconds"] == 5.0 and rows[0]["last_text"] == "and again"
    assert rows[0]["clip"].dtype == np.int16 and rows[0]["clip"].size == 24000
    s._x("UPDATE unnamed_voices SET last_seen=?", (time.time() - 9 * 86400,))
    assert s.expire_unnamed(7) == 1 and s.unnamed_voices() == []
    s.upsert_unnamed(2, "Speaker B", vec(2), np.ones(100, dtype=np.int16), "x", 1.0)
    s.wipe()
    assert s.unnamed_voices() == []


def _pipe(tmp_path, days=7, mode="listen", persist=True):
    s = Store(tmp_path)
    spk = SpeakerEngine(FakeEmbedder(), s, min_seconds=1.2)
    spk.enroll("Me", [clip(1), clip(1)], "ok")
    p = ConversationPipeline(Config(data_dir=tmp_path, keep_unnamed_days=days), s, spk, FakeTranscriber(["who is this"]), Memory(s, FakeLLM()), None, EventBus(), RingBuffer(8))
    p.conv_id = s.start_conversation(mode)
    p.mode, p.persist = mode, persist
    return s, p


def test_a_stranger_is_kept_for_review_but_never_a_known_person(tmp_path):
    s, p = _pipe(tmp_path)
    p.feed_segment(Segment(0, 2, clip(5, 32000)))
    p.feed_segment(Segment(4, 6, clip(1, 32000)))                   # Me: not an unnamed voice
    rows = s.unnamed_voices()
    assert len(rows) == 1 and rows[0]["last_text"] == "who is this" and rows[0]["clip"].size > 0


@pytest.mark.parametrize("days,mode,persist", [(0, "listen", True), (7, "listen", False), (7, "interpreter", True)])
def test_nothing_is_kept_when_off_not_saving_or_translating(tmp_path, days, mode, persist):
    s, p = _pipe(tmp_path, days, mode, persist)
    p.feed_segment(Segment(0, 2, clip(5, 32000)))
    assert s.unnamed_voices() == []


@pytest.fixture
def client(tmp_path):
    sk = _make(Config(data_dir=tmp_path, keep_unnamed_days=7), FakeLLM())
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def _earlier(client, spk=5, convo=1, text="when does the permit expire", seconds=4.0):
    e = client.sk.speaker.embed(clip(spk))
    return client.sk.store.upsert_unnamed(convo, "Speaker A", e, clip(spk, 32000), text, seconds)


def test_earlier_voices_appear_once_with_a_clip_and_when_they_were_heard(client):
    _earlier(client, 5, 1); _earlier(client, 5, 2, "second chat")                 # the same stranger in two conversations
    _earlier(client, 6, 3, "someone else")
    items = client.get("/api/v2/unnamed").json()
    stored = [i for i in items if i["label"].startswith("stored:")]
    assert len(stored) == 2 and sorted(i["utterances"] for i in stored) == [1, 2]
    assert all(i["last_seen"] and i["seconds"] > 0 for i in stored)
    assert client.get(f"/api/v2/unnamed/{stored[0]['label']}/clip").content[:4] == b"RIFF"


def test_naming_an_earlier_voice_enrols_it_and_removes_it_from_the_list(client):
    _earlier(client, 5, 1); _earlier(client, 5, 2)
    label = client.get("/api/v2/unnamed").json()[0]["label"]
    r = client.post(f"/api/v2/unnamed/{label}/name", json={"name": "Anita", "consent": "agreed"})
    assert r.status_code == 200
    pid = r.json()["person_id"]
    assert client.sk.store.person(pid)["name"] == "Anita" and client.sk.store.unnamed_voices() == []
    assert client.sk.speaker.identify(clip(5, 32000)).person_id == pid           # and she is recognised from now on


def test_an_earlier_voice_can_be_added_to_someone_you_know(client):
    ravi = client.sk.speaker.enroll("Ravi", [clip(1), clip(1)], "ok")
    _earlier(client, 5, 1)
    label = client.get("/api/v2/unnamed").json()[0]["label"]
    r = client.post(f"/api/v2/unnamed/{label}/name", json={"person_id": ravi})
    assert r.status_code == 200 and r.json()["person_id"] == ravi and len(client.sk.store.people()) == 1
    assert client.sk.store.unnamed_voices() == []


def test_old_unnamed_voices_expire_and_dismissing_deletes_now(client):
    _earlier(client, 5, 1)
    client.sk.store._x("UPDATE unnamed_voices SET last_seen=?", (time.time() - 30 * 86400,))
    assert [i for i in client.get("/api/v2/unnamed").json() if i["label"].startswith("stored:")] == []
    _earlier(client, 6, 2)
    label = client.get("/api/v2/unnamed").json()[0]["label"]
    assert client.post(f"/api/v2/unnamed/{label}/dismiss").status_code == 200
    assert client.sk.store.unnamed_voices() == []


def test_keeping_voices_is_a_setting_you_can_turn_off_and_it_clears_what_was_kept(client):
    _earlier(client, 5, 1)
    assert client.post("/api/settings", json={"keep_unnamed_days": 0}).json()["keep_unnamed_days"] == 0
    assert client.sk.store.unnamed_voices() == []
    assert client.post("/api/settings", json={"keep_unnamed_days": 400}).status_code == 400
