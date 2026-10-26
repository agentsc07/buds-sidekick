"""Autopilot's judgement and the wake word are wired into the live app."""
import asyncio
import json

import pytest

from buds_assistant.core.config import Config
from buds_assistant.intelligence.llm import FakeLLM
from test_dashboard import _make


def spoken(sk):
    return [x["text"] for x in sk.output.log if x["kind"] == "speak"]


async def until(pred, seconds=4.0):
    end = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < end and not pred():
        await asyncio.sleep(0.05)


def turn(text, self_=True):
    return {"speaker": "Me" if self_ else "Ravi", "person_id": 1 if self_ else None, "text": text, "is_self": self_, "t0": 0, "t1": 1, "conf": 0.9, "lang": "en", "experimental": False}


@pytest.fixture
def sk(tmp_path):
    reply = json.dumps({"say": "Quick answer: the Eiffel Tower is 330 metres tall.", "todo": "", "score": 5})
    k = _make(Config(data_dir=tmp_path, hint_ttl=3.0), FakeLLM(lambda m, model: reply))
    k.personal.clear_sample()
    k.judge.debounce = 0.05
    return k


async def test_the_judge_whispers_in_autopilot(sk):
    sk.loop = asyncio.get_running_loop()
    sk.modes.mode = "autopilot"; sk.policy.enabled = True
    sk._on_turn(turn("I need to look up how tall the Eiffel Tower is"))
    await until(lambda: any("330 metres" in t for t in spoken(sk)))
    assert any("330 metres" in t for t in spoken(sk))


async def test_the_judge_is_silent_when_autopilot_is_off(sk):
    sk.loop = asyncio.get_running_loop()
    sk.modes.mode = "listen"; sk.policy.enabled = False
    sk._on_turn(turn("I need to look up how tall the Eiffel Tower is"))
    await asyncio.sleep(0.8)
    assert spoken(sk) == [] and sk.llm.calls == []


async def test_saying_its_name_gets_an_answer_in_listen_and_autopilot(sk):
    sk.loop = asyncio.get_running_loop()
    for mode in ("listen", "autopilot"):
        sk.output.log.clear()
        sk.modes.mode = mode; sk.policy.enabled = mode == "autopilot"
        sk._on_turn(turn("Hey Sidekick, add buy milk to my to-do list", self_=False))
        await until(lambda: any("buy milk" in t for t in spoken(sk)))
        assert any("buy milk" in t for t in spoken(sk)), (mode, sk.output.log[-6:], sk.events.recent(10, {"reply","reply_stale"}))
        assert any("buy milk" in t["text"] for t in sk.personal.todos())


async def test_saying_only_its_name_gets_a_polite_greeting_and_is_not_judged(sk):
    sk.loop = asyncio.get_running_loop()
    sk.modes.mode = "autopilot"; sk.policy.enabled = True
    sk._on_turn(turn("Sidekick", self_=False))
    await until(lambda: any("I'm here" in t for t in spoken(sk)))
    assert any("I'm here" in t for t in spoken(sk)) and sk.llm.calls == []
