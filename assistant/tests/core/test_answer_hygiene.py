"""Answers must not pile up: a slow model must not make old questions get spoken minutes later, or one click three times."""
import asyncio
import time

import pytest

from buds_assistant.intelligence.brain import Reply
from buds_assistant.core.config import Config
from buds_assistant.intelligence.llm import FakeLLM
from test_dashboard import _make


@pytest.fixture
def sk(tmp_path):
    return _make(Config(data_dir=tmp_path, answer_stale_s=0.15), FakeLLM())


def spoken(sk):
    return [x["text"] for x in sk.output.log if x["kind"] == "speak"]


async def test_an_answer_that_arrives_too_late_is_shown_but_not_spoken(sk):
    def slow(text, ctx):
        time.sleep(0.4)
        return Reply("Your calendar is clear.", "en", "calendar")
    sk.brain.respond = slow
    r = await sk.answer("what is on my calendar")
    assert r.text == "Your calendar is clear." and spoken(sk) == []
    assert any(e["type"] == "reply" for e in sk.events.recent(20, {"reply"}))            # still visible on the dashboard
    assert any(e["type"] == "reply_stale" for e in sk.events.recent(20, {"reply_stale"}))


async def test_the_same_question_asked_again_while_working_shares_one_answer(sk):
    calls = []
    sk.cfg.answer_stale_s = 5
    def once(text, ctx):
        calls.append(text); time.sleep(0.2)
        return Reply("Done.", "en", "x")
    sk.brain.respond = once
    rs = await asyncio.gather(sk.answer("translate good morning"), sk.answer("translate good morning"), sk.answer("Translate good morning "))
    assert len(calls) == 1 and all(r.text == "Done." for r in rs) and spoken(sk) == ["Done."]
