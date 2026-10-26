"""Regression tests for the final whole-branch review (each was a real defect)."""
import asyncio
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from buds_assistant.intelligence.autopilot import AutopilotEngine, Hint
from buds_assistant.audio.capture import RingBuffer
from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.core.events import EventBus
from buds_assistant.controls.gestures import Binding, GestureRecognizer
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.audio.output import FakePlayer, FakeTTS, OutputArbiter
from buds_assistant.core.pipeline import ConversationPipeline
from buds_assistant.audio.segmenter import Segment
from buds_assistant.speech.speaker import SpeakerEngine
from buds_assistant.core.store import Store
from buds_assistant.speech.transcribe import FakeTranscriber
from test_dashboard import _make
from test_speaker import FakeEmbedder, clip


@pytest.fixture
def sk(tmp_path):
    k = _make(Config(data_dir=tmp_path, hint_ttl=0.5), FakeLLM())
    k.modes.mode = "autopilot"
    return k


@pytest.fixture
def client(sk):
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    c.sk = sk
    return c


def pipe_for(tmp_path, texts=("hello",)):
    cfg = Config(data_dir=tmp_path)
    s = Store(tmp_path)
    spk = SpeakerEngine(FakeEmbedder(), s)
    ana = spk.enroll("Ana", [clip(1), clip(1)], "ok")
    p = ConversationPipeline(cfg, s, spk, FakeTranscriber(list(texts)), Memory(s, FakeLLM()), None, EventBus(), RingBuffer(8))
    p.conv_id = s.start_conversation("listen")
    return s, p, ana


# ---- 1 ------------------------------------------------------------------------------------------------------------
def test_stop_without_a_worker_leaves_no_stale_sentinel(tmp_path):
    s, p, _ = pipe_for(tmp_path)
    p.stop()
    assert p._q.qsize() == 0                                    # a leftover None would kill the next worker at once


# ---- 2 ------------------------------------------------------------------------------------------------------------
def test_live_only_saves_nothing(tmp_path):
    s, p, ana = pipe_for(tmp_path)
    p.persist = False
    p.feed_segment(Segment(0, 1, clip(1, 16000 * 2)))
    assert s.segments() == [] and len(p.window) == 1            # still shown live, never stored


async def test_memory_level_live_switches_persistence_off_and_back(sk):
    await sk.modes.set_mode("listen")
    await sk.modes.set_memory_level("live")
    assert sk.pipeline.persist is False
    await sk.modes.set_memory_level("remember")
    assert sk.pipeline.persist is True


def test_recording_is_not_offered_until_it_exists(client):
    client.post("/api/v2/mode", json={"mode": "listen"})
    r = client.post("/api/v2/memory-level", json={"level": "recording"})
    assert r.status_code == 400 and "not available yet" in r.json()["detail"]


# ---- 3 ------------------------------------------------------------------------------------------------------------
def test_cross_site_requests_are_refused(client):
    pid = client.sk.store.add_person("Ravi")
    bad = {"Origin": "http://evil.example"}
    assert client.post(f"/api/v2/people/{pid}/forget", headers=bad).status_code == 403
    assert client.post(f"/api/people/{pid}/forget", headers=bad).status_code == 403
    assert client.get("/api/events", headers=bad).status_code == 403
    assert client.sk.store.person(pid)                                           # nothing was deleted
    assert client.post(f"/api/v2/people/{pid}/forget-preview", headers={"Origin": "http://127.0.0.1:8770"}).status_code == 200


def test_unknown_host_header_is_refused_dns_rebinding(client):
    assert client.get("/api/v2/state", headers={"Host": "evil.example:8770"}).status_code == 403
    assert client.get("/api/v2/state", headers={"Host": "localhost:8770"}).status_code == 200


def test_websocket_refuses_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"Origin": "http://evil.example", "Host": "127.0.0.1:8770"}) as ws:
            ws.receive_json()
    with client.websocket_connect("/ws", headers={"Origin": "http://127.0.0.1:8770", "Host": "127.0.0.1:8770"}) as ws:
        assert ws.receive_json()["kind"] == "hello"


# ---- 4 ------------------------------------------------------------------------------------------------------------
def seed_person_traces(sk):
    ravi = sk.store.add_person("Ravi")
    cid = sk.store.start_conversation("listen")
    sid = sk.store.add_segment(cid, 1, 2, ravi, None, 0.9, "I will send the report", "en", None)
    sk.store.log_decision("commitment", "said", None, "Reminder: Ravi said they would send it", ravi, cid, None)
    (sk.cfg.data_dir / "people" / str(ravi)).mkdir(parents=True)
    sk.events.publish("segment", speaker="Ravi", person_id=ravi, text="I will send the report")
    sk.events.publish("hint", id=1, text="Ravi.", trigger="identity", person_id=ravi)
    sk.ring.push(np.ones(16000, dtype=np.int16))
    return ravi


