"""Acceptance: every API call the dashboard JavaScript makes hits a real route, and every non-developer task works through those routes."""
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.intelligence.llm import FakeLLM
from test_dashboard import _make, wav_b64

JS = Path(__file__).resolve().parents[2] / "buds_assistant" / "dashboard" / "web" / "js"
CALL = re.compile(r"api\.(get|post|put)\(\s*([`\"])(/api/[^`\"]*)\2")


@pytest.fixture
def client(tmp_path):
    sk = _make(Config(data_dir=tmp_path), FakeLLM())
    sk.gestures_path = tmp_path / "g.yaml"
    sk.gestures_path.write_text((Path(__file__).resolve().parents[2] / "buds_assistant" / "config" / "sidekick_gestures.yaml").read_text())
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def test_every_api_call_in_the_javascript_matches_a_backend_route(client):
    routes = [(re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$"), {m.upper() for m in ops})
              for path, ops in client.app.openapi()["paths"].items()]
    seen = 0
    for f in JS.rglob("*.js"):
        for m in CALL.finditer(f.read_text()):
            method, path = m.group(1).upper(), re.sub(r"\$\{[^}]*\}", "1", m.group(3)).split("?")[0]
            seen += 1
            assert any(rx.match(path) and method in (methods or {method}) for rx, methods in routes), f"{f.name}: {method} {path}"
    assert seen > 30                                              # the scan really found the calls


def test_no_browser_dialogs_anywhere_in_the_ui():
    for f in JS.rglob("*.js"):
        assert not re.search(r"\b(alert|confirm|prompt)\(", f.read_text()), f.name


def test_every_non_developer_task_can_be_done(client):
    sk = client.sk
    post = lambda p, b=None: client.post(p, json=b or {})                           # noqa: E731
    assert post("/api/v2/setup/enroll-self", {"wav_base64": wav_b64(1, seconds=3)}).status_code == 200      # enrol myself
    ravi = sk.store.add_person("Ravi"); cid = sk.store.start_conversation("listen"); t = time.time() - 3600
    s1 = sk.store.add_segment(cid, t, t + 2, ravi, None, 0.9, "I will send the Q3 report by Friday")
    sk.store.add_fact(ravi, "commitment", "send the Q3 report", "Friday", s1, owner="Ravi"); sk.store.end_conversation(cid, "Budget")
    assert post("/api/ask", {"text": "what time is it"}).status_code == 200                                  # ask
    assert post("/api/v2/mode", {"mode": "listen"}).json()["mode"] == "listen"                               # listen
    assert post("/api/mark").status_code == 200 and post("/api/replay").status_code == 200                   # mark, replay
    assert post("/api/action", {"action": "catch_up"}).status_code == 200                                    # catch me up
    assert post("/api/v2/memory-level", {"level": "live"}).status_code == 200                                 # don't save this one
    assert post("/api/v2/mode", {"mode": "private"}).json()["mode"] == "private"                             # go private
    from test_speaker import clip
    m = sk.speaker.identify(clip(7)); sk.speaker.identify(clip(7))                  # an unknown voice becomes "Speaker A"
    sk.pipeline.window.append({"t0": 1, "t1": 2, "speaker": m.cluster, "person_id": None, "cluster": m.cluster, "text": "hi",
                               "lang": "en", "seg_id": None, "conf": 0.3, "experimental": False})
    assert post(f"/api/v2/unnamed/{m.cluster}/name", {"name": "Priya", "consent": "agreed"}).status_code == 200  # name a voice
    pid = sk.store.person_by_name("Priya")["id"]
    assert post(f"/api/people/{pid}/policy", {"policy": "audio"}).status_code == 200                         # change remember setting
    assert client.put("/api/v2/autopilot", json={"sensitivity": "quiet"}).status_code == 200                 # change sensitivity
    assert client.put("/api/v2/gestures", json={"slots": [{"gesture": "L:single", "action": "mark"}]}).status_code == 200   # remap
    assert client.get("/api/v2/activity").json()                                                              # export / read activity
    assert post(f"/api/v2/people/{ravi}/forget-preview").status_code == 200 and post(f"/api/v2/people/{ravi}/forget").status_code == 200   # forget
    assert post("/api/v2/delete-everything", {"confirm": "delete everything"}).status_code == 200            # delete everything
    assert client.get("/api/v2/library").json() == [] and client.get("/api/v2/open-loops").json() == []
