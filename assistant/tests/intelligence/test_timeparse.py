from datetime import datetime

import pytest

from buds_assistant.intelligence.timeparse import parse_when

NOW = datetime(2026, 10, 7, 11, 0)            # a Wednesday


@pytest.mark.parametrize("text,date,hm", [
    ("Friday at 3", (2026, 10, 9), (15, 0)),
    ("tomorrow at 10 am", (2026, 10, 8), (10, 0)),
    ("at 3:30 pm tomorrow", (2026, 10, 8), (15, 30)),
    ("let's do Thursday at 2", (2026, 10, 8), (14, 0)),
    ("next Monday", (2026, 10, 12), None),
    ("by Friday", (2026, 10, 9), None),
    ("Wednesday", (2026, 10, 7), None),
    ("today", (2026, 10, 7), None),
    ("tomorrow at noon", (2026, 10, 8), (12, 0)),
    ("in 2 hours", (2026, 10, 7), (13, 0)),
    ("in 30 minutes", (2026, 10, 7), (11, 30)),
    ("at 9 tomorrow", (2026, 10, 8), (9, 0)),
])
def test_parses_day_and_time(text, date, hm):
    w = parse_when(text, NOW)
    assert w and (w.date.year, w.date.month, w.date.day) == date
    assert (w.time and (w.time.hour, w.time.minute)) == (hm or None) if hm else w.time is None


def test_parts_of_the_day_give_a_window():
    w = parse_when("tomorrow afternoon", NOW)
    s, e = w.window()
    assert (s.hour, e.hour) == (12, 17) and s.day == 8


def test_a_whole_day_window_and_a_one_hour_slot():
    s, e = parse_when("Friday", NOW).window()
    assert (s.hour, e.hour) == (7, 22)
    s, e = parse_when("Friday at 3 pm", NOW).window()
    assert (s.hour, s.minute, e.hour) == (15, 0, 16)


@pytest.mark.parametrize("text", ["I like it", "see you around", "what is the plan", "three apples", "take 5 minutes to think"])
def test_returns_none_when_there_is_no_time(text):
    assert parse_when(text, NOW) is None


def test_label_reads_naturally():
    assert parse_when("tomorrow at 3 pm", NOW).label == "tomorrow at 3 pm"
    assert parse_when("Friday", NOW).label == "Friday"
    assert parse_when("in 2 hours", NOW).label == "at 1 pm"
