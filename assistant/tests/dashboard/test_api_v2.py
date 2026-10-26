import time

import pytest
import yaml
from fastapi.testclient import TestClient

from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.intelligence.llm import FakeLLM
from test_dashboard import _make


@pytest.fixture
def client(tmp_path):
    cfg = Config(data_dir=tmp_path)
    sk = _make(cfg, FakeLLM())
    sk.gestures_path = tmp_path / "gestures.yaml"
    sk.gestures_path.write_text(open(__import__("buds_assistant.core.config", fromlist=["CONFIG_DIR"]).CONFIG_DIR / "sidekick_gestures.yaml").read())
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def seed_conversation(sk):
    ravi, me = sk.store.add_person("Ravi"), sk.store.add_person("Me")
    cid = sk.store.start_conversation("listen")
    t = time.time() - 3600
    s1 = sk.store.add_segment(cid, t, t + 2, ravi, None, 0.9, "I will send the Q3 report by Friday")
    sk.store.add_segment(cid, t + 5, t + 7, me, None, 0.9, "Great, the budget looks fine")
    sk.store.add_fact(ravi, "commitment", "send the Q3 report", "Friday", s1, owner="Ravi")
    sk.store.end_conversation(cid, "Budget catch-up")
    return cid, ravi, me


def test_state_shape_and_legacy_static_moved(client):
    s = client.get("/api/v2/state").json()
    assert {"mode", "memory_level", "buds", "models", "autopilot", "banner"} <= set(s)
    assert "Buds Sidekick" in client.get("/dev/").text and client.get("/dev/app.js").status_code == 200


def test_mode_and_memory_level_with_plain_errors(client):
    assert client.post("/api/v2/mode", json={"mode": "listen"}).json()["mode"] == "listen"
    assert client.post("/api/v2/mode", json={"mode": "nope"}).status_code == 400
    assert client.post("/api/v2/memory-level", json={"level": "live"}).json()["memory_level"] == "live"
    r = client.post("/api/v2/memory-level", json={"level": "recording"})
    assert r.status_code == 400 and "not available yet" in r.json()["detail"]
    assert client.post("/api/v2/memory-level", json={"level": "nope"}).status_code == 400


def test_autopilot_settings_roundtrip_and_audit(client):
    r = client.put("/api/v2/autopilot", json={"sensitivity": "quiet", "categories": {"identity": False, "question": True,
                                                                                     "capture": True, "commitment": True, "mention": True}})
    assert r.status_code == 200
    cfg = client.sk.cfg
    assert cfg.autopilot_sensitivity == "quiet" and "identity" not in cfg.autopilot_categories
    assert client.get("/api/v2/autopilot").json()["sensitivity"] == "quiet"
    assert any(a["kind"] == "settings" for a in client.sk.store.audit_log())
    assert client.put("/api/v2/autopilot", json={"sensitivity": "loud"}).status_code == 400


def test_feed_has_plain_language_reasons(client):
    sk = client.sk
    sk.store.log_decision("question", "held_back", "too_soon", "", None, None, None)
    sk.store.log_decision("capture", "noted", None, "Noted: send it, Friday", None, None, None)
    feed = client.get("/api/v2/autopilot/feed").json()
    assert feed[0]["reason_text"] == "Skipped: too soon after the last whisper"
    assert feed[1]["outcome"] == "noted" and feed[1]["reason_text"] is None


def test_hint_feedback_and_commitment_undo(client):
    sk = client.sk
    me = sk.store.add_person("Me"); fid = sk.store.add_fact(me, "commitment", "send it", "Friday", None, owner="Me")
    hid = sk.store.log_hint("identity", "Ravi.", me, True)
    assert client.post(f"/api/v2/hints/{hid}/feedback", json={"useful": False}).json()["ok"]
    assert sk.policy.muted["identity"] > time.time()
    assert client.post(f"/api/v2/commitments/{fid}/undo").json()["ok"]
    assert sk.store.facts(kind="commitment", status="open") == []


