"""Autopilot: decides WHEN a whisper is worth it, and records every decision (said / noted / held back + why).

Triggers: capture (A3, your own promises), question (A2), commitment (A4), mention (A5), identity (A1).
Gating: never for unknown voices, never right after you spoke, min gap, hourly budget, dismissals, sensitivity.
Silence is explainable: every candidate that does not become a whisper is logged with a reason."""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

from datetime import datetime

from buds_assistant.intelligence import voice_lines
from buds_assistant.intelligence.commitments import detect
from buds_assistant.intelligence.timeparse import parse_when
from buds_assistant.intelligence.memory import _words
from buds_assistant.intelligence.personal import day_label, hm

QUESTION = re.compile(r"\?\s*$|^(what|when|where|who|why|how|can you|could you|will you|would you|do you|did you|are you|have you)\b",
                      re.I)

REASONS = {"too_soon": "Skipped: too soon after the last whisper", "you_were_speaking": "Held back: someone was still speaking",
           "stale": "Dropped: the moment had passed", "unknown_voice": "Skipped: I don't know this voice",
           "category_off": "Skipped: this type of hint is switched off", "autopilot_off": "Autopilot was off",
           "hourly_budget": "Skipped: hourly limit reached", "recently_dismissed": "Skipped: you dismissed this kind recently",
           "no_confident_match": "Skipped: no confident answer", "mode_changed": "Dropped: the mode changed",
           "unsure_voice": "Skipped: I wasn't sure it was you", "nothing_to_add": "Quiet: nothing useful to add", "low_value": "Quiet: not useful enough to interrupt",
           "repeat": "Skipped: I already said that", "model_busy": "Skipped: the language model was busy"}

SENS = {"quiet": {"capture", "question", "reminder"},
        "balanced": {"capture", "question", "reminder", "identity", "commitment", "calendar", "meeting", "judge"},
        "proactive": {"capture", "question", "reminder", "identity", "commitment", "calendar", "meeting", "mention", "judge"}}      # A6/A7 are "Later"
PROPOSE = re.compile(r"\b(let'?s|how about|what about|i can (do|make|meet)|i'?m (free|available)|works for me|can we|shall we|we could|"
                    r"are you (free|available|around)|do you have time|free (on|at|tomorrow|today)|available)\b", re.I)


@dataclass
class Hint:
    text: str
    trigger: str
    person_id: int | None
    sources: list[int] = field(default_factory=list)
    id: int | None = None
    kind: str = "said"                     # said | noted
    ts: float = 0.0
    fact_id: int | None = None
    any_mode: bool = False                 # reminders you set yourself play in any mode except Private


def clip_words(text: str, n: int) -> str:
    w = text.split()
    return text if len(w) <= n else " ".join(w[:n]).rstrip(",;:") + "."