def test_forget_removes_decisions_dirs_and_in_memory_traces(client):
    sk = client.sk
    ravi = seed_person_traces(sk)
    assert client.post(f"/api/v2/people/{ravi}/forget").status_code == 200
    assert sk.store.decisions() == []
    assert not (sk.cfg.data_dir / "people" / str(ravi)).exists()
    assert not [e for e in sk.events.recent(800) if e["data"].get("person_id") == ravi or e["data"].get("speaker") == "Ravi"]
    assert sk.ring.seconds == 0


async def test_delete_everything_clears_files_memory_and_stops_capture(client):
    sk = client.sk
    seed_person_traces(sk)
    (sk.cfg.data_dir / "notes.jsonl").write_text('{"text": "note that the code is 1234"}\n')
    (sk.cfg.data_dir / "audio").mkdir(); (sk.cfg.data_dir / "audio" / "x.wav").write_bytes(b"RIFF")
    sk.last_hint = Hint("x", "identity", 1)
    assert client.post("/api/v2/delete-everything", json={"confirm": "delete everything"}).status_code == 200
    assert not (sk.cfg.data_dir / "notes.jsonl").exists() and not (sk.cfg.data_dir / "audio").exists()
    assert not [e for e in sk.events.recent(800) if e["type"] in ("segment", "hint", "reply", "autopilot_decision")]
    assert sk.ring.seconds == 0 and sk.last_hint is None and sk.ui.snapshot()["autopilot"]["feed"] == []


# ---- 5 ------------------------------------------------------------------------------------------------------------
def test_a_long_hold_toggles_once_even_if_only_start_and_end_arrive():
    r = GestureRecognizer([Binding("l", ("R:hold",), "listen_toggle", "toggle")], 0.7, 1.2)
    fired = r.feed("R:hold_start", 0.0) + r.feed("R:hold_end", 2.0)
    assert len(fired) == 1
    assert len(r.feed("R:hold_start", 6.0)) == 1                             # a separate, later hold still toggles


# ---- 6 ------------------------------------------------------------------------------------------------------------
async def test_whisper_window_is_open_while_the_whisper_plays(sk):
    sk.output.players["ear"].hold = 0.6
    h = Hint("Ravi. He owes you the Q3 report.", "identity", 1, ts=time.time())
    task = asyncio.create_task(sk._deliver(h))
    await asyncio.sleep(0.5)                                                  # earcon + the whisper are playing
    assert sk.modes.context.intercept("R:double", time.monotonic(), speaking=False) == "not_useful"
    await task


async def test_a_short_phrase_does_not_count_as_speech_to_stop():
    out = OutputArbiter(FakeTTS(), {"ear": FakePlayer(hold=0.3), "remote": FakePlayer()})
    t = asyncio.create_task(out.say("Autopilot on", "en", "chime", whisper=True))
    await asyncio.sleep(0.1)
    assert out.busy and not out.speaking                                      # a mode phrase must not turn the next tap into "stop"
    await t
    t = asyncio.create_task(out.say("Here is the answer", "en", "answer"))
    await asyncio.sleep(0.1)
    assert out.speaking
    await t


# ---- 7 ------------------------------------------------------------------------------------------------------------
async def test_a_hint_is_dropped_if_the_mode_changed_before_it_could_play(sk):
    sk.modes.mode = "standby"
    await sk.modes.set_mode("private")
    await sk._deliver(Hint("late", "identity", 1, ts=time.time()))
    assert ("identity", "held_back", "mode_changed") in [(d["trigger"], d["outcome"], d["reason"]) for d in sk.store.decisions()]
    assert not any(x["kind"] == "speak" and x.get("text") == "late" for x in sk.output.log)


async def test_private_turns_autopilot_off_before_the_pipeline_flushes(tmp_path):
    from test_modes import make
    mc, pipe, *_ = make(tmp_path)
    await mc.set_mode("autopilot")
    seen = []
    orig = pipe.stop
    pipe.stop = lambda extract=True, discard=False: (seen.append(mc.policy.enabled), orig(extract, discard))
    await mc.set_mode("private")
    assert seen == [False]


# ---- 8 ------------------------------------------------------------------------------------------------------------
async def test_ask_is_refused_in_private(sk):
    calls = []

    async def ask(**k): calls.append(1)
    sk.modes.handlers["ask"] = ask
    await sk.modes.set_mode("private")
    await sk.modes.dispatch("ask")
    assert calls == []


