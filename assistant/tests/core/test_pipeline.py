"""Gesture -> listen -> transcribe -> agent -> speak, with fake audio/STT/TTS (no hardware, no models)."""
import asyncio
import threading

import numpy as np

from buds_assistant.intelligence.agent import RuleAgent
from buds_assistant.legacy.app import Assistant
from buds_assistant.legacy.audio_io import Recording
from buds_assistant.controls.gestures import Binding, GestureRecognizer


class FakeRecorder:
    def __init__(self):
        self.calls = []
        self.opened = 0

    def open(self):
        self.opened += 1

    def record(self, stop, label, hold):
        self.calls.append((label, hold))
        if hold:
            stop.wait(2)                       # hold-to-talk: returns when the hold ends
        return Recording((np.ones(8000) * 3000).astype(np.int16), 16000, True, "fake mic")


class FakeSTT:
    needs_audio = True

    def __init__(self, text):
        self.text = text

    def transcribe(self, audio):
        assert audio is not None and audio.dtype == np.float32
        return self.text


class FakeTTS:
    def __init__(self):
        self.spoken = []

    async def speak(self, text):
        self.spoken.append(text)

    def stop(self):
        pass


BIND = [Binding("ask", ("L:double",), "ask"), Binding("hold", ("L:hold",), "ask_hold", "hold"),
        Binding("tog", ("R:hold",), "note_toggle", "toggle"), Binding("tog2", ("L:hold",), "ask_toggle", "toggle"),
        Binding("rep", ("R:double",), "repeat"),
        Binding("bat", ("L:triple",), "battery")]


def make(tmp_path, text):
    tts, rec = FakeTTS(), FakeRecorder()
    a = Assistant(GestureRecognizer(BIND), RuleAgent(tmp_path / "n.jsonl"), FakeSTT(text), tts, rec,
                  lambda: {"left": 70, "right": 71, "case": 5}, tmp_path, say=lambda s: None)
    return a, tts, rec


async def settle(a):
    for _ in range(100):
        await asyncio.sleep(0.02)
        if a._task and a._task.done():
            return


async def test_double_tap_asks_and_answers(tmp_path):
    a, tts, rec = make(tmp_path, "hello")
    await a.on_token("L:double")
    await settle(a)
    assert tts.spoken == ["Hello! How can I help?"] and rec.calls == [("ask", False)]
    row = __import__("json").loads((tmp_path / "assistant.jsonl").read_text().splitlines()[0])
    assert row["heard"] == "hello" and row["intent"] == "greeting" and "t_stt" in row


async def test_hold_to_talk_records_until_release(tmp_path):
    a, tts, rec = make(tmp_path, "what is 2 plus 3")
    await a.on_token("L:hold_start")
    await asyncio.sleep(0.1)
    assert tts.spoken == []                     # still holding: nothing answered yet
    await a.on_token("L:hold_end")
    await settle(a)
    assert tts.spoken == ["2 plus 3 is 5."] and rec.calls == [("ask", True)]


async def test_repeat_and_battery(tmp_path):
    a, tts, _ = make(tmp_path, "hello")
    await a.on_token("R:double")
    await settle(a)
    assert tts.spoken == ["I have nothing to repeat yet."]
    await a.on_token("L:triple")
    await settle(a)
    assert tts.spoken[-1].startswith("Left 70 percent")
    await a.on_token("R:double")
    await settle(a)
    assert tts.spoken[-1] == tts.spoken[-2]


async def test_note_hold_saves_note(tmp_path):
    a, tts, _ = make(tmp_path, "buy milk")
    await a.on_token("R:hold_start")
    await a.on_token("R:hold_end")
    await settle(a)
    assert tts.spoken == ["Noted: buy milk."] and "buy milk" in (tmp_path / "n.jsonl").read_text()


async def test_no_speech_says_nothing(tmp_path):
    a, tts, rec = make(tmp_path, "x")
    rec.record = lambda stop, label, hold: Recording(np.zeros(100, dtype=np.int16), 16000, False, "m")
    await a.on_token("L:double")
    await settle(a)
    assert tts.spoken == []


async def test_toggle_hold_on_then_off(tmp_path):
    a, tts, rec = make(tmp_path, "what is 4 times 5")
    rec.record = lambda stop, label, hold: (stop.wait(2), Recording((np.ones(8000) * 3000).astype(np.int16), 16000, True, "m"))[1]
    await a.on_token("L:hold_start")
    await asyncio.sleep(0.15)
    assert tts.spoken == [] and rec.opened == 1            # listening; mic opened before the cue
    await a.on_token("L:hold_end")                          # burst events of the same hold: ignored
    await asyncio.sleep(0.1)
    assert tts.spoken == []
    a.rec._hold_last["L"] -= 5                              # time passes: the user holds again
    await a.on_token("L:hold_start")
    await settle(a)
    assert tts.spoken == ["4 times 5 is 20."]
