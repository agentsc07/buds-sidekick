import time

import pytest

from buds_assistant.intelligence.autopilot import Hint
from buds_assistant.core.config import Config
from buds_assistant.intelligence.llm import FakeLLM
from test_dashboard import _make


@pytest.fixture
def sk(tmp_path):
    k = _make(Config(data_dir=tmp_path, hint_ttl=0.5), FakeLLM())
    k.modes.mode = "autopilot"                                  # delivery only happens in Autopilot
    return k


def dec(sk):
    return [(d["trigger"], d["outcome"], d["reason"]) for d in sk.store.decisions()]


async def test_hint_is_spoken_and_opens_whisper_window(sk):
    h = Hint("Ravi. He owes you the Q3 report.", "identity", 1, ts=time.time()); h.id = 1
    await sk._deliver(h)
    assert any(x["kind"] == "speak" and x["priority"] == "hint" for x in sk.output.log)
    assert sk.last_hint is h
    assert sk.modes.context.intercept("L:single", time.monotonic(), speaking=False) == "tell_more"


async def test_noted_hint_opens_the_undo_window(sk):
    h = Hint("Noted: send it, Friday", "capture", 1, kind="noted", ts=time.time())
    await sk._deliver(h)
    assert sk.modes.context.intercept("L:double", time.monotonic(), speaking=False) == "undo_commitment"


async def test_stale_hint_is_dropped_with_reason(sk):
    h = Hint("old", "identity", 1, ts=time.time() - 10)
    await sk._deliver(h)
    assert ("identity", "held_back", "stale") in dec(sk)
    assert not any(x["kind"] == "speak" for x in sk.output.log)


async def test_hint_waits_while_wearer_speaks_then_drops(sk):
    sk.pipeline.user_speaking = lambda: True
    h = Hint("late", "identity", 1, ts=time.time())
    await sk._deliver(h)
    assert ("identity", "held_back", "you_were_speaking") in dec(sk)
    assert not any(x["kind"] == "speak" for x in sk.output.log)


async def test_hint_is_delivered_after_a_short_gap(sk):
    state = {"n": 0}

    def speaking():
        state["n"] += 1
        return state["n"] < 3                                  # speaking for two polls, then a gap
    sk.pipeline.user_speaking = speaking
    await sk._deliver(Hint("ok", "identity", 1, ts=time.time()))
    assert any(x["kind"] == "speak" for x in sk.output.log)


async def test_not_useful_mutes_that_trigger(sk):
    h = Hint("x", "identity", 1, ts=time.time()); h.id = sk.store.log_hint("identity", "x", 1, True)
    sk.last_hint = h
    await sk._handlers()["not_useful"]()
    assert sk.policy.muted["identity"] > time.time()
    assert sk.store.hints()[0]["feedback"] == -1


async def test_undo_commitment_cancels_fact(sk):
    me = sk.store.add_person("Me"); fid = sk.store.add_fact(me, "commitment", "send it", "Friday", None, owner="Me")
    h = Hint("Noted: send it, Friday", "capture", me, kind="noted", ts=time.time(), fact_id=fid)
    sk.last_hint = h
    await sk._handlers()["undo_commitment"]()
    assert sk.store.facts(person_id=me, kind="commitment", status="open") == []


async def test_tell_more_reads_the_source_line(sk):
    ravi = sk.store.add_person("Ravi"); cid = sk.store.start_conversation("listen")
    sid = sk.store.add_segment(cid, time.time() - 86400, time.time() - 86398, ravi, None, 0.9, "I will send the Q3 report by Friday")
    sk.last_hint = Hint("Ravi. Open: send the Q3 report", "identity", ravi, [sid], ts=time.time())
    await sk._handlers()["tell_more"]()
    spoken = [x["text"] for x in sk.output.log if x["kind"] == "speak"]
    assert any("Q3 report" in t and t.startswith("From ") for t in spoken)


async def test_tell_more_without_a_source_says_so(sk):
    sk.last_hint = Hint("x", "identity", 1, [], ts=time.time())
    await sk._handlers()["tell_more"]()
    assert any(x.get("text") == "No more detail." for x in sk.output.log)


def test_segmenter_reports_speaking():
    import numpy as np
    from buds_assistant.audio.segmenter import Segmenter
    seg = Segmenter()
    assert seg.speaking is False
    loud = (np.random.default_rng(0).standard_normal(16000) * 6000).astype(np.int16)
    seg.feed((np.random.default_rng(1).standard_normal(8000) * 20).astype(np.int16))    # calibrate on quiet
    seg.feed(loud[:6000])
    assert seg.speaking is True


async def test_engine_decisions_reach_the_ui_feed(sk):
    me = sk.store.add_person("Me"); sk.policy.enabled = True
    sk.policy.on_segment({"person_id": me, "speaker": "Me", "text": "I'll send it Friday", "is_self": True, "seg_id": None}, time.time())
    feed = sk.ui.snapshot()["autopilot"]["feed"]
    assert feed and feed[-1]["outcome"] == "noted"