async def test_a_failed_ask_does_not_swallow_the_next_utterance(sk):
    sk.cfg.ask_timeout = 0.1
    await sk.modes.set_mode("listen")
    sk.loop = asyncio.get_running_loop()
    await sk._ask()
    assert sk.pipeline._waiters == []
    assert any("didn't catch that" in (x.get("text") or "") for x in sk.output.log)


# ---- 9 ------------------------------------------------------------------------------------------------------------
def _engine(tmp_path, **kw):
    s = Store(tmp_path); me = s.add_person("Me")
    p = AutopilotEngine(Config(data_dir=tmp_path, **kw), s, Memory(s, FakeLLM())); p.enabled = True
    return p, s, me


def seg(me, text, **k):
    return {"person_id": me, "speaker": "Me", "text": text, "is_self": True, "seg_id": None, **k}


def test_a_promise_is_saved_even_when_the_whisper_is_budgeted_away(tmp_path):
    p, s, me = _engine(tmp_path, hints_per_hour=0)
    assert p.on_segment(seg(me, "I'll send it Friday"), 1000.0) is None
    assert s.facts(person_id=me, kind="commitment")[0]["text"] == "send it"
    assert ("capture", "held_back", "hourly_budget") in [(d["trigger"], d["outcome"], d["reason"]) for d in s.decisions()]


def test_capture_switched_off_saves_nothing(tmp_path):
    p, s, me = _engine(tmp_path, autopilot_categories=["identity"])
    p.on_segment(seg(me, "I'll send it Friday"), 1000.0)
    assert s.facts(kind="commitment") == []


def test_an_unsure_voice_that_made_a_promise_is_logged(tmp_path):
    p, s, me = _engine(tmp_path)
    p.on_segment(seg(me, "I'll send it Friday", is_self=False), 1000.0)
    assert ("capture", "held_back", "unsure_voice") in [(d["trigger"], d["outcome"], d["reason"]) for d in s.decisions()]


async def test_a_stale_hint_rewrites_its_row_instead_of_logging_twice(sk):
    sk.policy.enabled = True
    me = sk.store.add_person("Me")
    h = sk.policy.on_segment(seg(me, "I'll send it Friday"), time.time() - 30)      # decided 30 s ago
    await sk._deliver(h)
    rows = [d for d in sk.store.decisions() if d["trigger"] == "capture"]
    assert len(rows) == 1 and rows[0]["outcome"] == "held_back" and rows[0]["reason"] == "stale"


def test_decision_events_carry_plain_reason_text_and_conversation(tmp_path):
    p, s, me = _engine(tmp_path, hints_per_hour=0)
    p.events = EventBus(); p.conv_id = 5
    p.on_segment(seg(me, "I'll send it Friday"), 1000.0)
    d = p.events.recent(types={"autopilot_decision"})[-1]["data"]
    assert d["reason_text"] == "Skipped: hourly limit reached" and d["conv_id"] == 5


# ---- 10 -----------------------------------------------------------------------------------------------------------
def test_ui_snapshot_names_the_wearer(sk):
    assert sk.ui.snapshot()["self_name"] == sk.cfg.self_name


# ---- 11 -----------------------------------------------------------------------------------------------------------
async def test_mode_changes_are_serialized(tmp_path):
    from test_modes import make
    mc, pipe, *_ = make(tmp_path)
    log = []
    orig_stop, orig_start = pipe.stop, pipe.start

    def slow_stop(extract=True):
        log.append("stop-begin"); time.sleep(0.15); orig_stop(extract); log.append("stop-end")

    def start(*a, **k):
        log.append("start"); return orig_start(*a, **k)
    pipe.stop, pipe.start = slow_stop, start
    await mc.set_mode("listen")
    await asyncio.gather(mc.set_mode("standby"), mc.set_mode("listen"))
    assert log.index("stop-end") < len(log) - 1 and log[log.index("stop-begin") + 1] == "stop-end"   # no start inside a stop
    assert mc.mode == "listen" and pipe.conv_id == 7


# ---- 12 -----------------------------------------------------------------------------------------------------------
def test_settings_outside_safe_ranges_are_refused(client):
    for k, v in (("speaker_threshold", 0), ("speaker_threshold", 1.5), ("hints_per_hour", -1), ("hint_min_gap", 100000), ("hint_max_words", 0)):
        r = client.post("/api/settings", json={k: v})
        assert r.status_code == 400, (k, v)
    assert client.sk.cfg.speaker_threshold == Config().speaker_threshold
    assert client.post("/api/settings", json={"speaker_threshold": 0.7}).status_code == 200
