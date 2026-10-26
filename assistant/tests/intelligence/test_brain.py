import time
from datetime import datetime

from buds_assistant.intelligence.agent import RuleAgent
from buds_assistant.intelligence.brain import Brain, spoken_trim
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.core.store import Store
from buds_assistant.speech.translate import Translator

CTX = lambda **k: {"now": datetime(2026, 10, 1, 10, 0), "battery": None, **k}   # noqa: E731


def setup(tmp_path, replies=None, up=True):
    s = Store(tmp_path)
    llm = FakeLLM(replies if replies is not None else [], up=up)
    mem = Memory(s, llm)
    ravi, anita = s.add_person("Ravi"), s.add_person("Anita")
    cid = s.start_conversation("conversation")
    now = time.time()
    for i, (p, t) in enumerate([(ravi, "The budget for the third quarter is two million dollars"),
                                (ravi, "I will send you the report by Friday"),
                                (anita, "The budget meeting moved to Thursday")]):
        sid = s.add_segment(cid, now - 3600 + i, now - 3599 + i, p, None, 0.9, t)
        mem.index_segment(sid, t)
    return Brain(mem, Translator(llm), llm, RuleAgent(tmp_path / "n.jsonl"), s), s, llm, ravi, anita


def test_who_is_talking(tmp_path):
    b, *_ = setup(tmp_path)
    assert b.respond("who is talking", CTX(speaker={"name": "Ravi"})).text == "Ravi."
    assert "do not recognise" in b.respond("who's speaking?", CTX(speaker={"name": None, "cluster": "Speaker A"})).text
    assert "cannot tell" in b.respond("who is this", CTX()).text


def test_voice_commands_become_actions(tmp_path):
    b, *_ = setup(tmp_path)
    assert b.respond("replay that", CTX()).action == "replay"
    assert b.respond("mark this", CTX()).action == "mark"
    assert b.respond("auto mode on", CTX()).action == "auto:on"
    assert b.respond("autopilot off", CTX()).action == "auto:off"
    assert b.respond("private mode", CTX()).action == "private"


def test_what_did_ravi_say_uses_only_ravis_segments(tmp_path):
    b, s, llm, ravi, anita = setup(tmp_path, ["Ravi said the third quarter budget is two million dollars. He said it a while ago."])
    r = b.respond("what did Ravi say about the budget", CTX())
    assert r.intent == "rag" and "two million" in r.text and r.sources
    prompt = llm.calls[-1]["messages"][1]["content"]
    assert "two million" in prompt and "Thursday" not in prompt                   # Anita's words never leak into Ravi's answer
    assert {seg["speaker_id"] for seg in s.segments() if seg["id"] in r.sources} == {ravi}


def test_rule_intents_win_over_llm_and_online_questions_are_honest(tmp_path):
    b, *_ = setup(tmp_path, up=True)
    assert b.respond("what time is it", CTX()).text == "It is 10:00 AM."
    b2, *_ = setup(tmp_path / "x", up=False)
    r = b2.respond("what is the current petrol price", CTX())
    assert "offline" in r.text and r.intent.startswith("offline")                 # honest, no invention


def test_translate_routes_to_translator_with_telugu_voice(tmp_path):
    te = "రేపు కలుద్దాం"
    b, *_ = setup(tmp_path, [te, "See you tomorrow"])
    r = b.respond("translate to Telugu: see you tomorrow", CTX())
    assert r.text == te and r.lang == "te" and r.intent == "translate"
    r2 = b.respond("translate that", CTX(last_text=te))
    assert r2.lang == "en" and r2.text == "See you tomorrow"
    assert "nothing to translate" in b.respond("translate that", CTX()).text


def test_dossier_commitments_catch_up(tmp_path):
    b, s, llm, ravi, anita = setup(tmp_path, ["They talked about the budget. Ravi will send a report."])
    s.add_fact(ravi, "commitment", "send the report", "Friday", None, owner="Ravi")
    assert "send the report" in b.respond("what did Ravi promise me", CTX()).text
    assert "Ravi" in b.respond("what do I know about Ravi", CTX()).text
    assert "nothing stored" in b.respond("tell me about Anita", CTX()).text or "Anita" in b.respond("tell me about Anita", CTX()).text
    win = [{"speaker": "Ravi", "text": "the budget is two million"}]
    assert b.respond("catch me up", CTX(window=win)).intent == "catch_up"
    assert "nothing to catch up" in b.respond("catch me up", CTX()).text


def test_spoken_trim_limits_sentences_and_strips_markdown():
    assert spoken_trim("**One.** Two. Three. Four. Five.") == "One. Two. Three."
