"""Proactive Autopilot with your own data: promises become to-dos, availability answers itself, meetings and reminders announce themselves."""
import asyncio
import time
from datetime import datetime, timedelta

import pytest

from buds_assistant.intelligence.autopilot import AutopilotEngine
from buds_assistant.intelligence.brain import Brain
from buds_assistant.core.config import Config
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.intelligence.personal import Personal
from buds_assistant.core.store import Store
from buds_assistant.speech.translate import Translator
from buds_assistant.intelligence.agent import RuleAgent
from test_dashboard import _make


def tomorrow_at(h, m=0):
    return (datetime.now().replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)).timestamp()


@pytest.fixture
def eng(tmp_path):
    s = Store(tmp_path); me = s.add_person("Me"); priya = s.add_person("Priya")
    pe = Personal(s)
    e = AutopilotEngine(Config(data_dir=tmp_path), s, Memory(s, FakeLLM()), personal=pe); e.enabled = True
    e.me, e.priya, e.pe, e.s = me, priya, pe, s
    return e


def say(e, who, text, self_=False, now=None):
    pid = e.me if self_ else e.priya
    return e.on_segment({"person_id": pid, "speaker": "Me" if self_ else "Priya", "text": text, "is_self": self_, "seg_id": None}, now or time.time())


def test_a_promise_becomes_a_todo_and_the_whisper_says_so(eng):
    h = say(eng, "me", "I'll send the deck on Friday", self_=True)
    assert h.trigger == "capture" and "to your to-dos" in h.text
    t = eng.pe.todos()[0]
    assert t["text"] == "send the deck" and t["due_text"] == "Friday" and t["fact_id"] == h.fact_id and t["source"] == "promise"
    assert datetime.fromtimestamp(t["due"]).strftime("%A") == "Friday"


def test_a_promise_with_a_clashing_time_warns_you(eng):
    eng.pe.add_event("Budget review", tomorrow_at(14), tomorrow_at(15))
    h = say(eng, "me", "I'll call Ravi tomorrow at 2", self_=True)
    assert "Budget review" in h.text


def test_availability_is_answered_when_someone_asks(eng):
    eng.pe.add_event("Budget review", tomorrow_at(14), tomorrow_at(15))
    h = say(eng, "priya", "Are you free tomorrow at 2?")
    assert h.trigger == "calendar" and h.text == "You have Budget review tomorrow at 2 pm."
    eng.last_hint = 0
    h2 = say(eng, "priya", "Okay then how about tomorrow at 4?", now=time.time() + 30)
    assert h2.trigger == "calendar" and h2.text == "You're free tomorrow at 4 pm."


def test_availability_is_checked_when_you_propose_a_time(eng):
    eng.pe.add_event("Dentist", tomorrow_at(9, 30), tomorrow_at(10, 30))
    h = say(eng, "me", "Let's meet tomorrow at 10", self_=True)
    assert h.trigger == "calendar" and "Dentist" in h.text


def test_a_question_about_something_on_your_calendar_is_answered(eng):
    eng.pe.add_event("Demo with the client", tomorrow_at(10), None)
    h = say(eng, "priya", "When is the demo?")
    assert h.trigger == "question" and "Demo with the client" in h.text


def test_the_identity_cue_mentions_a_meeting_with_that_person(eng):
    eng.pe.add_event("1:1 with Priya", tomorrow_at(11), None, ["Priya"])
    eng.pe.add_todo("send Priya the deck", "Friday")
    h = say(eng, "priya", "Good morning")
    assert h.trigger == "identity" and "You meet tomorrow at 11 am" in h.text and "To do: send Priya the deck" in h.text


def test_meetings_and_reminders_announce_themselves(eng):
    now = time.time()
    eng.pe.add_event("Standup", now + 9 * 60, None, ["Ravi"])
    h = eng.system_hint("meeting", "Standup in 10 minutes, with Ravi", now)
    assert h.trigger == "meeting" and h.id and not h.any_mode
    r = eng.system_hint("reminder", "Reminder: call mum", now, any_mode=True)
    assert r.any_mode
    assert [d["trigger"] for d in eng.s.decisions()][-2:] == ["meeting", "reminder"]


def test_quiet_mode_still_delivers_reminders_but_not_meetings(eng):
    eng.cfg.autopilot_sensitivity = "quiet"
    assert eng.system_hint("meeting", "Standup in 10 minutes", time.time()) is None
    assert eng.system_hint("reminder", "Reminder: call mum", time.time(), any_mode=True) is not None


def test_proactive_is_the_default():
    c = Config()
    assert c.autopilot_sensitivity == "proactive" and c.hint_min_gap <= 10 and c.hints_per_hour >= 30


# ---- Ask: your agenda by voice or text ---------------------------------------------------------------------------
@pytest.fixture
def brain(tmp_path):
    s = Store(tmp_path); pe = Personal(s)
    mem = Memory(s, FakeLLM())
    b = Brain(mem, Translator(FakeLLM(), "x"), FakeLLM(up=False), RuleAgent(tmp_path / "n.jsonl"), s, personal=pe)
    b.pe = pe
    return b


def ask(b, text):
    return b.respond(text, {"now": datetime.now()}).text


def test_ask_for_your_calendar(brain):
    brain.pe.add_event("Standup", tomorrow_at(10), None, ["Ravi"])
    assert "Standup at 10 am" in ask(brain, "what's on my calendar tomorrow")
    assert "nothing" in ask(brain, "what's on my schedule today").lower()
    assert "Standup" in ask(brain, "what's my next meeting")


def test_ask_if_you_are_free(brain):
    brain.pe.add_event("Standup", tomorrow_at(10), None)
    assert ask(brain, "am I free tomorrow at 10") == "You have Standup tomorrow at 10 am."
    assert ask(brain, "am I free tomorrow at 3") == "You're free tomorrow at 3 pm."


def test_add_and_list_todos_by_voice(brain):
    assert ask(brain, "add buy milk to my to-do list") == "Done, I've added buy milk to your to-dos."
    assert "buy milk" in ask(brain, "what are my to-dos")
    assert [t["text"] for t in brain.pe.todos()] == ["buy milk"]


def test_remind_me(brain):
    r = ask(brain, "remind me to call mum tomorrow at 9")
    assert "call mum" in r and "tomorrow at 9 am" in r
    rem = brain.pe.reminders()[0]
    assert rem["text"] == "call mum" and datetime.fromtimestamp(rem["due"]).hour == 9


def test_schedule_something_and_warn_about_a_clash(brain):
    assert ask(brain, "schedule lunch with Priya tomorrow at 1") == "Added lunch with Priya tomorrow at 1 pm."
    assert "already" in ask(brain, "schedule dentist tomorrow at 1").lower()
