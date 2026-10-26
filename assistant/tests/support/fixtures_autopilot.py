"""A scripted ten-minute, three-person conversation with labelled Autopilot trigger points (spec 5.9).

Line = (offset_seconds, speaker, person_key, text, is_self, expected_trigger_or_None). `person_key` None = unknown voice."""
import time

from buds_assistant.core.config import Config
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.core.store import Store

SCRIPT = [
    (0, "Ravi", "Ravi", "Good morning everyone", False, "identity"),
    (12, "Me", "Me", "Morning Ravi, how was the trip", True, None),
    (30, "Ravi", "Ravi", "The trip was fine, busy as always", False, None),
    (50, "Priya", "Priya", "Hi all, sorry I am late", False, "identity"),
    (70, "Me", "Me", "I'll send the deck Friday", True, "capture"),
    (95, "Priya", "Priya", "When is the demo?", False, "question"),
    (120, "Me", "Me", "The demo is October fourteenth", True, None),
    (150, "Ravi", "Ravi", "About the Q3 report, I am still working on it", False, "commitment"),
    (180, "Speaker A", None, "Excuse me, when does the parking permit expire?", False, None),
    (200, "Priya", "Priya", "Let us move on to the budget", False, None),
    (230, "Me", "Me", "Sounds good to me", True, None),
    (260, "Ravi", "Ravi", "Thanks, that covers my part", False, None),
    (300, "Me", "Me", "I will think about it", True, None),
    (330, "Priya", "Priya", "Do you have the numbers for the second quarter?", False, None),
    (360, "Me", "Me", "Let me email Ravi the contract by Monday", True, "capture"),
    (400, "Me", "Me", "Has Priya seen the new numbers", True, "mention"),
    (430, "Priya", "Priya", "Yes I looked at them yesterday", False, None),
    (470, "Ravi", "Ravi", "Great, let us wrap up here", False, None),
    (520, "Me", "Me", "Thanks everyone", True, None),
    (560, "Speaker A", None, "Where can I find the parking office?", False, None),
    (600, "Me", "Me", "I'm going to review the slides tonight", True, "capture"),
]


def build(tmp_path, with_memory: bool = True, **cfg_kw):
    """Returns (engine, store, people). with_memory=False is the cold start: only the wearer is enrolled, nothing stored."""
    from buds_assistant.intelligence.autopilot import AutopilotEngine
    cfg = Config(data_dir=tmp_path, **cfg_kw)
    s = Store(tmp_path)
    mem = Memory(s, FakeLLM())
    people = {"Me": s.add_person("Me")}
    if with_memory:
        people["Ravi"], people["Priya"] = s.add_person("Ravi"), s.add_person("Priya")
        cid, t = s.start_conversation("listen"), time.time() - 86400
        sid = s.add_segment(cid, t, t + 3, people["Me"], None, 0.9, "When is the demo? The demo is October fourteenth")
        mem.index_segment(sid, "When is the demo? The demo is October fourteenth")
        sid2 = s.add_segment(cid, t + 5, t + 8, people["Ravi"], None, 0.9, "I will send the Q3 report by Friday")
        mem.index_segment(sid2, "I will send the Q3 report by Friday")
        s.add_fact(people["Ravi"], "commitment", "send the Q3 report", "Friday", sid2, owner="Ravi")
        s.add_fact(people["Priya"], "fact", "joined from finance last week", None, None)
    p = AutopilotEngine(cfg, s, mem)
    p.enabled = True
    return p, s, people, cfg


def run(script, engine, people, base: float = 10_000.0):
    """Feed the script; return [(offset, trigger, expected)] for every whisper."""
    said = []
    for off, name, key, text, is_self, expected in script:
        e = {"person_id": people.get(key), "speaker": name, "text": text, "is_self": is_self, "seg_id": None}
        h = engine.on_segment(e, base + off)
        if h:
            said.append((off, h.trigger, expected))
    return said
