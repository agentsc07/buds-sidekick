"""Renaming people, and the assistant's own voice (it must never be a person, and recaps must know which lines are the assistant's)."""
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.intelligence.llm import FakeLLM
from test_dashboard import _make
from test_speaker import clip


@pytest.fixture
def client(tmp_path):
    sk = _make(Config(data_dir=tmp_path), FakeLLM())
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def test_a_person_can_be_renamed_and_the_conversation_shows_the_new_name(client):
    ravi = client.sk.speaker.enroll("Ravi", [clip(2), clip(2)], "ok")
    client.sk.pipeline.window.append({"speaker": "Ravi", "person_id": ravi, "cluster": None, "text": "hi", "t0": 0, "t1": 1})
    r = client.post(f"/api/v2/people/{ravi}/rename", json={"name": "  Ravindra "})
    assert r.status_code == 200 and r.json()["name"] == "Ravindra"
    assert client.sk.store.person(ravi)["name"] == "Ravindra"
    assert client.sk.pipeline.window[-1]["speaker"] == "Ravindra"
    assert any(e["type"] == "renamed" for e in client.sk.events.recent(20, {"renamed"}))


def test_rename_refuses_empty_taken_and_your_own_entry(client):
    me = client.sk.speaker.enroll("Me", [clip(1), clip(1)], "ok")
    ravi = client.sk.speaker.enroll("Ravi", [clip(2), clip(2)], "ok")
    assert client.post(f"/api/v2/people/{ravi}/rename", json={"name": " "}).status_code == 400
    assert "already" in client.post(f"/api/v2/people/{ravi}/rename", json={"name": "me"}).json()["detail"].lower()
    assert client.post(f"/api/v2/people/{ravi}/rename", json={"name": "ravi"}).status_code == 200          # same person, different capitals
    assert client.post(f"/api/v2/people/{me}/rename", json={"name": "Sai"}).status_code == 400            # the app identifies you by this entry
    assert client.post("/api/v2/people/999/rename", json={"name": "X"}).status_code == 404


async def test_the_arbiter_knows_when_its_own_voice_was_playing():
    import asyncio
    from buds_assistant.audio.output import FakePlayer, FakeTTS, OutputArbiter
    out = OutputArbiter(FakeTTS(), {"ear": FakePlayer(hold=0.3), "remote": FakePlayer()})
    t = asyncio.create_task(out.say("hello there", "en", "answer"))
    await asyncio.sleep(0.15)
    now = time.time()
    assert out.overlap_fraction(now - 0.1, now + 0.05) > 0.9                  # while it is talking
    await t
    end = time.time()
    assert out.overlap_fraction(end + 0.8, end + 1.5) == 0.0                  # long after
    assert out.overlap_fraction(end - 0.25, end - 0.1) > 0.9                  # a moment that was inside the playback
    assert 0.2 < out.overlap_fraction(end - 0.6, end + 0.8) < 0.9             # partly


def test_a_line_that_is_mostly_the_assistants_own_voice_never_enters_the_conversation(tmp_path):
    from buds_assistant.audio.capture import RingBuffer
    from buds_assistant.core.events import EventBus
    from buds_assistant.intelligence.memory import Memory
    from buds_assistant.core.pipeline import ConversationPipeline
    from buds_assistant.audio.segmenter import Segment
    from buds_assistant.speech.speaker import SpeakerEngine
    from buds_assistant.core.store import Store
    from buds_assistant.speech.transcribe import FakeTranscriber
    from test_speaker import FakeEmbedder
    s = Store(tmp_path)
    p = ConversationPipeline(Config(data_dir=tmp_path), s, SpeakerEngine(FakeEmbedder(), s, min_seconds=1.2), FakeTranscriber(["Your calendar is clear."]),
                             Memory(s, FakeLLM()), None, EventBus(), RingBuffer(8))
    p.conv_id = s.start_conversation("listen")
    p.own_voice = lambda a, b: 0.9
    assert p.feed_segment(Segment(0, 2, clip(5, 32000))) is None and p.window == []
    assert any(e["type"] == "own_voice_dropped" for e in p.events.recent(20, {"own_voice_dropped"}))
    p.own_voice = lambda a, b: 0.1                                                # the user talking over a short part of it still counts
    assert p.feed_segment(Segment(5, 7, clip(5, 32000)))["text"] == "Your calendar is clear."


def test_the_assistants_own_voice_is_a_built_in_profile_not_a_person(client):
    sk = client.sk
    pid = sk.ensure_assistant_voice()
    assert sk.store.person(pid)["kind"] == "assistant" and sk.speaker.ready_for(pid)
    assert sk.ensure_assistant_voice() == pid and len([p for p in sk.store.people() if p["kind"] == "assistant"]) == 1
    names = [p["name"] for p in client.get("/api/people").json()]
    assert all("Sidekick" not in n for n in names)                                    # not listed under People
    assert pid in sk.speaker.assistant_ids


