import json
import time

from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.core.store import Store


def seed(tmp_path, llm):
    s = Store(tmp_path)
    ravi, anita = s.add_person("Ravi"), s.add_person("Anita")
    cid = s.start_conversation("conversation")
    now = time.time()
    rows = [(ravi, "The budget for the third quarter is two million dollars"),
            (ravi, "I will send you the report by Friday"),
            (anita, "The budget meeting moved to Thursday"),
            (anita, "My daughter starts school next month"),
            (ravi, "We should visit the Hyderabad office in March")]
    m = Memory(s, llm)
    ids = []
    for i, (p, t) in enumerate(rows):
        sid = s.add_segment(cid, now - 100 + i, now - 99 + i, p, None, 0.9, t)
        m.index_segment(sid, t)
        ids.append(sid)
    return s, m, ravi, anita, cid, ids


def test_retrieval_filters_by_person_and_topic(tmp_path):
    s, m, ravi, anita, *_ = seed(tmp_path, FakeLLM())
    hits = m.retrieve("what did Ravi say about the budget", person_id=ravi)
    assert hits and "two million" in hits[0].segment["text"] and all(h.segment["speaker_id"] == ravi for h in hits)
    anita_hits = m.retrieve("budget", person_id=anita)
    assert "Thursday" in anita_hits[0].segment["text"]
    assert m.retrieve("quantum chromodynamics", person_id=ravi) == []


def test_keyword_fallback_when_llm_down(tmp_path):
    s, m, ravi, *_ = seed(tmp_path, FakeLLM())
    m.llm = FakeLLM(up=False)                                  # Ollama unavailable: no exception, keyword search
    hits = m.retrieve("report Friday", person_id=ravi)
    assert hits and "Friday" in hits[0].segment["text"]


def test_fact_extraction_keeps_only_sourced_facts(tmp_path):
    s, m, ravi, anita, cid, ids = seed(tmp_path, FakeLLM())
    reply = json.dumps([{"segment_id": ids[1], "kind": "commitment", "text": "send the report", "due": "Friday"},
                        {"segment_id": 99999, "kind": "fact", "text": "invented", "due": None},      # no such segment
                        {"segment_id": ids[3], "kind": "mood", "text": "bad kind", "due": None}])
    m.llm = FakeLLM([reply])
    assert len(m.extract_facts(cid)) == 1
    c = m.commitments(ravi)
    assert c[0]["text"] == "send the report" and c[0]["source_segment"] == ids[1] and c[0]["person"] == "Ravi"
    m.llm = FakeLLM(["not json at all"])
    assert m.extract_facts(cid) == []                          # garbage from the model is ignored


def test_dossier(tmp_path):
    s, m, ravi, *_ = seed(tmp_path, FakeLLM())
    d = m.dossier(ravi)
    assert d["person"]["name"] == "Ravi" and d["segments"] == 3 and "budget" in d["topics"]


import pytest


@pytest.mark.slow
def test_real_embeddings_separate_topics(tmp_path):
    from buds_assistant.intelligence.llm import OllamaClient
    c = OllamaClient()
    if not c.available():
        pytest.skip("ollama not running")
    s, m, ravi, *_ = seed(tmp_path, c)
    assert "two million" in m.retrieve("how much money is allocated for the quarter", person_id=ravi)[0].segment["text"]
    assert m.retrieve("recipe for chocolate cake", person_id=ravi) == []


def test_fact_extraction_accepts_wrapped_and_single_object_replies(tmp_path):
    s, m, ravi, anita, cid, ids = seed(tmp_path, FakeLLM())
    wrapped = json.dumps({"facts": [{"segment_id": ids[1], "kind": "commitment", "text": "send the report", "due": "Friday"}]})
    m.llm = FakeLLM([wrapped])
    assert len(m.extract_facts(cid)) == 1
    single = json.dumps({"segment_id": ids[0], "kind": "fact", "text": "Q3 budget is two million", "due": None})
    m.llm = FakeLLM([single])
    assert len(m.extract_facts(cid)) == 1                       # a lone object (what qwen returned in practice)
