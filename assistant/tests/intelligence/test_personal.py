from datetime import datetime, timedelta

import pytest

from buds_assistant.intelligence.personal import Personal
from buds_assistant.core.store import Store

NOW = datetime(2026, 10, 7, 11, 0)             # Wednesday 11:00


def at(day_offset, h, m=0):
    return (NOW.replace(hour=h, minute=m) + timedelta(days=day_offset)).timestamp()


@pytest.fixture
def p(tmp_path):
    return Personal(Store(tmp_path))


def test_sample_data_is_seeded_once_flagged_and_removable(p):
    assert p.seed_sample(NOW) > 0
    assert p.seed_sample(NOW) == 0                                       # never twice
    assert all(e["sample"] for e in p.events_between(NOW.timestamp(), at(7, 0)))
    assert p.todos() and p.next_event(NOW.timestamp())
    p.clear_sample()
    assert p.events_between(0, 9e12) == [] and p.todos() == []
    assert p.seed_sample(NOW) == 0                                       # clearing is a decision: it stays cleared


def test_conflicts_and_availability_answers(p):
    p.add_event("Budget review", at(1, 14), at(1, 15), ["Priya"])
    assert [e["title"] for e in p.conflicts(at(1, 14, 30), at(1, 15, 30))] == ["Budget review"]
    assert p.conflicts(at(1, 15), at(1, 16)) == []                       # back-to-back is fine
    assert p.answer_availability("are you free tomorrow at 2", NOW) == "You have Budget review tomorrow at 2 pm."
    assert p.answer_availability("are you free tomorrow at 4", NOW) == "You're free tomorrow at 4 pm."
    assert p.answer_availability("how about Friday", NOW) == "Your Friday is clear."
    assert "Budget review" in p.answer_availability("what about tomorrow", NOW)
    assert p.answer_availability("I like pizza", NOW) is None


def test_reminders_become_due_once(p):
    rid = p.add_reminder("call mum", at(0, 12))
    assert p.due_reminders(at(0, 11)) == []
    assert [r["text"] for r in p.due_reminders(at(0, 12, 1))] == ["call mum"]
    p.complete_reminder(rid)
    assert p.due_reminders(at(0, 13)) == []


def test_todos_lifecycle_and_link_to_a_promise(p):
    tid = p.add_todo("send the deck", "Friday", at(2, 9), source="promise", fact_id=7)
    assert [t["text"] for t in p.todos()] == ["send the deck"]
    p.cancel_for_fact(7)                                                 # undo of the promise removes its to-do
    assert p.todos() == []
    t2 = p.add_todo("book room")
    p.complete_todo(t2)
    assert p.todos() == [] and [t["text"] for t in p.todos("done")] == ["book room"]


def test_events_announce_at_ten_and_two_minutes_once_each(p):
    p.add_event("Standup", NOW.timestamp() + 9 * 60, None, ["Ravi"])
    first = p.upcoming_to_announce(NOW.timestamp())
    assert [(e["title"], mins) for e, mins in first] == [("Standup", 10)]
    assert p.upcoming_to_announce(NOW.timestamp() + 30) == []            # not again
    later = p.upcoming_to_announce(NOW.timestamp() + 7 * 60 + 1)
    assert [(e["title"], m) for e, m in later] == [("Standup", 2)]
    assert p.upcoming_to_announce(NOW.timestamp() + 8 * 60) == []


def test_search_finds_the_thing_a_question_is_about(p):
    p.add_event("Demo with the client", at(7, 10), None, [])
    p.add_todo("review the Q3 report", "Friday")
    assert "Demo with the client" in p.search("when is the demo", NOW)
    assert "review the Q3 report" in p.search("did I have to do the report", NOW)
    assert p.search("what is the weather", NOW) is None


def test_agenda_text_for_the_language_model(p):
    p.add_event("Standup", at(0, 15), None, ["Ravi"])
    p.add_todo("send the deck", "Friday")
    t = p.agenda_text(NOW)
    assert "Standup" in t and "send the deck" in t


def test_delete_everything_clears_personal_data(tmp_path):
    s = Store(tmp_path); pe = Personal(s)
    pe.seed_sample(NOW)
    s.wipe()
    assert pe.events_between(0, 9e12) == [] and pe.todos() == []