class AutopilotEngine:
    def __init__(self, cfg, store, memory, events=None, personal=None) -> None:
        self.cfg, self.store, self.memory, self.events, self.personal = cfg, store, memory, events, personal
        self.enabled = False
        self.conv_id: int | None = None
        self.last_hint = 0.0
        self.hour: deque[float] = deque()
        self.last_cue: dict[int, float] = {}
        self.last_mention: dict[int, float] = {}
        self.last_spoke: dict[int, float] = {}
        self.user_last = 0.0
        self.rate_factor = 1.0
        self.dismiss_streak = 0
        self.muted: dict[str, float] = {}

    # ---- decisions -----------------------------------------------------------------------------
    def categories(self) -> set[str]:
        return set(self.cfg.autopilot_categories) if self.cfg.autopilot_categories else SENS.get(self.cfg.autopilot_sensitivity, SENS["balanced"])

    def _decide(self, trigger: str, outcome: str, reason: str | None, text: str, pid: int | None, hint_id: int | None = None,
                fact_id: int | None = None) -> None:
        self.store.log_decision(trigger, outcome, reason, text, pid, self.conv_id, hint_id, fact_id)
        if self.events:
            self.events.publish("autopilot_decision", trigger=trigger, outcome=outcome, reason=reason, text=text,
                                reason_text=REASONS.get(reason), person_id=pid, hint_id=hint_id, fact_id=fact_id, conv_id=self.conv_id)

    def _gate(self, trigger: str, now: float, capture: bool = False, own: bool = False) -> str | None:
        while self.hour and now - self.hour[0] > 3600:
            self.hour.popleft()
        if trigger not in self.categories():
            return "category_off"
        if now < self.muted.get(trigger, 0):
            return "recently_dismissed"
        if not (capture or own) and now - self.user_last <= 1.5:      # own = triggered by your own sentence
            return "you_were_speaking"
        if not capture and now - self.last_hint < self.cfg.hint_min_gap * self.rate_factor:
            return "too_soon"
        if len(self.hour) >= self.cfg.hints_per_hour / self.rate_factor:
            return "hourly_budget"
        return None

    def _try(self, trigger: str, now: float, pid: int | None, build, capture: bool = False, own: bool = False) -> Hint | None:
        """A candidate exists. Gate it, build the hint, emit and log; every non-whisper outcome is logged with a reason."""
        if not self.enabled:
            return None                                       # Autopilot is off (plain Listen): not a decision worth showing
        reason = self._gate(trigger, now, capture, own)
        if reason:
            self._decide(trigger, "held_back", reason, "", pid)
            return None
        h = build()
        if h is None:
            self._decide(trigger, "held_back", "no_confident_match", "", pid)
            return None
        h.text = clip_words(h.text, self.cfg.hint_max_words)
        h.ts = now
        self.last_hint = now
        self.hour.append(now)
        h.id = self.store.log_hint(h.trigger, h.text, h.person_id, True, h.sources)
        self._decide(trigger, h.kind, None, h.text, pid, h.id, h.fact_id)
        return h

    # ---- main --------------------------------------------------------------------------------------
    def on_segment(self, e: dict, now: float | None = None) -> Hint | None:
        now = now or time.time()
        text = (e.get("text") or "").strip()
        if e.get("inherited"):
            return None                                       # the speaker was guessed from the previous turn: never act on a guess
        if e.get("is_self"):
            self.user_last = now
            return self._on_self(e, text, now)
        if e.get("speaker") == getattr(self.cfg, "self_name", "Me"):
            if self.enabled and "capture" in self.categories() and detect(text):
                self._decide("capture", "held_back", "unsure_voice", "", e.get("person_id"))
            return None                                       # probably you, just not confident enough: stay quiet
        pid = e.get("person_id")
        if not text:
            return None
        if pid is None:
            if QUESTION.search(text) and self.enabled:        # a candidate, but we never whisper about unknown voices
                self._decide("question", "held_back", "unknown_voice", "", None)
            return None
        first_turn = now - self.last_spoke.get(pid, 0) > 60
        self.last_spoke[pid] = now
        name = e["speaker"]

        # a time is being arranged: answer from your calendar
        h = self._calendar(text, now, pid, own=False)
        if h:
            return h

        # A2 a question that memory or your calendar can answer
        if QUESTION.search(text):
            def build_q():
                if self.personal:
                    ans = self.personal.search(text, datetime.fromtimestamp(now))
                    if ans:
                        return Hint(ans, "question", pid)
                hits = [h for h in self.memory.retrieve(text, k=3) if h.segment["id"] != e.get("seg_id")]
                if hits and hits[0].score >= 0.35:
                    s = hits[0].segment
                    return Hint(f"{name} asked. Earlier {s['speaker']} said: {s['text']}", "question", pid, [s["id"]])
                return None
            h = self._try("question", now, pid, build_q)
            if h:
                return h

        # A4 a stored commitment of this person is mentioned
        tw = _words(text)
        for f in self.store.facts(person_id=pid, kind="commitment", status="open"):
            fw = _words(f["text"])
            if fw and len(tw & fw) >= max(1, min(2, len(fw))):
                h = self._try("commitment", now, pid, lambda f=f: Hint(
                    f"Reminder: {name} said they would {f['text']}" + (f" by {f['due']}." if f["due"] else "."),
                    "commitment", pid, [f["source_segment"]] if f["source_segment"] else []))
                if h:
                    return h
                break

        h = self._mention(e, text, now)
        if h:
            return h

        # A1 a known voice starts a new turn (once per person per window)
        if first_turn and now - self.last_cue.get(pid, 0) > self.cfg.identity_cue_gap:
            def build_i():
                open_c = self.store.facts(person_id=pid, kind="commitment", status="open")
                extra = (f" Open: {open_c[0]['text']}" + (f" by {open_c[0]['due']}." if open_c[0]["due"] else ".")) if open_c else ""
                if self.personal:
                    nd = datetime.fromtimestamp(now)
                    meet = [e for e in self.personal.events_between(now, now + 36 * 3600) if name in e["people"] or name.lower() in e["title"].lower()]
                    todo = [t for t in self.personal.todos() if name.lower() in t["text"].lower()]
                    if meet:
                        extra += f" You meet {day_label(meet[0]['start'], nd)} at {hm(meet[0]['start'])}."
                    if todo:
                        extra += f" To do: {todo[0]['text']}."
                srcs = [open_c[0]["source_segment"]] if open_c and open_c[0]["source_segment"] else []
                self.last_cue[pid] = now
                return Hint(f"{name}.{extra}", "identity", pid, srcs)
            return self._try("identity", now, pid, build_i)
        return None

    def _on_self(self, e: dict, text: str, now: float) -> Hint | None:
        c = detect(text) if self.enabled and "capture" in self.categories() else None     # A3 your own promise: needs no history
        if c:
            me = self.store.person_by_name(getattr(self.cfg, "self_name", "Me"))
            fid = None
            if me and me["policy"] != "none":                 # the promise is saved whether or not the whisper is allowed
                fid = self.store.add_fact(me["id"], "commitment", c.text, c.due, e.get("seg_id"), owner=me["name"])
            clash, added = None, False
            if self.personal and fid:
                nd = datetime.fromtimestamp(now)
                w = parse_when(text, nd)
                due = None
                if w:
                    due = (w.start if w.time else w.window()[1].replace(hour=17)).timestamp()
                    if w.time and (found := self.personal.conflicts(*(x.timestamp() for x in w.window()))):
                        clash = found[0]["title"]
                self.personal.add_todo(c.text, c.due, due, source="promise", fact_id=fid)
                added = True
            h = self._try("capture", now, me["id"] if me else None, lambda: Hint(
                voice_lines.promise_noted(c.text, c.due, added, clash), "capture", me["id"] if me else None, kind="noted", fact_id=fid),
                capture=True)
            if h:
                return h
        h = self._calendar(text, now, e.get("person_id"), own=True)
        if h:
            return h
        return self._mention(e, text, now, own=True)

    def _calendar(self, text: str, now: float, pid, own: bool) -> Hint | None:
        """Someone (or you) is arranging a time: say whether you are free."""
        if not self.personal or not PROPOSE.search(text):
            return None
        ans = self.personal.answer_availability(text, datetime.fromtimestamp(now))
        if not ans:
            return None
        return self._try("calendar", now, pid, lambda: Hint(ans, "calendar", pid), own=own)

    def judge_hint(self, text: str, now: float) -> Hint | None:
        """A whisper the language model decided on after listening to the conversation (judge.py). Same gates and log as every other whisper."""
        me = self.store.person_by_name(getattr(self.cfg, "self_name", "Me"))
        return self._try("judge", now, me["id"] if me else None, lambda: Hint(text, "judge", me["id"] if me else None), own=True)

    def system_hint(self, trigger: str, text: str, now: float, any_mode: bool = False, pid=None) -> Hint | None:
        """A hint that comes from the clock, not from a sentence (meeting in 10 minutes, a reminder). Not rate-limited."""
        if not (self.enabled or any_mode):
            return None
        if trigger not in self.categories():
            self._decide(trigger, "held_back", "category_off", "", pid)
            return None
        h = Hint(clip_words(text, self.cfg.hint_max_words), trigger, pid, ts=now, any_mode=any_mode)
        h.id = self.store.log_hint(trigger, h.text, pid, True, [])
        self._decide(trigger, "said", None, h.text, pid, h.id)
        return h

    def _mention(self, e: dict, text: str, now: float, own: bool = False) -> Hint | None:
        """A5 a known person's name comes up: a one-line brief from what we know about them."""
        me_name = getattr(self.cfg, "self_name", "Me")
        for p in self.store.people():
            if p["name"] in (me_name, e.get("speaker")) or not re.search(rf"\b{re.escape(p['name'])}\b", text, re.I):
                continue
            if now - self.last_mention.get(p["id"], 0) <= self.cfg.identity_cue_gap:
                continue
            facts = [f for f in self.store.facts(person_id=p["id"]) if f["kind"] != "commitment"]
            if not facts:
                continue

            def build_m(p=p, facts=facts):
                self.last_mention[p["id"]] = now
                return Hint(f"{p['name']} {facts[0]['text']}", "mention", p["id"],
                            [facts[0]["source_segment"]] if facts[0]["source_segment"] else [])
            return self._try("mention", now, p["id"], build_m, own=own)
        return None

    # ---- feedback ----------------------------------------------------------------------------------------
    def feedback(self, hint_id: int, useful: bool, trigger: str | None = None, now: float | None = None) -> None:
        now = now or time.time()
        self.store.rate_hint(hint_id, useful)
        if useful:
            self.dismiss_streak = 0
            return
        self.dismiss_streak += 1
        if trigger:
            self.muted[trigger] = now + 600                 # dismissed: quiet that kind for 10 minutes
        if self.dismiss_streak >= 3:
            self.rate_factor = min(self.rate_factor * 2, 8.0)
            self.dismiss_streak = 0