def test_health_reports_a_fix_when_failing(tmp_path):
    sk = _make(Config(data_dir=tmp_path), FakeLLM(up=False))
    checks = {c["id"]: c for c in TestClient(create_app(sk), base_url="http://127.0.0.1:8770").get("/api/v2/health").json()["checks"]}
    assert {"ollama", "models", "buds", "speaker_model", "whisper"} <= set(checks)
    assert checks["ollama"]["ok"] is False and "ollama.com" in checks["ollama"]["fix"]


def test_health_ok_with_fake_llm(client):
    checks = {c["id"]: c for c in client.get("/api/v2/health").json()["checks"]}
    assert checks["ollama"]["ok"] and checks["models"]["ok"]


def test_gestures_get_put_validation_and_reset(client):
    g = client.get("/api/v2/gestures").json()
    assert len(g["slots"]) == 8 and {a["id"] for a in g["actions"]} >= {"ask", "replay", "mark"}
    slots = {s["gesture"]: s["action"] for s in g["slots"]}
    assert client.put("/api/v2/gestures", json={"slots": [{"gesture": "L:single", "action": "teleport"}]}).status_code == 400
    dup = [{"gesture": "L:single", "action": "ask"}, {"gesture": "L:single", "action": "mark"}]
    assert client.put("/api/v2/gestures", json={"slots": dup}).status_code == 400
    slots["L:single"] = "mark"; slots["R:single"] = "ask"
    ok = client.put("/api/v2/gestures", json={"slots": [{"gesture": k, "action": v} for k, v in slots.items()]})
    assert ok.status_code == 200
    assert (client.sk.gestures_path.with_suffix(".yaml.bak")).exists()
    saved = {b["gesture"]: b["action"] for b in yaml.safe_load(client.sk.gestures_path.read_text())["bindings"]}
    assert saved["L:single"] == "mark"
    assert next(b for b in client.sk.modes.recognizers["ear"].bindings if b.pattern == ("L:single",)).action == "mark"   # hot reload
    client.post("/api/v2/gestures/reset")
    assert {s["gesture"]: s["action"] for s in client.get("/api/v2/gestures").json()["slots"]}["L:single"] == "ask"


def test_unnamed_voices_naming_needs_consent(client):
    sk = client.sk
    sk.pipeline.window.append({"t0": 1, "t1": 2, "speaker": "Speaker A", "person_id": None, "cluster": "Speaker A",
                               "text": "hello there", "lang": "en", "seg_id": None, "conf": 0.3, "experimental": False})
    u = client.get("/api/v2/unnamed").json()
    assert u and u[0]["label"] == "Speaker A" and u[0]["utterances"] == 1 and u[0]["last_text"] == "hello there"
    assert client.post("/api/v2/unnamed/Speaker A/name", json={"name": "Priya"}).status_code == 400


def test_person_page_and_two_step_forget(client):
    cid, ravi, me = seed_conversation(client.sk)
    page = client.get(f"/api/v2/people/{ravi}").json()
    assert page["person"]["name"] == "Ravi" and page["commitments"][0]["text"] == "send the Q3 report"
    assert "Q3 report" in page["brief"]
    preview = client.post(f"/api/v2/people/{ravi}/forget-preview").json()
    assert client.get(f"/api/v2/people/{ravi}").status_code == 200            # preview deletes nothing
    done = client.post(f"/api/v2/people/{ravi}/forget").json()
    assert preview["segments"] == done["segments"] == 1 and preview["facts"] == done["facts"] == 1
    assert client.get(f"/api/v2/people/{ravi}").status_code == 404


