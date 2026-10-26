"""Autopilot's judgement: with Autopilot on, a small model follows the conversation and speaks only when it can really help."""
import json
import time

import pytest

from buds_assistant.intelligence.autopilot import AutopilotEngine
from buds_assistant.core.config import Config
from buds_assistant.intelligence.judge import Judge, parse_verdict
from buds_assistant.intelligence.llm import FakeLLM, LLMError
from buds_assistant.intelligence.memory import Memory
from buds_assistant.intelligence.personal import Personal
from buds_assistant.core.store import Store
from buds_assistant.intelligence.wake import wake_query


def verdict(say="", todo="", score=4):
    return json.dumps({"say": say, "todo": todo, "score": score})


class Rig:
    def __init__(self, tmp_path, reply, sens="proactive"):
        self.cfg = Config(data_dir=tmp_path, autopilot_sensitivity=sens)
        self.store = Store(tmp_path)
        self.me = self.store.add_person("Me")
        self.llm = FakeLLM(reply if callable(reply) else [reply] * 50)
        self.personal = Personal(self.store)
        self.policy = AutopilotEngine(self.cfg, self.store, Memory(self.store, self.llm), personal=self.personal)
        self.policy.enabled = True
        self.out = []
        self.speaking = False
        self.judge = Judge(self.cfg, self.llm, self.personal, self.policy.memory, self.policy, self.out.append,
                           speaking=lambda: self.speaking, debounce=0.05)

    def turn(self, text, who="Me", now=None, self_=True):
        self.judge.add_turn({"speaker": who, "text": text, "t1": now or time.time(), "is_self": self_, "person_id": self.me if self_ else None})


@pytest.fixture
def rig(tmp_path):
    n = [0]
    def make(reply, sens="proactive"):
        n[0] += 1
        d = tmp_path / f"r{n[0]}"; d.mkdir()
        return Rig(d, reply, sens)
    return make


def test_it_whispers_when_the_model_has_something_useful(rig):
    r = rig(verdict("Quick answer: the Eiffel Tower is 330 metres tall.", score=4))
    r.turn("I need to look up how tall the Eiffel Tower is")
    h = r.judge.evaluate(time.time())
    assert h and h.trigger == "judge" and "330" in h.text
    assert r.store.decisions(5)[-1]["trigger"] == "judge"


def test_it_stays_silent_when_nothing_is_worth_saying(rig):
    r = rig(verdict("", score=1))
    r.turn("okay so the weather is nice today I think")
    assert r.judge.evaluate(time.time()) is None and r.out == []


def test_a_user_who_needs_to_look_something_up_can_get_it_added_to_the_to_dos(rig):
    r = rig(verdict("", todo="look up flights to Hyderabad", score=4))
    r.turn("I need to check flights to Hyderabad for next month")
    h = r.judge.evaluate(time.time())
    assert h and "flights to Hyderabad" in h.text and "to-dos" in h.text
    assert any("flights to Hyderabad" in t["text"] for t in r.personal.todos())


def test_helpful_needs_a_strong_reason_proactive_needs_a_decent_one(rig):
    helpful = rig(verdict("The budget review is on Thursday.", score=3), sens="balanced")
    helpful.turn("when is the budget review again please tell me")
    assert helpful.judge.evaluate(time.time()) is None
    proactive = rig(verdict("The budget review is on Thursday.", score=3), sens="proactive")
    proactive.turn("when is the budget review again please tell me")
    assert proactive.judge.evaluate(time.time()) is not None


def test_quiet_and_off_never_call_the_model(rig):
    q = rig(verdict("Hi", score=5), sens="quiet")
    q.turn("when is the budget review again please tell me")
    assert q.judge.evaluate(time.time()) is None and q.llm.calls == []
    off = rig(verdict("Hi", score=5))
    off.policy.enabled = False
    off.turn("when is the budget review again please tell me")
    assert off.judge.evaluate(time.time()) is None and off.llm.calls == []


def test_it_never_says_the_same_thing_twice_or_too_often(rig):
    r = rig(verdict("The budget review is on Thursday.", score=5))
    r.turn("when is the budget review again please tell me")
    assert r.judge.evaluate(time.time())
    r.turn("and when exactly is that budget review happening")
    assert r.judge.evaluate(time.time() + 1) is None                      # too soon after the last whisper
    r.turn("remind me when the budget review is happening again")
    assert r.judge.evaluate(time.time() + 120) is None                    # long enough, but it is the same sentence


def test_short_chatter_does_not_wake_the_model(rig):
    r = rig(verdict("x", score=5))
    r.turn("yeah okay")
    assert r.judge.evaluate(time.time()) is None and r.llm.calls == []


def test_it_does_not_talk_over_its_own_voice_or_your_speech(rig):
    r = rig(verdict("Hello there friend.", score=5))
    r.speaking = True
    r.turn("when is the budget review again please tell me")
    assert r.judge.evaluate(time.time()) is None and r.llm.calls == []


def test_a_broken_or_down_model_is_silence_not_a_crash(rig):
    r = rig("not json at all {{")
    r.turn("when is the budget review again please tell me")
    assert r.judge.evaluate(time.time()) is None
    d = rig(lambda m, model: (_ for _ in ()).throw(LLMError("down")))
    d.turn("when is the budget review again please tell me")
    assert d.judge.evaluate(time.time()) is None


def test_the_prompt_carries_the_conversation_your_day_and_what_it_already_said(rig):
    r = rig(verdict("The review is Thursday.", score=5))
    r.personal.seed_sample(__import__("datetime").datetime.now(), force=True)
    r.turn("Ravi said he sends the report", who="Ravi", self_=False)
    r.turn("when is the budget review again please tell me")
    r.judge.evaluate(time.time())
    prompt = json.dumps(r.llm.calls[0]["messages"])
    assert "Me: when is the budget review" in prompt and "Ravi: Ravi said" in prompt and "Calendar" in prompt


def test_bursts_of_segments_make_one_judgement(rig):
    r = rig(verdict("The review is Thursday.", score=5))
    for i in range(5):
        r.turn(f"so when is the budget review again please tell me {i}")
    r.judge.start_timer()
    time.sleep(0.4)
    assert len(r.llm.calls) == 1 and len(r.out) == 1


def test_parse_verdict_is_forgiving():
    assert parse_verdict('{"say": "Hi", "todo": "", "score": 4}')["say"] == "Hi"
    assert parse_verdict('```json\n{"say": "Hi", "score": "5"}\n```')["score"] == 5
    assert parse_verdict("nonsense") is None


def test_wake_word_forms():
    assert wake_query("Hey Sidekick, what's on my calendar today?") == "what's on my calendar today?"
    assert wake_query("sidekick what time is it") == "what time is it"
    assert wake_query("Okay Autopilot, add milk to my to-do list") == "add milk to my to-do list"
    assert wake_query("Sidekick") == ""
    assert wake_query("I think the sidekick in that film was funny") is None
    assert wake_query("what's on my calendar today") is None


def test_it_does_not_add_a_to_do_you_already_have(rig):
    r = rig(verdict("", todo="Book the demo room", score=5))
    r.personal.add_todo("book the demo room", "tomorrow")
    r.turn("hmm what did I need to do about the demo again please")
    assert r.judge.evaluate(time.time()) is None                         # nothing new to say or add
    assert len([t for t in r.personal.todos() if "demo room" in t["text"].lower()]) == 1
