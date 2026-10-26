import asyncio
import time
from dataclasses import dataclass

import numpy as np
import pytest
from fastapi.testclient import TestClient

from buds_assistant.core.config import Config
from buds_assistant.dashboard.server import create_app
from buds_assistant.core.events import EventBus
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.core.models import ModelManager
from buds_assistant.audio.segmenter import Segment
from buds_assistant.speech.transcribe import Transcript
from test_dashboard import _make
from test_interpreter import FakeTranslator
from test_speaker import clip


def test_entering_interpreter_loads_telugu_speech_and_leaving_unloads_it():
    calls = []
    m = ModelManager(FakeLLM(), Config(chat_model="qwen3.5:4b-mlx"), EventBus())          # separate chat model: the old swap behaviour
    m.hooks = {"enter": lambda: calls.append("enter"), "leave": lambda: calls.append("leave")}
    m.start(); m.enter("interpreter")
    assert calls == ["enter"] and m.state()["telugu"] == "ready"
    m.leave("interpreter")
    assert calls == ["enter", "leave"] and m.state()["telugu"] == "unloaded"


def test_a_telugu_model_that_fails_to_load_is_reported():
    ev = EventBus()
    m = ModelManager(FakeLLM(), Config(), ev)
    m.hooks = {"enter": lambda: (_ for _ in ()).throw(RuntimeError("no model"))}
    m.start(); m.enter("interpreter")
    assert m.state()["telugu"] == "unloaded" and any("Telugu" in e["data"]["error"] for e in ev.recent(types={"error"}))


async def test_interpreter_mode_uses_short_phrases_and_normal_modes_do_not(tmp_path):
    from test_modes import make
    mc, pipe, *_ = make(tmp_path)
    await mc.set_mode("interpreter")
    assert pipe.seg_kwargs["end_silence"] < 0.7
    await mc.set_mode("listen")
    assert pipe.seg_kwargs == {}


class TeTranscriber:
    def transcribe(self, audio, lang_hint=None):
        return Transcript("రేపు కలుద్దాం", "te", 0.9, True)


async def test_a_telugu_phrase_heard_while_interpreting_is_spoken_in_english(tmp_path):
    sk = _make(Config(data_dir=tmp_path, live_translation=True), FakeLLM())
    sk.pipeline.transcriber = TeTranscriber()
    sk.interpreter.translator = FakeTranslator()
    sk.loop = asyncio.get_running_loop()
    sk.cfg.interpreter = True
    sk.pipeline._stream_start = time.time() - 2
    await asyncio.get_running_loop().run_in_executor(None, sk.pipeline.feed_segment, Segment(0, 2, clip(1, 16000 * 2)))
    await asyncio.sleep(0.05)
    await sk.interpreter.process_all()
    assert [x["text"] for x in sk.output.log if x["kind"] == "speak"] == ["[en] రేపు కలుద్దాం"]
    assert not sk.store.segments()                              # Telugu is experimental: never stored


async def test_nothing_is_interpreted_when_the_mode_is_off(tmp_path):
    sk = _make(Config(data_dir=tmp_path, live_translation=True), FakeLLM())
    sk.pipeline.transcriber = TeTranscriber()
    sk.interpreter.translator = FakeTranslator()
    sk.loop = asyncio.get_running_loop()
    await asyncio.get_running_loop().run_in_executor(None, sk.pipeline.feed_segment, Segment(0, 2, clip(1, 16000 * 2)))
    await asyncio.sleep(0.05)
    assert sk.interpreter.queue == [] or len(sk.interpreter.queue) == 0


def test_two_way_can_be_switched_from_the_dashboard(tmp_path):
    sk = _make(Config(data_dir=tmp_path, live_translation=True), FakeLLM())
    c = TestClient(create_app(sk), base_url="http://127.0.0.1:8770")
    r = c.post("/api/v2/interpreter", json={"two_way": True})
    assert r.status_code == 200 and sk.cfg.interpreter_two_way is True
    assert c.get("/api/v2/state").json()["interpreter"] == {"two_way": True}
    c.post("/api/v2/interpreter", json={"two_way": False})
    assert c.get("/api/v2/state").json()["interpreter"] == {"two_way": False}
