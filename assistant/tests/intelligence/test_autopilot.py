from buds_assistant.intelligence.autopilot import AutopilotEngine
from buds_assistant.core.config import Config
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.core.store import Store
from test_policy import ev, seed


def decisions(s):
    return [(d["trigger"], d["outcome"], d["reason"]) for d in s.decisions()]


def test_capture_works_on_cold_start(tmp_path):
    s = Store(tmp_path); me = s.add_person("Me")
    p = AutopilotEngine(Config(data_dir=tmp_path), s, Memory(s, FakeLLM())); p.enabled = True
    h = p.on_segment(ev(me, "Me", "I'll send it Friday", is_self=True), 1000.0)
    assert h and h.kind == "noted" and h.trigger == "capture" and "send it" in h.text and "Friday" in h.text
    assert s.facts(person_id=me, kind="commitment")[0]["text"] == "send it"
    assert h.fact_id == s.facts(person_id=me, kind="commitment")[0]["id"]
    assert decisions(s)[-1][:2] == ("capture", "noted")
    assert s.decisions()[-1]["fact_id"] == h.fact_id                       # the UI needs it for Undo


def test_disabled_autopilot_is_silent_and_does_not_log(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.enabled = False
    assert p.on_segment(ev(ravi, "Ravi", "Hello there"), 1000.0) is None
    assert s.decisions() == []


def test_every_suppressed_candidate_has_a_reason(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    assert p.on_segment(ev(ravi, "Ravi", "Hello again"), 2000.0).trigger == "identity"
    p.on_segment(ev(ravi, "Ravi", "When is the Q3 report due?"), 2005.0)          # 5 s later
    assert ("question", "held_back", "too_soon") in decisions(s)


def test_budget_reason(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    cfg.hint_min_gap = 0; cfg.hints_per_hour = 1
    p.last_spoke[ravi] = 10 ** 9; p.last_cue[ravi] = 10 ** 9
    p.on_segment(ev(ravi, "Ravi", "About the Q3 report"), 3000.0)
    p.on_segment(ev(ravi, "Ravi", "About the Q3 report again"), 3010.0)
    assert ("commitment", "held_back", "hourly_budget") in decisions(s)


def test_unknown_voice_question_is_logged_not_whispered(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    assert p.on_segment(ev(None, "Speaker A", "When is the demo?"), 1000.0) is None
    assert ("question", "held_back", "unknown_voice") in decisions(s)


def test_question_with_no_memory_hit_is_logged(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.last_cue[ravi] = 1000.0; p.last_spoke[ravi] = 1000.0
    assert p.on_segment(ev(ravi, "Ravi", "What is the airspeed of a swallow?"), 1010.0) is None
    assert ("question", "held_back", "no_confident_match") in decisions(s)


def test_quiet_sensitivity_only_capture_and_question(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    cfg.autopilot_sensitivity = "quiet"
    assert p.on_segment(ev(ravi, "Ravi", "Good morning"), 1000.0) is None
    assert ("identity", "held_back", "category_off") in decisions(s)


def test_category_override(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    cfg.autopilot_categories = ["identity"]
    assert p.on_segment(ev(ravi, "Ravi", "Good morning"), 1000.0).trigger == "identity"


def test_capture_is_not_blocked_by_min_gap_but_counts_to_budget(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.on_segment(ev(ravi, "Ravi", "Good morning"), 1000.0)
    h = p.on_segment(ev(me, "Me", "I will call Anita tomorrow", is_self=True), 1002.0)
    assert h and h.trigger == "capture" and len(p.hour) == 2


def test_mention_of_known_person_gives_brief(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    s.add_fact(ravi, "fact", "is the new finance lead", None, None)
    h = p.on_segment(ev(me, "Me", "Is Ravi coming?", is_self=True), 1000.0)
    assert h and h.trigger == "mention" and "finance lead" in h.text
    assert p.on_segment(ev(me, "Me", "Is Ravi coming later?", is_self=True), 1100.0) is None     # debounced


def test_recently_dismissed_trigger_reason(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.feedback(1, False, "identity", 1000.0)
    assert p.on_segment(ev(ravi, "Ravi", "Good morning"), 1100.0) is None
    assert ("identity", "held_back", "recently_dismissed") in decisions(s)


def test_decisions_are_published_on_the_bus(tmp_path):
    from buds_assistant.core.events import EventBus
    s = Store(tmp_path); me = s.add_person("Me"); ev_bus = EventBus()
    p = AutopilotEngine(Config(data_dir=tmp_path), s, Memory(s, FakeLLM()), ev_bus); p.enabled = True
    p.on_segment(ev(me, "Me", "I'll send it Friday", is_self=True), 1000.0)
    assert ev_bus.recent(types={"autopilot_decision"})[-1]["data"]["outcome"] == "noted"
