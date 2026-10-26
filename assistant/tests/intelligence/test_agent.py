import random
from datetime import datetime

from buds_assistant.intelligence.agent import RuleAgent

CTX = {"now": datetime(2026, 9, 29, 14, 5), "battery": {"left": 90, "right": 88, "case": 42}}


def ask(a, text, ctx=CTX):
    return a.respond(text, ctx)


def test_basic_intents(tmp_path):
    a = RuleAgent(tmp_path / "n.jsonl", random.Random(1))
    assert ask(a, "What's the time?").text == "It is 2:05 PM."
    assert "Tuesday, September 29" in ask(a, "what is the date today").text
    assert "Left 90 percent" in ask(a, "how is my battery").text
    assert ask(a, "what is 12 plus 7").text == "12 plus 7 is 19."
    assert ask(a, "what is 7 divided by 2").text == "7 divided by 2 is 3.5."
    assert ask(a, "10 divided by 0").intent == "math"
    assert ask(a, "hello there").intent == "greeting"


def test_online_questions_are_honest(tmp_path):
    r = ask(RuleAgent(tmp_path / "n.jsonl"), "What is the current petrol price?")
    assert r.intent == "needs_online" and "cannot look things up" in r.text


def test_notes_roundtrip(tmp_path):
    a = RuleAgent(tmp_path / "n.jsonl")
    assert ask(a, "note buy milk").text == "Noted: buy milk."
    ask(a, "remember that the wifi code is on the fridge")
    out = ask(a, "read my notes").text
    assert "buy milk" in out and "wifi code" in out


def test_empty_and_fallback(tmp_path):
    a = RuleAgent(tmp_path / "n.jsonl")
    assert ask(a, "").intent == "empty"
    assert ask(a, "banana telephone").intent == "fallback"
    assert ask(a, "what is the battery", {"now": CTX["now"], "battery": None}).text.startswith("I cannot see")