def test_library_cards_search_and_open_loops(client):
    cid, ravi, me = seed_conversation(client.sk)
    lib = client.get("/api/v2/library").json()
    assert lib[0]["title"] == "Budget catch-up" and set(lib[0]["people"]) == {"Ravi", "Me"}
    assert client.get("/api/v2/library", params={"q": "budget"}).json()[0]["id"] == cid
    assert client.get("/api/v2/library", params={"q": "zzzz"}).json() == []
    one = client.get(f"/api/v2/library/{cid}").json()
    assert len(one["transcript"]) == 2 and one["card"]["id"] == cid
    loops = client.get("/api/v2/open-loops").json()
    assert loops[0]["text"] == "send the Q3 report" and loops[0]["person"] == "Ravi"
    client.post(f"/api/v2/open-loops/{loops[0]['id']}/done")
    assert client.get("/api/v2/open-loops").json() == []
    client.post(f"/api/v2/open-loops/{loops[0]['id']}/reopen")
    assert len(client.get("/api/v2/open-loops").json()) == 1


def test_dashboard_v2_static_assets_are_served_offline(client):
    index = client.get("/").text
    assert 'src="js/main.js"' in index and "http" not in index.replace("http-equiv", "")        # no CDN
    for path in ("/js/main.js", "/js/store.js", "/js/components/ui.js", "/css/tokens.css", "/vendor/htm-preact-standalone.module.js"):
        assert client.get(path).status_code == 200, path


async def test_try_mode_shows_the_gesture_without_doing_it(client):
    sk = client.sk
    assert client.post("/api/v2/gestures/try", json={"on": True}).json()["on"] is True
    await sk.gesture("R:double")                                  # would toggle Autopilot
    assert sk.modes.mode == "standby"
    assert sk.events.recent(types={"token"})[-1]["data"]["token"] == "R:double"
    client.post("/api/v2/gestures/try", json={"on": False})
    await sk.gesture("R:double")
    assert sk.modes.mode == "autopilot"


async def test_try_mode_expires_on_its_own(client):
    sk = client.sk
    client.post("/api/v2/gestures/try", json={"on": True})
    sk.try_until = time.time() - 1                                # the dashboard went away
    await sk.gesture("R:double")
    assert sk.modes.mode == "autopilot"


def test_activity_log_is_plain_language(client):
    sk = client.sk
    sk.store.audit("mode", {"from": "standby", "to": "autopilot", "placement": "ear"})
    sk.store.audit("recording_start", {"from": "remember", "to": "recording"})
    sk.store.audit("forget", {"person_id": 3, "deleted": {"segments": 4, "facts": 1}})
    lines = [a["text"] for a in client.get("/api/v2/activity").json()]
    assert "Switched to Autopilot" in lines and "Started recording audio" in lines
    assert any(l.startswith("Forgot a person") and "4" in l for l in lines)


def test_delete_everything_needs_the_exact_phrase_and_wipes_data(client):
    sk = client.sk
    seed_conversation(sk)
    assert client.post("/api/v2/delete-everything", json={"confirm": "no"}).status_code == 400
    assert sk.store.people()
    done = client.post("/api/v2/delete-everything", json={"confirm": "delete everything"}).json()
    assert done["ok"]
    assert sk.store.people() == [] and sk.store.segments() == [] and sk.store.facts() == [] and sk.store.hints() == []
    assert sk.store.audit_log()[0]["kind"] == "delete_everything"          # the wipe itself is the one thing that stays on record


def test_first_run_download_starts_only_what_is_missing(client, monkeypatch):
    started = []
    monkeypatch.setattr(client.sk.downloads, "pull_model", lambda n: started.append(("model", n)))
    monkeypatch.setattr(client.sk.downloads, "fetch_file", lambda k, u, d: started.append(("file", k)))
    client.sk.cfg.speaker_model = client.sk.cfg.data_dir / "missing.onnx"
    client.sk.llm.models = []                                    # nothing installed
    r = client.post("/api/v2/setup/download")
    assert r.status_code == 200
    assert ("file", "voice model") in started
    assert client.get("/api/v2/setup/download").json() == {"items": {}}
