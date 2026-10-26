"""Rule-based commitment capture (A3): first-person promise + action verb, optional due phrase.

Needs no model and no stored history, so Autopilot has something useful to do on day one."""
from __future__ import annotations

import re
from dataclasses import dataclass

VERBS = "send|call|email|share|review|finish|finali[sz]e|check|schedule|book|prepare|update|follow up|bring|submit|forward|ping|text"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tonight|tomorrow"
PROMISE = re.compile(rf"(?<![\w'])(?:i(?:'ll| will| am going to|'m going to)|let me)\s+((?:{VERBS})\b[^,.?!]*)", re.I)
DUE = re.compile(rf"(?:\b(?:by|on|before|this|next|until)\s+)?\b({DAYS}|end of (?:the )?(?:day|week|month)|next week)\b", re.I)


@dataclass
class Commitment:
    text: str
    due: str | None


def detect(text: str) -> Commitment | None:
    if text.strip().endswith("?"):
        return None
    m = PROMISE.search(text)
    if not m:
        return None
    body = m.group(1).strip()
    due = None
    d = DUE.search(body)
    if d:
        due = d.group(1)
        if due.lower() in WEEKDAYS:
            due = due[0].upper() + due[1:].lower()
        body = body[:d.start()].strip()
    body = re.sub(r"\s+(?:by|on|before|this|next|until)$", "", body, flags=re.I).strip()
    return Commitment(body, due)