def test_a_voice_that_matches_the_assistants_profile_is_dropped_not_stored_as_someone(client):
    from buds_assistant.audio.segmenter import Segment
    sk = client.sk
    sk.speaker.threshold = 0.3
    pid = sk.ensure_assistant_voice()
    audio, rate = sk.output.tts.render("Your calendar is clear today.", "en")            # the assistant says one of its usual lines
    x = audio.astype(np.float32)
    x = np.interp(np.linspace(0, x.size - 1, int(x.size * 16000 / rate)), np.arange(x.size), x).astype(np.int16)
    x = np.concatenate([x, np.zeros(max(0, 24000 - x.size), dtype=np.int16)])
    sk.pipeline.conv_id = sk.store.start_conversation("listen")
    e = sk.pipeline.feed_segment(Segment(0, x.size / 16000, x))
    assert e is None and sk.pipeline.window == []
    assert any(ev["data"].get("reason") == "voice" for ev in sk.events.recent(50, {"own_voice_dropped"}))


def test_a_person_you_saved_by_mistake_can_be_marked_as_the_assistant_and_loses_its_transcripts(client):
    sk = client.sk
    ai = sk.speaker.enroll("AI voice", [clip(7), clip(7)], "ok")
    cid = sk.store.start_conversation("listen")
    sk.store.add_segment(cid, 0, 1, ai, None, 0.9, "Your calendar is clear.", "en", None)
    r = client.post(f"/api/v2/people/{ai}/make-assistant")
    assert r.status_code == 200
    assert sk.store.person(ai)["kind"] == "assistant" and sk.store.segments(person_id=ai) == []
    assert "AI voice" not in [p["name"] for p in client.get("/api/people").json()]
    assert ai in sk.speaker.assistant_ids and client.post("/api/v2/people/999/make-assistant").status_code == 404


def test_what_the_assistant_said_is_in_the_recap_context_but_labelled_as_the_assistant(client):
    sk = client.sk
    sk.pipeline.window.append({"speaker": "Ravi", "person_id": 2, "cluster": None, "text": "Can you send the report?", "t0": time.time() - 9, "t1": time.time() - 8})
    sk.pipeline.note_assistant("Your calendar is clear today.")
    assert sk.pipeline.window[-1]["assistant"] is True and sk.pipeline.window[-1]["speaker"] == "Sidekick"
    assert all(not e.get("assistant") for e in client.get("/api/live").json())              # not shown as a transcript line
    assert sk.ctx()["last_text"] == "Can you send the report?"                                # "translate that" means what a person said
    r = sk.brain.respond("catch me up", sk.ctx())
    sk.llm.calls.clear()
    sk.llm.replies = ["Ravi asked for the report."]
    sk.brain.respond("catch me up", sk.ctx())
    prompt = " ".join(m["content"] for m in sk.llm.calls[-1]["messages"])
    assert "Sidekick: Your calendar is clear today." in prompt
    assert "Sidekick is you" in prompt and "not another person" in prompt


def test_fact_extraction_tells_the_model_who_the_user_is(client):
    sk = client.sk
    me = sk.speaker.enroll("Me", [clip(1), clip(1)], "ok")
    cid = sk.store.start_conversation("listen")
    sk.store.add_segment(cid, 0, 1, me, None, 0.9, "I will send the report on Friday", "en", None)
    sk.llm.calls.clear(); sk.llm.replies = ['{"facts": []}']
    sk.memory.extract_facts(cid)
    prompt = " ".join(m["content"] for m in sk.llm.calls[-1]["messages"])
    assert "'Me' is the user" in prompt


def test_a_saved_person_who_sounds_like_the_assistant_is_flagged(client):
    sk = client.sk
    aid = sk.ensure_assistant_voice()
    sample = sk.store.voice_samples(aid)[0]["embedding"]
    mistaken = sk.store.add_person("SideKick", "ok")
    for _ in range(3):
        sk.store.add_voice_sample(mistaken, sample, "enrol")                          # the assistant's voice, saved as a person
    human = sk.store.add_person("Ravi", "ok")
    far = np.zeros(256, dtype=np.float32); far[200] = 1.0                              # nothing like the assistant
    for _ in range(3):
        sk.store.add_voice_sample(human, far, "enrol")
    sk.speaker.reload()
    assert client.get(f"/api/v2/people/{mistaken}").json()["assistant_like"] is True
    assert client.get(f"/api/v2/people/{human}").json()["assistant_like"] is False
