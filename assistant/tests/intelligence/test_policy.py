import time

from buds_assistant.core.config import Config
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.intelligence.policy import Policy
from buds_assistant.core.store import Store


def seed(tmp_path):
    s = Store(tmp_path)
    cfg = Config(data_dir=tmp_path)
    mem = Memory(s, FakeLLM())
    ravi, me = s.add_person("Ravi"), s.add_person("Me")
    cid = s.start_conversation("auto")
    t = time.time() - 86400
    sid = s.add_segment(cid, t, t + 2, me, None, 0.9, "I will finalise the vendor contract by Monday")
    mem.index_segment(sid, "I will finalise the vendor contract by Monday")
    sid2 = s.add_segment(cid, t + 5, t + 7, ravi, None, 0.9, "I will send you the Q3 report by Friday")
    mem.index_segment(sid2, "I will send you the Q3 report by Friday")
    s.add_fact(ravi, "commitment", "send the Q3 report", "Friday", sid2, owner="Ravi")
    p = Policy(cfg, s, mem)
    p.enabled = True
    return p, s, ravi, me, cfg


def ev(pid, name, text, **k):
    return {"person_id": pid, "speaker": name, "text": text, "is_self": name == "Me", "seg_id": None, **k}


def test_identity_cue_once_per_window_with_open_commitment(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    t = 1000.0
    h = p.on_segment(ev(ravi, "Ravi", "Hi, good morning"), t)
    assert h and h.trigger == "identity" and "Ravi" in h.text and "Q3 report" in h.text
    assert p.on_segment(ev(ravi, "Ravi", "How is your week"), t + 30) is None          # no repeat cue
    assert s.hints()[0]["text"] == h.text


def test_unknown_speakers_and_self_never_get_hints(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    assert p.on_segment(ev(None, "Speaker A", "Hello there how are you?"), 1000) is None
    assert p.on_segment(ev(me, "Me", "I am fine"), 1000) is None
    assert s.hints() == []


def test_question_answered_by_memory(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.last_cue[ravi] = 1000.0; p.last_spoke[ravi] = 1000.0                              # skip identity cue
    h = p.on_segment(ev(ravi, "Ravi", "When will you finalise the vendor contract?"), 1010)
    assert h and h.trigger == "question" and "Monday" in h.text and h.sources


def test_commitment_mention_and_word_limit(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.last_cue[ravi] = 1000.0; p.last_spoke[ravi] = 1000.0
    h = p.on_segment(ev(ravi, "Ravi", "About the Q3 report, I am still working on it"), 1010)
    assert h and h.trigger == "commitment" and len(h.text.split()) <= cfg.hint_max_words


def test_gating_no_talking_over_you_gap_budget(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.last_cue[ravi] = 1000.0; p.last_spoke[ravi] = 1000.0
    p.on_segment(ev(me, "Me", "let me answer that"), 1010)                               # you are speaking
    assert p.on_segment(ev(ravi, "Ravi", "About the Q3 report?"), 1010.5) is None
    assert p.on_segment(ev(ravi, "Ravi", "About the Q3 report?"), 1013) is not None
    assert p.on_segment(ev(ravi, "Ravi", "And the Q3 report again?"), 1020) is None      # < 20 s since last hint
    p.enabled = False
    assert p.on_segment(ev(ravi, "Ravi", "Q3 report?"), 5000) is None                    # auto mode off = silent


def test_hourly_budget_and_feedback_slows_down(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    cfg.hint_min_gap = 0
    p.last_spoke[ravi] = 10 ** 9
    p.last_cue[ravi] = 10 ** 9
    n = 0
    for i in range(60):
        n += p.on_segment(ev(ravi, "Ravi", "About the Q3 report"), 2000 + i * 5) is not None
    assert n == cfg.hints_per_hour
    p2, *_ = seed(tmp_path / "b")
    for _ in range(3):
        p2.feedback(1, False, "commitment", 1000)
    assert p2.rate_factor == 2.0 and p2.muted["commitment"] > 1000
    p2.feedback(1, True)
    assert p2.dismiss_streak == 0


def test_low_confidence_me_is_not_treated_as_a_stranger_to_speak_to(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    # labelled "Me" but not confident (is_self False): no hints about "Me", and it does not count as you speaking
    assert p.on_segment(ev(me, "Me", "Hello there, how are you?", is_self=False), 1000) is None
    assert p.user_last == 0.0
