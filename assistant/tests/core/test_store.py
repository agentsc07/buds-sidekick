import numpy as np

from buds_assistant.core.config import Config
from buds_assistant.core.events import EventBus
from buds_assistant.core.store import Store


def test_config_clamps_ring_and_loads_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("ring_seconds: 500\nchat_model: foo\nunknown_key: 1\n")
    c = Config.load(p)
    assert c.ring_seconds == 60 and c.chat_model == "foo"
    assert Config.load(None).ring_seconds == 8


def test_event_bus_history_and_subscribers():
    bus, got = EventBus(history=3), []
    bus.subscribe(got.append)
    for i in range(5):
        bus.publish("x", i=i)
    assert [e["data"]["i"] for e in bus.recent()] == [2, 3, 4] and len(got) == 5
    bus.subscribe(lambda e: 1 / 0)               # a broken subscriber never breaks publishing
    bus.publish("y")


def test_roundtrip_people_segments_facts(tmp_path):
    s = Store(tmp_path)
    pid = s.add_person("Ravi", "verbal consent 2026-10-01")
    cid = s.start_conversation("conversation")
    sid = s.add_segment(cid, 1.0, 3.0, pid, None, 0.9, "I will send the report Friday")
    s.add_fact(pid, "commitment", "send the report", "Friday", sid, owner="Ravi")
    assert s.segments(person_id=pid)[0]["speaker"] == "Ravi"
    assert s.facts(pid)[0]["due"] == "Friday" and s.people()[0]["samples"] == 0
    assert any(a["kind"] == "enrol" for a in s.audit_log())


def test_forget_removes_every_trace(tmp_path):
    s = Store(tmp_path)
    a, b = s.add_person("Ravi"), s.add_person("Anita")
    cid = s.start_conversation("conversation")
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF")
    sid = s.add_segment(cid, 0, 1, a, None, 0.9, "secret budget number", audio_ref=str(wav))
    s.add_segment(cid, 2, 3, b, None, 0.9, "keep me")
    s.add_voice_sample(a, np.ones(4, dtype=np.float32))
    s.add_fact(a, "fact", "likes tea", None, sid)
    s.add_bookmark(cid, 1.0, a, "note")
    s.log_hint("identity", "that is Ravi", a, True)
    counts = s.forget(a)
    assert counts["segments"] == 1 and counts["audio_files"] == 1 and counts["people"] == 1
    assert not wav.exists()
    for t, col in (("segments", "speaker_id"), ("facts", "person_id"), ("voice_samples", "person_id"),
                   ("bookmarks", "speaker_id"), ("hints", "person_id")):
        assert s.q(f"SELECT COUNT(*) c FROM {t} WHERE {col}=?", (a,))[0]["c"] == 0
    assert [p["name"] for p in s.people()] == ["Anita"] and len(s.segments()) == 1
    log = [x for x in s.audit_log() if x["kind"] == "forget"][0]["detail"]
    assert "secret" not in str(log)                # the deletion record never contains content
    raw = (tmp_path / "sidekick.db").read_bytes()
    assert b"secret budget number" not in raw       # secure_delete overwrote the freed pages


def test_retention_sweep_keeps_transcript(tmp_path):
    s = Store(tmp_path)
    pid = s.add_person("Ravi", policy="audio")
    s.set_policy(pid, "audio", retention_days=1)
    wav = tmp_path / "old.wav"
    wav.write_bytes(b"x")
    cid = s.start_conversation("conversation")
    s.add_segment(cid, 0, 1, pid, None, 1.0, "hello", audio_ref=str(wav))
    import time
    assert s.sweep_retention(time.time() + 3 * 86400) == 1
    assert not wav.exists() and s.segments()[0]["text"] == "hello" and s.segments()[0]["audio_ref"] is None


def test_old_decision_table_without_fact_id_is_migrated(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "sidekick.db")
    db.execute("CREATE TABLE autopilot_decisions(id INTEGER PRIMARY KEY, ts REAL, conv_id INTEGER, trigger TEXT, outcome TEXT, "
               "reason TEXT, text TEXT, person_id INTEGER, hint_id INTEGER)")
    db.commit(); db.close()
    s = Store(tmp_path)
    s.log_decision("capture", "noted", None, "x", None, None, None, 5)
    assert s.decisions()[-1]["fact_id"] == 5
