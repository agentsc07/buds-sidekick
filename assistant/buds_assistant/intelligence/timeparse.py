"""Small rule-based parser for 'Friday at 3', 'tomorrow afternoon', 'in 2 hours'. English only, no model, no network."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
PARTS = {"morning": (8, 12), "afternoon": (12, 17), "evening": (17, 22), "tonight": (18, 23)}
HOUR = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\bat\s+(\d{1,2})(?::(\d{2}))?\b", re.I)
REL = re.compile(r"\bin\s+(\d+|an?|half an)\s*(minutes?|mins?|hours?|hrs?)\b", re.I)


@dataclass
class When:
    date: date
    time: time | None = None
    part: str | None = None
    label: str = ""

    def window(self) -> tuple[datetime, datetime]:
        d = datetime.combine(self.date, time(0))
        if self.time is not None:
            s = datetime.combine(self.date, self.time)
            return s, s + timedelta(hours=1)
        if self.part:
            a, b = PARTS[self.part]
            return d.replace(hour=a), d.replace(hour=b)
        return d.replace(hour=7), d.replace(hour=22)

    @property
    def start(self) -> datetime:
        return self.window()[0]


def _fmt(t: time) -> str:
    h = t.hour % 12 or 12
    return f"{h}{':%02d' % t.minute if t.minute else ''} {'am' if t.hour < 12 else 'pm'}"


def parse_when(text: str, now: datetime) -> When | None:
    low = text.lower()
    m = REL.search(low)
    if m:
        n = {"a": 1, "an": 1, "half an": 0.5}.get(m.group(1), None) or float(m.group(1))
        unit = timedelta(minutes=n) if m.group(2).startswith(("min",)) else timedelta(hours=n)
        t = now + unit
        return When(t.date(), t.time().replace(second=0, microsecond=0), None, "at " + _fmt(t.time()))
    day, label_day = None, ""
    if re.search(r"\btomorrow\b", low):
        day, label_day = now.date() + timedelta(days=1), "tomorrow"
    elif re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", low):
        day, label_day = now.date(), "today"
    else:
        for i, name in enumerate(DAYS):
            if re.search(rf"\b{name}\b", low):
                day, label_day = now.date() + timedelta(days=(i - now.weekday()) % 7), name.capitalize()
                break
    part = next((p for p in PARTS if re.search(rf"\b{p}\b", low)), None)
    hm = None
    if re.search(r"\bnoon\b", low):
        hm = time(12, 0)
    else:
        h = HOUR.search(low)
        if h:
            hour, minute, ap = (h.group(1), h.group(2), h.group(3)) if h.group(1) else (h.group(4), h.group(5), None)
            hour, minute = int(hour), int(minute or 0)
            if 0 < hour <= 12 and 0 <= minute < 60:
                if ap:
                    hour = hour % 12 + (12 if ap == "pm" else 0)
                elif 1 <= hour <= 6:
                    hour += 12                                  # "at 3" in a meeting means the afternoon
                hm = time(hour % 24, minute)
    if day is None and hm is not None and part is None:
        day, label_day = now.date(), "today"                    # "at 3" alone: today
        if datetime.combine(day, hm) < now:
            day, label_day = day + timedelta(days=1), "tomorrow"
    if day is None:
        return None
    if part == "tonight":
        part = "evening"
    label = label_day + (f" at {_fmt(hm)}" if hm else (f" {part}" if part else ""))
    return When(day, hm, part if hm is None else None, label)


_WHEN_WORDS = re.compile(
    r"\b(?:by|on|for|at|in the|this|next)?\s*(?:tomorrow|today|tonight|noon|morning|afternoon|evening|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|"
    r"\bin\s+(?:\d+|an?|half an)\s*(?:minutes?|mins?|hours?|hrs?)\b", re.I)


def strip_when(text: str) -> str:
    """The text without its time words: 'call mum tomorrow at 9' -> 'call mum'."""
    return re.sub(r"\s+", " ", _WHEN_WORDS.sub(" ", text)).strip(" ,.-")
