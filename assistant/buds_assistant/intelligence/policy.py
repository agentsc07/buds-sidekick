"""Compatibility shim: the v1 `Policy` is now `AutopilotEngine` (autopilot.py)."""
from buds_assistant.intelligence.autopilot import QUESTION, AutopilotEngine as Policy, Hint, clip_words  # noqa: F401
