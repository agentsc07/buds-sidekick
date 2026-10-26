import numpy as np
import pytest
from fastapi.testclient import TestClient

from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.audio.mic_check import measure
from test_dashboard import _make, wav_b64


@pytest.fixture
def client(tmp_path):
    sk = _make(Config(data_dir=tmp_path), FakeLLM())
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def tone(seconds, amp, noise=30):
    rng = np.random.default_rng(0)
    t = np.arange(int(16000 * seconds)) / 16000
    return (amp * np.sin(2 * np.pi * 220 * t) + rng.standard_normal(t.size) * noise).astype(np.int16)


def test_measure_reports_higher_snr_for_cleaner_audio():
    quiet_room = np.concatenate([tone(1, 0, 20), tone(1, 6000, 20), tone(1, 0, 20)])
    noisy_room = np.concatenate([tone(1, 0, 900), tone(1, 6000, 900), tone(1, 0, 900)])
    assert measure(quiet_room)["snr_db"] > measure(noisy_room)["snr_db"] + 10
    assert measure(np.zeros(100, dtype=np.int16))["snr_db"] == 0.0           # nothing heard, no crash


def test_mic_check_recommends_the_clearer_source(client):
    sk = client.sk

    def record_from(placement, seconds):
        return np.concatenate([tone(1, 0, 20), tone(1, 6000, 20)]) if placement == "remote" else np.concatenate([tone(1, 0, 900), tone(1, 6000, 900)])
    sk.record_from = record_from
    r = client.post("/api/v2/setup/mic-check", json={"seconds": 2}).json()
    assert r["recommend"] == "remote" and r["mac"]["snr_db"] > r["buds"]["snr_db"]
    assert "Mac" in r["advice"]


def test_mic_check_survives_a_missing_buds_mic(client):
    sk = client.sk

    def record_from(placement, seconds):
        if placement == "ear":
            raise RuntimeError("buds mic not available")
        return tone(2, 6000, 20)
    sk.record_from = record_from
    r = client.post("/api/v2/setup/mic-check", json={"seconds": 2}).json()
    assert r["buds"] is None and r["recommend"] == "remote" and r["errors"]["buds"]


def test_enroll_self_creates_me_and_rejects_short_samples(client):
    assert client.post("/api/v2/setup/enroll-self", json={"wav_base64": wav_b64(1, seconds=1)}).status_code == 400
    ok = client.post("/api/v2/setup/enroll-self", json={"wav_base64": wav_b64(1, seconds=3)})
    assert ok.status_code == 200
    p = client.sk.store.person_by_name("Me")
    assert p and p["consent_note"]
    assert client.post("/api/v2/setup/enroll-self", json={"wav_base64": wav_b64(1, seconds=3)}).status_code == 400   # already set up


def test_setup_status_and_done_persist(client, tmp_path):
    assert client.get("/api/v2/setup/status").json() == {"done": False, "has_me": False, "me_ready": False}
    client.post("/api/v2/setup/enroll-self", json={"wav_base64": wav_b64(1, seconds=3)})
    assert client.get("/api/v2/setup/status").json()["has_me"] is True
    client.post("/api/v2/setup/done")
    assert client.get("/api/v2/setup/status").json()["done"] is True
    sk2 = _make(Config(data_dir=tmp_path), FakeLLM())                     # a new run reads the same file
    assert TestClient(create_app(sk2), base_url="http://127.0.0.1:8770").get("/api/v2/setup/status").json()["done"] is True
