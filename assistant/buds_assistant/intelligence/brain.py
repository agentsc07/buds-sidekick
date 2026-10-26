"""The brain: rules for deterministic things, retrieval-grounded LLM answers for the rest.

Never invents quotes: answers about people are built only from retrieved segments of THAT person, and an unsure
model must say it does not know. Falls back to the rule agent (with an honest message) when the LLM is down."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from buds_assistant.intelligence.agent import RuleAgent
from buds_assistant.intelligence import voice_lines
from buds_assistant.intelligence.llm import LLMError
from datetime import timedelta

from buds_assistant.intelligence.timeparse import parse_when, strip_when
from buds_assistant.speech.translate import NAMES, Translator, detect_lang

SYSTEM = ("You are a discreet assistant whispering in the user's ear. Answer in one or two short spoken sentences, "
          "plain words, no lists or markdown, and do not add commentary about what was not said. Use ONLY the memory excerpts and conversation shown. If they do not "
          "contain the answer, say you do not have that. Attribute statements to the person named in the excerpt. "
          "Never invent facts, names or quotes. In the conversation, 'Me' is the user and 'Sidekick' is you, the assistant: lines from Sidekick are "
          "your own earlier whispers and answers, not another person.")


@dataclass
class Reply:
    text: str
    lang: str = "en"
    intent: str = "fallback"
    sources: list[int] = field(default_factory=list)
    action: str | None = None            # a command for the ModeController: replay, mark, private, stop, ...


def spoken_trim(text: str, max_sentences: int = 3) -> str:
    text = re.sub(r"[*_#`>]+", "", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(parts[:max_sentences]).strip()


def ago(ts: float, now: float | None = None) -> str:
    d = (now or time.time()) - ts
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} minutes ago"
    if d < 86400:
        return f"{int(d // 3600)} hours ago"
    return f"{int(d // 86400)} days ago"


_COMMANDS = [
    (r"\b(replay|play that again|say that again|what did (he|she|they) just say)\b", "replay"),
    (r"\b(mark (this|that)|bookmark)\b", "mark"),
    (r"\b(private mode|stop listening|go private)\b", "private"),
    (r"\b(start|begin) (a )?(conversation|listening)\b", "conversation_on"),
    (r"\b(end|stop) (the )?conversation\b", "conversation_off"),
    (r"\bauto(?:pilot)?(?: mode)? (on|off)\b", "auto"),
    (r"^(stop|cancel|quiet|shut up)\b", "stop"),
]


class Brain:
    def __init__(self, memory, translator: Translator, llm, rules: RuleAgent, store, deep_model: str | None = None, personal=None) -> None:
        self.memory, self.translator, self.llm, self.rules, self.store = memory, translator, llm, rules, store
        self.personal = personal                             # your calendar, reminders and to-dos
        self.deep_model = deep_model

    # ---- helpers -----------------------------------------------------------------------------
    def _person_in(self, text: str) -> dict | None:
        for p in sorted(self.store.people(), key=lambda p: -len(p["name"])):
            if re.search(rf"\b{re.escape(p['name'].lower())}('s)?\b", text.lower()):
                return p
        return None

    def _llm_ok(self) -> bool:
        return self.llm is not None and self.llm.available()

    def _rag(self, query: str, ctx: dict, person: dict | None, hits) -> Reply:
        excerpts = "\n".join(f"[{h.segment['speaker']}, {ago(h.segment['t1'])}] {h.segment['text']}" for h in hits)
        window = "\n".join(f"{w['speaker']}: {w['text']}" for w in ctx.get("window", [])[-10:])
        agenda = f"Your agenda:\n{self.personal.agenda_text(ctx['now'])}\n\n" if self.personal else ""
        content = (f"Memory excerpts:\n{excerpts or '(none)'}\n\nCurrent conversation:\n{window or '(none)'}\n\n{agenda}"
                   f"Question: {query}")
        try:
            out = self.llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
                                model=self.deep_model if ctx.get("deep") else None, max_tokens=140, timeout=25)
        except LLMError:
            return self._offline(query, ctx)
        return Reply(spoken_trim(out, 1) or "I do not have that.", "en", "rag", [h.segment["id"] for h in hits])

    def _offline(self, query: str, ctx: dict) -> Reply:
        r = self.rules.respond(query, ctx)
        note = "" if r.intent not in ("fallback", "needs_online") else " My language model is offline right now."
        return Reply(r.text + note, "en", "offline_" + r.intent)

    # ---- main entry --------------------------------------------------------------------------------
    def respond(self, query: str, ctx: dict | None = None) -> Reply:
        ctx = ctx or {}
        ctx.setdefault("now", datetime.now())
        q = re.sub(r"\s+", " ", query.strip())
        low = q.lower().rstrip("?.! ")
        if not low:
            return Reply("I did not hear anything.", intent="empty")
        for pat, action in _COMMANDS:
            if re.search(pat, low):
                return Reply({"replay": "Replaying.", "mark": "Marked.", "private": "Private mode.",
                              "conversation_on": "Conversation mode on.", "conversation_off": "Conversation mode off.",
                              "auto": "Auto mode " + ("on." if " on" in low else "off."),
                              "stop": ""}[action], intent="command",
                             action=action + (":on" if action == "auto" and " on" in low else ":off" if action == "auto" else ""))
        m = re.search(r"\b(who('s| is) (talking|speaking|this|that)|who am i (talking|speaking) (to|with))\b", low)
        if m:
            sp = ctx.get("speaker")
            if sp and sp.get("name"):
                return Reply(sp["name"] + ".", intent="who")
            if sp and sp.get("cluster"):
                return Reply(f"I do not recognise this voice. I am calling them {sp['cluster']}.", intent="who")
            return Reply("I cannot tell who is speaking right now.", intent="who")
        pr = self._personal(q, low, ctx)
        if pr:
            return pr
        t = re.search(r"\b(translate|say|how do you say)\b(.*?)\b(in|to|into) (telugu|english)\b[:,]? ?(.*)", q, re.I)
        t2 = re.search(r"^translate( that| this| it)?( to| into)? ?(telugu|english)?$", low)
        if t or t2:
            return self._translate(q, t, t2, ctx)
        if re.search(r"\bcatch me up|summari[sz]e (the )?(last|conversation)|what did i miss\b", low):
            return self._catch_up(ctx)
        person = self._person_in(low)
        if re.search(r"\b(what do i know about|tell me about|brief me on|who is)\b", low) and person:
            return self._dossier(person)
        if re.search(r"\b(promise|promised|owe|owes|commitments?|follow ?ups?|pending)\b", low):
            return self._commitments(person, low)
        if not self._llm_ok():
            return self._offline(q, ctx)
        rr = self.rules.respond(q, ctx)
        if rr.intent not in ("fallback", "needs_online"):                 # deterministic rules win (time, notes, math...)
            return Reply(rr.text, "en", rr.intent)
        hits = self.memory.retrieve(q, person_id=person["id"] if person else None, k=6)
        return self._rag(q, ctx, person, hits)

    # ---- your own data ---------------------------------------------------------------------------------------
    def _personal(self, q: str, low: str, ctx: dict) -> Reply | None:
        pe = self.personal
        if pe is None:
            return None
        now = ctx["now"]
        R = lambda text, intent: Reply(text, "en", intent)                                                    # noqa: E731
        orig = q.rstrip("?.! ")                                                                              # keeps the capitals in names
        m = re.match(r"^(?:please )?(?:add|put) (.+?) (?:to|on|onto) my (?:to-?do|task)s?(?: list)?$", orig, re.I) or re.match(r"^(?:to-?do|task)[: ]+(.+)$", orig, re.I)
        if m:
            text = m.group(1).strip()
            w = parse_when(text, now)
            pe.add_todo(strip_when(text) if w else text, w.label if w else None, w.start.timestamp() if w else None, source="ask")
            return R(voice_lines.todo_added(strip_when(text) if w else text), "todo_add")
        m = re.match(r"^(?:please )?remind me (?:to |about |that )?(.+)$", orig, re.I)
        if m:
            text = m.group(1).strip()
            w = parse_when(text, now)
            due = w.start if w and w.time else (w.window()[0].replace(hour=9) if w else now + timedelta(hours=1))
            label = w.label if w else "in an hour"
            body = strip_when(text) if w else text
            pe.add_reminder(body, due.timestamp())
            return R(f"I'll remind you to {body} {label}.", "reminder_add")
        m = re.match(r"^(?:please )?(?:schedule|book|add) (?:a |an )?(?:meeting |event |appointment )?(.+)$", orig, re.I)
        if m and parse_when(m.group(1), now) and not re.search(r"\b(todo|to-do|task)\b", low):
            w = parse_when(m.group(1), now)
            title = strip_when(m.group(1)) or "Event"
            start = w.start.timestamp()
            clash = pe.conflicts(start, start + 3600) if w.time else []
            pe.add_event(title, start, None, [p["name"] for p in self.store.people() if p["name"].lower() in title.lower()])
            if clash:
                return R(f"Added {title} {w.label}, but you already have {clash[0]['title']} then.", "event_add")
            return R(f"Added {title} {w.label}.", "event_add")
        if re.search(r"\b(am i|are we) (free|available|busy)\b|\bdo i have anything\b", low):
            ans = pe.answer_availability(low, now)
            if ans:
                return R(ans, "availability")
        if re.search(r"\b(next|upcoming) (meeting|event|appointment)\b|what'?s next\b", low):
            e = pe.next_event(now.timestamp())
            return R(pe.describe(e, now) + "." if e else "You have nothing coming up.", "next_event")
        if re.search(r"\b(calendar|schedule|agenda)\b|what do i have (today|tomorrow|on |this )", low) and re.search(r"\bwhat|show|read|tell|any\b", low):
            w = parse_when(low, now)
            from datetime import datetime as _dt
            a, b = (w.window() if w else (_dt.combine(now.date(), _dt.min.time()).replace(hour=0), _dt.combine(now.date(), _dt.min.time()).replace(hour=23, minute=59)))
            if w and w.time is None and not w.part:
                a = a.replace(hour=0)
            evs = pe.events_between(a.timestamp(), b.timestamp())
            label = w.label if w else "today"
            if not evs:
                return R(f"Nothing on your calendar {label}.", "calendar")
            from buds_assistant.intelligence.personal import hm
            return R(f"{label.capitalize()} you have " + ", ".join(f"{e['title']} at {hm(e['start'])}" for e in evs[:4]) + ".", "calendar")
        if re.search(r"\b(to-?dos?|tasks?)\b|what do i have to do|what do i need to do", low) and re.search(r"\bwhat|show|read|list|my\b", low):
            todos = pe.todos()
            if not todos:
                return R("Your to-do list is empty.", "todo_list")
            return R("To do: " + "; ".join(t["text"] + (f", {t['due_text']}" if t["due_text"] else "") for t in todos[:4]) + ".", "todo_list")
        if re.search(r"\breminders?\b", low) and re.search(r"\bwhat|show|read|list|my\b", low):
            rs = pe.reminders()
            from buds_assistant.intelligence.personal import hm, day_label
            return R("Reminders: " + "; ".join(f"{r['text']} {day_label(r['due'], now)} at {hm(r['due'])}" for r in rs[:4]) + "." if rs else "You have no reminders.", "reminders")
        return None

    # ---- intents ---------------------------------------------------------------------------------------
    def _translate(self, q: str, m, m2, ctx: dict) -> Reply:
        if m:
            body, dst = m.group(5).strip() or m.group(2).strip(" :,"), "te" if m.group(4).lower() == "telugu" else "en"
        else:
            dst = {"telugu": "te", "english": "en"}.get((m2.group(3) or "").lower())
            body = ctx.get("last_text", "")
            dst = dst or ("en" if detect_lang(body) == "te" else "te")
        if not body:
            return Reply("There is nothing to translate yet.", intent="translate")
        r = self.translator.translate(body, "auto", dst)
        if not r.ok:
            return Reply(f"I could not translate that: {r.error}.", intent="translate")
        return Reply(r.text, r.dst, "translate")

    def _catch_up(self, ctx: dict) -> Reply:
        win = ctx.get("window", [])[-30:]
        if not win:
            return Reply("There is nothing to catch up on yet.", intent="catch_up")
        text = "\n".join(f"{w['speaker']}: {w['text']}" for w in win)
        if self._llm_ok():
            try:
                out = self.llm.chat([{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": f"Summarise what was just said in two sentences. 'Me' is the user. Sidekick is you, the assistant, not another person: "
                                                                  f"its lines are your own earlier whispers and answers.\n\n{text}"}],
                                    max_tokens=100, timeout=25)
                return Reply(spoken_trim(out, 2), intent="catch_up")
            except LLMError:
                pass
        return Reply("Last said: " + " ".join(f"{w['speaker']} said {w['text']}." for w in win[-3:]), intent="catch_up")

    def _dossier(self, person: dict) -> Reply:
        d = self.memory.dossier(person["id"])
        if not d.get("segments") and not d.get("facts"):
            return Reply(f"I have nothing stored about {person['name']} yet.", intent="dossier")
        bits = [f"{person['name']}: {d['segments']} things said"]
        if d["topics"]:
            bits.append("topics " + ", ".join(d["topics"][:4]))
        open_c = [f for f in d["facts"] if f["kind"] == "commitment" and f["status"] == "open"]
        if open_c:
            bits.append("open: " + "; ".join(f"{f['text']}" + (f" by {f['due']}" if f["due"] else "") for f in open_c[:2]))
        return Reply(". ".join(bits) + ".", intent="dossier", sources=[f["source_segment"] for f in open_c[:2] if f["source_segment"]])

    def _commitments(self, person: dict | None, low: str) -> Reply:
        rows = self.memory.commitments(person["id"] if person else None)
        if not rows:
            return Reply("I have no open commitments" + (f" for {person['name']}." if person else "."), intent="commitments")
        parts = [f"{r['person'] or 'someone'}: {r['text']}" + (f", due {r['due']}" if r["due"] else "") for r in rows[:4]]
        return Reply(spoken_trim(". ".join(parts) + ".", 4), intent="commitments",
                     sources=[r["source_segment"] for r in rows[:4] if r["source_segment"]])
