import base64
import io
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.audio.output import FakePlayer
from buds_assistant.audio.segmenter import Segment
from buds_assistant.sidekick import Sidekick
from buds_assistant.speech.speaker import SpeakerEngine
from buds_assistant.speech.transcribe import FakeTranscriber
from test_speaker import FakeEmbedder, clip
from pathlib import Path

GEST = Path(__file__).resolve().parents[2] / "buds_assistant" / "config" / "sidekick_gestures.yaml"
TE = "రేపు కలుద్దాం"


def wav_b64(spk, seconds=3):
    a = np.concatenate([clip(spk) for _ in range(seconds)])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(a.tobytes())
    return base64.b64encode(buf.getvalue()).decode()


def _make(cfg, llm):
    """Sidekick with fakes for the heavy parts; the speaker engine needs the Sidekick's own store."""
    import buds_assistant.sidekick as sm
    orig = sm.Sidekick._make_speaker
    sm.Sidekick._make_speaker = lambda self: SpeakerEngine(FakeEmbedder(), self.store)
    try:
        return Sidekick(cfg, GEST, simulate=True, silent=True, llm=llm,
                        transcriber=FakeTranscriber(["I will send the report by Friday"]),
                        player_factory=lambda hint: FakePlayer())
    finally:
        sm.Sidekick._make_speaker = orig


@pytest.fixture
def client(tmp_path):
    k = _make(Config(data_dir=tmp_path), FakeLLM())
    with TestClient(create_app(k), base_url="http://127.0.0.1:8770") as c:
        c.sk = k
        yield c


def test_state_has_both_gesture_profiles_and_static_ui(client):
    s = client.get("/api/state").json()
    assert s["mode"] == "standby" and s["simulate"] and set(s["profiles"]) == {"ear", "remote"}
    assert any(g["action"] == "autopilot_toggle" for g in s["profiles"]["remote"])
    assert "Buds Sidekick" in client.get("/dev/").text and client.get("/dev/app.js").status_code == 200


def test_placement_follows_wear_state_and_changes_route(client):
    assert client.post("/api/wear", json={"left": False, "right": False}).json()["placement"] == "remote"
    assert client.get("/api/state").json()["route"] == "remote"
    assert client.post("/api/wear", json={"left": True, "right": False}).json()["placement"] == "ear"
    assert client.post("/api/placement", json={"placement": "bogus"}).status_code == 400


def test_mode_changes_and_private_wipes_buffer(client):
    sk = client.sk
    client.post("/api/mode", json={"mode": "private"})
    assert client.get("/api/state").json()["mode"] == "private" and sk.ring.seconds == 0
    assert client.post("/api/mode", json={"mode": "nonsense"}).status_code == 400


def test_enrol_requires_consent_and_enough_audio_then_forget_removes_all(client):
    assert client.post("/api/people/enroll", json={"name": "Ravi", "consent": "", "wav_base64": wav_b64(1)}).status_code == 400
    short = client.post("/api/people/enroll", json={"name": "Ravi", "consent": "ok", "wav_base64": wav_b64(1, 1)})
    assert short.status_code == 400
    r = client.post("/api/people/enroll", json={"name": "Ravi", "consent": "verbal consent", "wav_base64": wav_b64(1)})
    assert r.status_code == 200
    pid = r.json()["id"]
    sk = client.sk
    cid = sk.store.start_conversation("conversation")
    sk.store.add_segment(cid, 1, 2, pid, None, 0.9, "the secret budget figure")
    assert client.get("/api/memory/search", params={"q": "secret budget"}).json()
    counts = client.post(f"/api/people/{pid}/forget").json()
    assert counts["segments"] == 1 and counts["people"] == 1
    assert client.get("/api/memory/search", params={"q": "secret budget"}).json() == []
    assert client.get("/api/people").json() == []
    assert any(a["kind"] == "forget" for a in client.get("/api/audit").json())


