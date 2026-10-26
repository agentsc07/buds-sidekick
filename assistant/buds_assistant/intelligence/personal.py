"""Your own data: calendar events, reminders, a to-do list. Local, editable, and (for now) seeded with clearly flagged sample data.

Autopilot and Ask read from here: availability when you are asked to meet, the next meeting, what you promised (as to-dos)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from buds_assistant.intelligence.timeparse import parse_when

STOP = {"when", "what", "where", "who", "the", "and", "for", "with", "have", "need", "did", "does", "are", "you", "that", "this", "about",
        "from", "your", "was", "were", "will", "going", "time", "meeting", "tell", "much", "many", "know", "get", "got"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4 and w not in STOP}


def hm(ts: float) -> str:
    t = datetime.fromtimestamp(ts)
    return f"{t.hour % 12 or 12}{':%02d' % t.minute if t.minute else ''} {'am' if t.hour < 12 else 'pm'}"


def day_label(ts: float, now: datetime) -> str:
    d = datetime.fromtimestamp(ts).date()
    delta = (d - now.date()).days
    return "today" if delta == 0 else "tomorrow" if delta == 1 else d.strftime("%A") if 0 < delta < 7 else d.strftime("%A %-d %B")


class Personal:
    def __init__(self, store) -> None:
        self.store = store

    # ---- events -------------------------------------------------------------------------------------------------
    def add_event(self, title: str, start: float, end: float | None = None, people=(), place: str = "", sample: bool = False) -> int:
        return self.store._x("INSERT INTO events(title, start, end, people, place, sample) VALUES(?,?,?,?,?,?)",
                             (title, start, end or start + 3600, json.dumps(list(people)), place, int(sample))).lastrowid

    def _ev(self, rows: list[dict]) -> list[dict]:
        for r in rows:
            r["people"] = json.loads(r["people"] or "[]")
        return rows

    def events_between(self, a: float, b: float) -> list[dict]:
        return self._ev(self.store.q("SELECT * FROM events WHERE start < ? AND end > ? ORDER BY start", (b, a)))

    def next_event(self, now: float) -> dict | None:
        r = self._ev(self.store.q("SELECT * FROM events WHERE end > ? ORDER BY start LIMIT 1", (now,)))
        return r[0] if r else None

    def delete_event(self, eid: int) -> None:
        self.store._x("DELETE FROM events WHERE id=?", (eid,))

    def conflicts(self, a: float, b: float) -> list[dict]:
        return self.events_between(a, b)

    def describe(self, e: dict, now: datetime) -> str:
        return f"{e['title']} {day_label(e['start'], now)} at {hm(e['start'])}"

    def upcoming_to_announce(self, now: float) -> list[tuple[dict, int]]:
        """Events starting in <=10 min (announce once) and <=2 min (once more)."""
        out = []
        for e in self._ev(self.store.q("SELECT * FROM events WHERE start > ? AND start <= ? ORDER BY start", (now, now + 600))):
            mins = (e["start"] - now) / 60
            if mins <= 2 and not e["announced"] & 2:
                self.store._x("UPDATE events SET announced = announced | 3 WHERE id=?", (e["id"],)); out.append((e, 2))
            elif mins <= 10 and not e["announced"] & 1:
                self.store._x("UPDATE events SET announced = announced | 1 WHERE id=?", (e["id"],)); out.append((e, 10))
        return out

    # ---- reminders ----------------------------------------------------------------------------------------------
    def add_reminder(self, text: str, due: float, sample: bool = False) -> int:
        return self.store._x("INSERT INTO reminders(text, due, sample) VALUES(?,?,?)", (text, due, int(sample))).lastrowid

    def reminders(self, status: str = "open") -> list[dict]:
        return self.store.q("SELECT * FROM reminders WHERE status=? ORDER BY due", (status,))

    def due_reminders(self, now: float) -> list[dict]:
        return self.store.q("SELECT * FROM reminders WHERE status='open' AND due <= ? ORDER BY due", (now,))

    def complete_reminder(self, rid: int) -> None:
        self.store._x("UPDATE reminders SET status='done' WHERE id=?", (rid,))

    # ---- to-dos -------------------------------------------------------------------------------------------------
    def add_todo(self, text: str, due_text: str | None = None, due: float | None = None, source: str = "manual",
                 fact_id: int | None = None, sample: bool = False) -> int:
        import time
        return self.store._x("INSERT INTO todos(text, due_text, due, source, fact_id, created, sample) VALUES(?,?,?,?,?,?,?)",
                             (text, due_text, due, source, fact_id, time.time(), int(sample))).lastrowid

    def todos(self, status: str = "open") -> list[dict]:
        return self.store.q("SELECT * FROM todos WHERE status=? ORDER BY COALESCE(due, 9e12), id", (status,))

    def complete_todo(self, tid: int) -> None:
        self.store._x("UPDATE todos SET status='done' WHERE id=?", (tid,))

    def reopen_todo(self, tid: int) -> None:
        self.store._x("UPDATE todos SET status='open' WHERE id=?", (tid,))

    def cancel_for_fact(self, fact_id: int) -> None:
        self.store._x("UPDATE todos SET status='cancelled' WHERE fact_id=?", (fact_id,))

    # ---- questions ----------------------------------------------------------------------------------------------
    def answer_availability(self, text: str, now: datetime) -> str | None:
        w = parse_when(text, now)
        if w is None:
            return None
        a, b = w.window()
        busy = self.conflicts(a.timestamp(), b.timestamp())
        if w.time is not None:
            if busy:
                return f"You have {busy[0]['title']} {w.label}."
            return f"You're free {w.label}."
        if not busy:
            return f"Your {w.label} is clear." if w.label[0].isupper() or w.label in ("today", "tomorrow") else f"You're free {w.label}."
        parts = [f"{e['title']} at {hm(e['start'])}" for e in busy[:3]]
        return f"On {w.label} you have " + ", ".join(parts) + "."

    def search(self, text: str, now: datetime) -> str | None:
        """Does this question mention something that is on your calendar, reminders or to-do list?"""
        q = _words(text)
        if not q:
            return None
        for e in self.events_between(now.timestamp() - 3600, now.timestamp() + 60 * 86400):
            if q & _words(e["title"]):
                return self.describe(e, now) + "."
        for t in self.todos():
            if q & _words(t["text"]):
                return f"To do: {t['text']}" + (f", {t['due_text']}" if t["due_text"] else "") + "."
        for r in self.reminders():
            if q & _words(r["text"]):
                return f"Reminder: {r['text']} at {hm(r['due'])}."
        return None

    def agenda_text(self, now: datetime) -> str:
        lines = []
        for e in self.events_between(now.timestamp(), now.timestamp() + 3 * 86400)[:6]:
            lines.append(f"- {self.describe(e, now)}" + (f" with {', '.join(e['people'])}" if e["people"] else ""))
        todos = self.todos()[:6]
        todo_lines = [f"- {t['text']}" + (f" ({t['due_text']})" if t["due_text"] else "") for t in todos]
        return "Calendar (next 3 days):\n" + ("\n".join(lines) or "- nothing") + "\nTo-do:\n" + ("\n".join(todo_lines) or "- nothing")

    # ---- sample data --------------------------------------------------------------------------------------------
    def seed_sample(self, now: datetime, force: bool = False) -> int:
        """Illustrative data so Autopilot has something to work with. Flagged as sample; seeded once; clearing is remembered
        (force=True is the user pressing 'load sample data')."""
        if not force and (any(a["kind"] in ("sample_seeded", "sample_cleared") for a in self.store.audit_log(1000))
                          or self.events_between(0, 9e12) or self.todos()):
            return 0
        day = lambda off, h, m=0: (now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=off)).timestamp()   # noqa: E731
        n = 0
        for title, off, h, m, people in (("Standup", 1, 10, 0, ["Ravi"]), ("Demo prep", 0, 16, 0, []), ("1:1 with Ravi", 2, 16, 0, ["Ravi"]),
                                         ("Budget review", 3, 14, 0, ["Priya"]), ("Dentist", 4, 9, 30, []), ("Team lunch", 4, 13, 0, [])):
            if day(off, h, m) > now.timestamp():
                self.add_event(title, day(off, h, m), None, people, sample=True); n += 1
        self.add_reminder("Call mum", now.timestamp() + 3 * 3600, sample=True)
        self.add_reminder("Take medicine", day(1, 8, 30), sample=True)
        self.add_todo("Review the Q3 report", "Friday", day(4, 17), sample=True)
        self.add_todo("Book the demo room", "tomorrow", day(1, 12), sample=True)
        self.add_todo("Reply to Priya about the budget", None, None, sample=True)
        self.store.audit("sample_seeded", {"events": n})
        return n + 5

    def has_sample(self) -> bool:
        return any(self.store.q(f"SELECT 1 FROM {t} WHERE sample=1 LIMIT 1") for t in ("events", "reminders", "todos"))

    def clear_sample(self) -> None:
        for t in ("events", "reminders", "todos"):
            self.store._x(f"DELETE FROM {t} WHERE sample=1")
        self.store.audit("sample_cleared", {})
