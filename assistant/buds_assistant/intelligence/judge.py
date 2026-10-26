"""Autopilot's judgement. With Autopilot on, a small local model follows the conversation and decides, after each thought, whether
there is something genuinely useful to whisper: a question it can answer, a fact the user is reaching for, something they say they
need to look up, a clash with their calendar, a relevant memory. Prefer silence: a whisper that is not clearly useful is worse than none.

Runs off the audio thread, coalesces bursts of segments into one judgement, never talks over speech, never repeats itself."""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime

from buds_assistant.intelligence import voice_lines
from buds_assistant.intelligence.llm import LLMError

SYSTEM = (
    "You are Sidekick, a quiet assistant whispering in the user's ear while they talk with people. You hear the conversation. "
    "Lines starting with 'Me:' are the user. Decide whether there is something genuinely useful to whisper RIGHT NOW.\n"
    "Useful: answering a question that was just asked and you can answer; a fact the user is reaching for; something the user says they "
    "need to look up, search or check (give the quick answer if you know it, otherwise offer it as a to-do); a clash with their calendar; "
    "a relevant earlier memory; a task they commit to.\n"
    "Not useful: greetings, small talk, opinions, things already said, anything obvious, repeating an earlier whisper, guessing.\n"
    "Prefer silence. If you speak: one polite sentence of at most 18 words, addressed to the user.\n"
    'Reply with JSON only: {"say": "<what to whisper, or empty>", "todo": "<a short task to add to their to-do list, or empty>", '
    '"score": <1-5, how useful this is to the user right now>}')

# per sensitivity: (minimum score, minimum seconds between judged whispers, whispers per hour)
LEVELS = {"balanced": (4, 25.0, 12), "proactive": (3, 10.0, 30)}


def parse_verdict(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    try:
        score = int(float(d.get("score", 0)))
    except (TypeError, ValueError):
        score = 0
    return {"say": str(d.get("say") or "").strip(), "todo": str(d.get("todo") or "").strip(), "score": max(0, min(5, score))}


def _words(t: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", t.lower()))


class Judge:
    def __init__(self, cfg, llm, personal, memory, policy, emit, speaking=lambda: False, debounce: float = 1.5) -> None:
        self.cfg, self.llm, self.personal, self.memory, self.policy, self.emit = cfg, llm, personal, memory, policy, emit
        self.speaking, self.debounce = speaking, debounce
        self.window: list[dict] = []
        self._seen = 0                                   # window entries already judged
        self.said: list[tuple[float, str]] = []
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._busy = threading.Lock()

    # ---- input ---------------------------------------------------------------------------------------------
    @property
    def level(self) -> tuple[int, float, int] | None:
        return LEVELS.get(self.cfg.autopilot_sensitivity) if self.policy.enabled and "judge" in self.policy.categories() else None

    def add_turn(self, e: dict) -> None:
        who = "Me" if e.get("is_self") or e.get("speaker") == getattr(self.cfg, "self_name", "Me") else (e.get("speaker") or "Someone")
        with self._lock:
            self.window.append({"who": who, "text": (e.get("text") or "").strip(), "ts": e.get("t1") or time.time()})
            self._seen = max(0, self._seen - max(0, len(self.window) - 40))
            del self.window[:-40]

    def on_turn(self, e: dict) -> None:
        """From the audio pipeline for every spoken line: remember it and judge once the speaker pauses."""
        if self.speaking() or not (e.get("text") or "").strip():
            return                                       # our own voice coming back through the mic, or nothing
        self.add_turn(e)
        if self.level:
            self.start_timer()

    def start_timer(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        if not self._busy.acquire(blocking=False):
            return
        try:
            h = self.evaluate(time.time())
            if h:
                self.emit(h)
        except Exception:  # noqa: BLE001  judgement must never break listening
            pass
        finally:
            self._busy.release()

    # ---- the judgement ----------------------------------------------------------------------------------------
    def _log_quiet(self, reason: str) -> None:
        """Silences are stored (so they can be explained) but not pushed to the live feed: most turns need no comment."""
        self.policy.store.log_decision("judge", "held_back", reason, "", None, self.policy.conv_id, None)

    def _prompt(self, now: float) -> list[dict]:
        with self._lock:
            turns = list(self.window[-self.cfg.judge_context_turns:])
        convo = "\n".join(f"{t['who']}: {t['text']}" for t in turns)
        last = turns[-1]["text"] if turns else ""
        mem = ""
        try:
            hits = [h for h in self.memory.retrieve(last, k=3) if h.score >= 0.35]
            mem = "\n".join(f"- {h.segment['speaker']}: {h.segment['text']}" for h in hits)
        except Exception:  # noqa: BLE001
            pass
        said = "\n".join(f"- {t}" for _, t in self.said[-3:])
        agenda = self.personal.agenda_text(datetime.fromtimestamp(now)) if self.personal else ""
        ctx = (f"Now: {datetime.fromtimestamp(now):%A %d %B, %H:%M}\n\n{agenda}\n\nRelevant earlier conversations:\n{mem or '- none'}\n\n"
               f"What you already whispered recently (do not repeat):\n{said or '- nothing'}\n\nConversation (newest last):\n{convo}")
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": ctx}]

    def evaluate(self, now: float):
        level = self.level
        if level is None or self.speaking():
            return None
        min_score, gap, per_hour = level
        with self._lock:
            new = self.window[self._seen:]
            self._seen = len(self.window)
        text = " ".join(t["text"] for t in new)
        if len(text.split()) < 4:
            return None                                  # "yeah okay": not worth waking the model
        self.said = [(t, s) for t, s in self.said if now - t < 3600]
        if self.said and now - self.said[-1][0] < gap:
            self._log_quiet("too_soon")
            return None
        if len(self.said) >= per_hour:
            self._log_quiet("hourly_budget")
            return None
        try:
            raw = self.llm.chat(self._prompt(now), model=getattr(self.cfg, "judge_model", None), max_tokens=110, temperature=0.2,
                                json_mode=True, timeout=12)
        except LLMError:
            self._log_quiet("model_busy")
            return None
        v = parse_verdict(raw)
        if v is None:
            self._log_quiet("no_confident_match")
            return None
        say, todo = v["say"], v["todo"]
        if not (say or todo):
            self._log_quiet("nothing_to_add")
            return None
        if v["score"] < min_score:
            self._log_quiet("low_value")
            return None
        if say and any(len(_words(say) & _words(old)) >= 0.6 * max(1, len(_words(say))) for _, old in self.said[-5:]):
            self._log_quiet("repeat")
            return None
        if todo and self.personal and any(len(_words(todo) & _words(t["text"])) >= 0.6 * max(1, len(_words(todo))) for t in self.personal.todos()):
            todo = ""                                    # you already have that on your list
            if not say:
                self._log_quiet("repeat")
                return None
        if todo and self.personal:
            self.personal.add_todo(todo, None, None, source="autopilot")
            if not say:
                say = voice_lines.todo_added(todo)
            elif todo.lower() not in say.lower():
                say = f"{say.rstrip('.')}. I've added it to your to-dos."
        h = self.policy.judge_hint(say, now)
        if h:
            self.said.append((now, say))
        return h