def test_unknown_voice_is_named_from_the_dashboard_and_persisted(client):
    sk = client.sk
    cid = sk.store.start_conversation("conversation")
    sk.pipeline.conv_id = cid
    sk.pipeline.feed_segment(Segment(0, 2, clip(5, 32000)))
    assert sk.pipeline.window[0]["cluster"] == "Speaker A" and sk.store.segments() == []      # not stored while unknown
    r = client.post("/api/clusters/Speaker A/name", json={"name": "Dev", "consent": "agreed"})
    assert r.status_code == 200
    assert [s["speaker"] for s in sk.store.segments()] == ["Dev"]
    assert client.post("/api/clusters/Speaker Z/name", json={"name": "X", "consent": "y"}).status_code == 400
    assert client.post("/api/clusters/Speaker A/name", json={"name": "X", "consent": ""}).status_code == 400


def test_ask_translate_settings_hints(client):
    r = client.post("/api/ask", json={"text": "what is 6 times 7"}).json()
    assert r["text"] == "6 times 7 is 42." and r["intent"] == "math"
    assert client.post("/api/ask", json={"text": " "}).status_code == 400
    client.sk.llm.replies = [TE]
    t = client.post("/api/translate", json={"text": "see you tomorrow", "dst": "te"}).json()
    assert t["ok"] and t["text"] == TE
    assert client.post("/api/translate", json={"text": ""}).json()["ok"] is False
    s = client.post("/api/settings", json={"ring_seconds": 500, "hints_per_hour": 5}).json()
    assert s["ring_seconds"] == 60 and client.sk.ring.capacity == 60 * 16000 and s["hints_per_hour"] == 5
    assert client.post("/api/settings", json={"evil": 1}).status_code == 400
    hid = client.sk.store.log_hint("identity", "Ravi.", None, True)
    for _ in range(3):
        assert client.post(f"/api/hints/{hid}/feedback", json={"useful": False}).status_code == 200
    assert client.sk.policy.rate_factor == 2.0


def test_replay_endpoint_and_gesture_dispatch(client):
    sk = client.sk
    sk.ring.push((np.arange(16000 * 4) % 50).astype(np.int16))
    assert client.post("/api/replay").json()["buffered_seconds"] == 4.0
    client.post("/api/gesture", json={"token": "R:hold_start"})                  # ear profile: conversation toggle
    assert client.get("/api/state").json()["mode"] == "listen"
    assert client.post("/api/gesture", json={"token": "nope"}).status_code == 400


def test_ui_state_endpoint_and_ws_snapshot_on_connect(client):
    snap = client.get("/api/v2/state").json()
    assert snap["mode"] == "standby" and snap["autopilot"]["sensitivity"] == "proactive"
    with client.websocket_connect("/ws", headers={"Host": "127.0.0.1:8770"}) as ws:
        assert ws.receive_json()["kind"] == "hello"
        first = ws.receive_json()
        assert first["type"] == "ui_state" and first["data"]["mode"] == "standby"


def test_websocket_streams_events(client):
    with client.websocket_connect("/ws", headers={"Host": "127.0.0.1:8770"}) as ws:
        assert ws.receive_json()["kind"] == "hello"
        assert ws.receive_json()["type"] == "ui_state"
        client.sk.events.publish("hint", id=1, text="Ravi.", trigger="identity", person_id=None)
        msg = ws.receive_json()
        assert msg["type"] == "hint" and msg["data"]["text"] == "Ravi."


def test_the_translator_warm_up_runs_once_not_every_time_translate_is_switched_on(tmp_path):
    sk = _make(Config(data_dir=tmp_path), FakeLLM())
    calls = []
    sk.translator.translate = lambda text, src, dst: calls.append((src, dst)) or None
    sk._warm_translation()
    sk._warm_translation()
    assert calls == [("te", "en"), ("en", "te")]                      # once: the second switch-on is instant
