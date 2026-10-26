"""The 'brain'. A rule-based dummy for now; the interface is what a real LLM agent will implement.

    respond(text, ctx) -> Reply(text)

ctx: {"battery": {"left": int, "right": int, "case": int} | None, "now": datetime}
"""
from __future__ import annotations

import json
import operator
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass
class Reply:
    text: str
    intent: str = "fallback"


class Agent(Protocol):
    def respond(self, text: str, ctx: dict) -> Reply: ...


_JOKES = ["Why did the earbud go to school? To get a little wired.",
          "I would tell you a Bluetooth joke, but I have trouble connecting with the audience.",
          "What do you call earbuds that never lose a signal? Well connected."]
_OPS = {"plus": operator.add, "minus": operator.sub, "times": operator.mul, "multiplied by": operator.mul,
        "divided by": operator.truediv, "over": operator.truediv}
_NUM = r"(-?\d+(?:\.\d+)?)"
_ONLINE = r"petrol|gas price|fuel|weather|news|stock|score|traffic|price of|search|look up|google|who won"


class RuleAgent:
    def __init__(self, notes_path: Path | None = None, rng: random.Random | None = None) -> None:
        self.notes_path = notes_path
        self.rng = rng or random.Random()

    # ---- helpers ----------------------------------------------------------------
    def _notes(self) -> list[str]:
        if not self.notes_path or not self.notes_path.exists():
            return []
        return [json.loads(l)["text"] for l in self.notes_path.read_text().splitlines() if l.strip()]

    def _add_note(self, text: str) -> None:
        if self.notes_path:
            self.notes_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.notes_path, "a") as f:
                f.write(json.dumps({"ts": time.time(), "text": text}) + "\n")

    @staticmethod
    def _say_num(x: float) -> str:
        return str(int(x)) if float(x).is_integer() else f"{x:.2f}".rstrip("0")

    # ---- the rules ----------------------------------------------------------------
    def respond(self, text: str, ctx: dict) -> Reply:
        t = re.sub(r"[^\w\s.\-']", " ", text.lower()).strip()
        t = re.sub(r"\s+", " ", t)
        now: datetime = ctx.get("now") or datetime.now()
        if not t:
            return Reply("I did not hear anything.", "empty")
        if re.search(r"\b(note|remember)\b( that)? (.+)", t) and not re.search(r"\b(read|what are|my notes)\b", t):
            body = re.search(r"\b(?:note|remember)\b(?: that)? (.+)", t).group(1)
            self._add_note(body)
            return Reply(f"Noted: {body}.", "note")
        if re.search(r"\b(read|what are|list)\b.*\bnotes?\b", t):
            n = self._notes()[-3:]
            return Reply("You have no notes yet." if not n else "Your latest notes: " + ". ".join(n) + ".", "notes")
        if re.search(r"\bwhat('?s| is)? the time\b|\bwhat time is it\b|\bcurrent time\b|^time$", t):
            return Reply("It is " + now.strftime("%I:%M %p").lstrip("0") + ".", "time")
        if re.search(r"\b(what('?s| is)? (the )?(date|day)|what day is it|today'?s date)\b", t):
            return Reply("Today is " + now.strftime("%A, %B %d").replace(" 0", " ") + ".", "date")
        if "battery" in t:
            b = ctx.get("battery")
            if not b:
                return Reply("I cannot see the battery level right now.", "battery")
            return Reply(f"Left {b['left']} percent, right {b['right']} percent, case {b['case']} percent.", "battery")
        m = re.search(rf"{_NUM}\s+(plus|minus|times|multiplied by|divided by|over)\s+{_NUM}", t)
        if m:
            a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
            if op in ("divided by", "over") and b == 0:
                return Reply("I cannot divide by zero.", "math")
            return Reply(f"{self._say_num(a)} {op} {self._say_num(b)} is {self._say_num(_OPS[op](a, b))}.", "math")
        if re.search(r"\b(joke|funny)\b", t):
            return Reply(self.rng.choice(_JOKES), "joke")
        if re.search(r"\b(hello|hi|hey|good (morning|afternoon|evening))\b", t):
            return Reply("Hello! How can I help?", "greeting")
        if re.search(r"\b(thanks|thank you)\b", t):
            return Reply("You are welcome.", "thanks")
        if re.search(rf"\b({_ONLINE})\b", t):
            return Reply("You asked: " + text.strip().rstrip("?.") + ". I cannot look things up online yet. "
                         "This is a simple rule based assistant; a real model will answer that later.", "needs_online")
        return Reply(f"I heard: {text.strip()}. I do not know how to help with that yet.", "fallback")
