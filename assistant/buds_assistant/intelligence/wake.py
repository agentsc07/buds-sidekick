"""Talking to the assistant by name while Listen or Autopilot is on: 'Hey Sidekick, what's on my calendar?'"""
from __future__ import annotations

import re

NAMES = r"side\s?kick|autopilot|assistant"
WAKE = re.compile(rf"^\s*(?:(?:hey|hi|ok|okay|yo)[,\s]+)?(?:{NAMES})\b[\s,:;.\-]*(.*)$", re.I | re.S)


def wake_query(text: str) -> str | None:
    """The request that follows the name (may be empty), or None when the sentence is not addressed to the assistant."""
    m = WAKE.match(text or "")
    return m.group(1).strip() if m else None
