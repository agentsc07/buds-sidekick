import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from buds_assistant.intelligence.autopilot import Hint
from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.intelligence.llm import FakeLLM
from test_dashboard import _make


@pytest.fixture
def sk(tmp_path):
    k = _make(Config(data_dir=tmp_path, hint_ttl=0.5), FakeLLM())
    k.personal.clear_sample()                                  # these tests want an empty calendar
    return k


@pytest.fixture
def client(sk):
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def spoken(sk):
    return [x["text"] for x in sk.output.log if x["kind"] == "speak"]


def test_fresh_install_has_clearly_flagged_sample_data(tmp_path):
    k = _make(Config(data_dir=tmp_path), FakeLLM())
    assert k.personal.todos() and k.personal.next_event(time.time())
    assert all(t["sample"] for t in k.personal.todos())
    assert k.policy.personal is k.personal and k.brain.personal is k.personal


async def test_a_meeting_is_announced_in_autopilot(sk):
    sk.modes.mode = "autopilot"; sk.policy.enabled = True
    sk.personal.add_event("Standup", time.time() + 9 * 60, None, ["Ravi"])
    await sk._agenda_tick(time.time())
    assert any(t.startswith("Your Standup starts in 10 minutes") for t in spoken(sk))
    n = len(spoken(sk))
    await sk._agenda_tick(time.time())
    assert len(spoken(sk)) == n                                # once


async def test_meetings_are_not_announced_outside_autopilot(sk):
    sk.personal.add_event("Standup", time.time() + 9 * 60, None)
    await sk._agenda_tick(time.time())
    assert spoken(sk) == [] and sk.personal.upcoming_to_announce(time.time())     # still pending: it was not consumed


async def test_a_reminder_plays_even_in_standby_and_only_once(sk):
    rid = sk.personal.add_reminder("call mum", time.time() - 5)
    await sk._agenda_tick(time.time())
    assert any("reminder: call mum" in t.lower() for t in spoken(sk)) and sk.personal.reminders() == []
    n = len(spoken(sk))
    await sk._agenda_tick(time.time())
    assert len(spoken(sk)) == n


async def test_nothing_is_announced_in_private(sk):
    sk.modes.mode = "private"
    sk.personal.add_reminder("call mum", time.time() - 5)
    await sk._agenda_tick(time.time())
    assert spoken(sk) == [] and len(sk.personal.reminders()) == 1


async def test_undoing_a_promise_also_removes_its_todo(sk):
    me = sk.store.add_person("Me")
    sk.modes.mode = "autopilot"; sk.policy.enabled = True
    h = sk.policy.on_segment({"person_id": me, "speaker": "Me", "text": "I'll send the deck on Friday", "is_self": True, "seg_id": None}, time.time())
    assert sk.personal.todos()
    sk.last_hint = h
    await sk._handlers()["undo_commitment"]()
    assert sk.personal.todos() == []


def test_my_day_api_lists_and_edits(client):
    pe = client.sk.personal
    r = client.post("/api/v2/me/todos", json={"text": "book the room", "when": "tomorrow"}).json()
    assert r["ok"]
    r = client.post("/api/v2/me/reminders", json={"text": "call mum", "when": "tomorrow at 9"})
    assert r.status_code == 200
    assert client.post("/api/v2/me/reminders", json={"text": "call mum", "when": "whenever"}).status_code == 400
    ev = client.post("/api/v2/me/events", json={"title": "Dentist", "when": "tomorrow at 3 pm", "people": ["Ravi"]}).json()
    day = client.get("/api/v2/me").json()
    assert [t["text"] for t in day["todos"]] == ["book the room"] and day["reminders"][0]["text"] == "call mum"
    assert day["events"][0]["title"] == "Dentist" and day["events"][0]["when_label"] == "tomorrow at 3 pm" and day["sample"] is False
    tid = day["todos"][0]["id"]
    client.post(f"/api/v2/me/todos/{tid}/done")
    assert client.get("/api/v2/me").json()["todos"] == []
    client.post(f"/api/v2/me/todos/{tid}/reopen")
    assert len(client.get("/api/v2/me").json()["todos"]) == 1
    client.delete(f"/api/v2/me/events/{ev['id']}")
    assert client.get("/api/v2/me").json()["events"] == []


def test_sample_data_can_be_loaded_and_cleared_from_the_dashboard(client):
    assert client.post("/api/v2/me/sample", json={"on": True}).status_code == 200
    day = client.get("/api/v2/me").json()
    assert day["sample"] is True and day["events"] and day["todos"]
    client.post("/api/v2/me/sample", json={"on": False})
    day = client.get("/api/v2/me").json()
    assert day["sample"] is False and day["events"] == []


def test_autopilot_settings_know_the_new_hint_types(client):
    cats = client.get("/api/v2/autopilot").json()["categories"]
    assert {"calendar", "meeting", "reminder"} <= set(cats)
