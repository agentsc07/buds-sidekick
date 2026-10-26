import asyncio

import numpy as np

from buds_assistant.audio.output import FakePlayer, FakeTTS, OutputArbiter


def make(hold=0.0):
    ear, remote = FakePlayer(hold), FakePlayer(hold)
    tts = FakeTTS()
    return OutputArbiter(tts, {"ear": ear, "remote": remote}, hint_ttl=0.2), tts, ear, remote


async def test_say_plays_and_uses_language_voice():
    out, tts, ear, _ = make()
    assert await out.say("hello", "en") and await out.say("తెలుగు", "te")
    assert tts.rendered == [("hello", "en"), ("తెలుగు", "te")] and len(ear.played) == 2


async def test_whisper_lowers_gain():
    out, _, ear, _ = make()
    await out.say("x", whisper=True)
    await out.say("x", whisper=False)
    assert abs(int(ear.played[0][0].max())) < abs(int(ear.played[1][0].max())) * 0.5


async def test_answer_interrupts_hint_but_hint_cannot_interrupt_answer():
    out, _, ear, _ = make(hold=0.3)
    hint = asyncio.create_task(out.say("a hint", priority="hint"))
    await asyncio.sleep(0.05)
    await out.say("the answer", priority="answer")
    await hint
    assert [p for p in ear.played][-1][0].size > 0 and ear.stopped >= 1
    out2, _, _, _ = make(hold=0.3)
    ans = asyncio.create_task(out2.say("answer", priority="answer"))
    await asyncio.sleep(0.05)
    assert await out2.say("late hint", priority="hint") is False        # queued, not played over the answer
    await ans


async def test_stale_hint_is_dropped():
    out, _, ear, _ = make(hold=0.4)
    ans = asyncio.create_task(out.say("answer", priority="answer"))
    await asyncio.sleep(0.05)
    await out.say("hint", priority="hint")                              # ttl 0.2 s < answer duration 0.4 s
    await ans
    assert len(ear.played) == 1 and any(e.get("reason") == "stale" for e in out.log)


async def test_route_switch_changes_device_and_replay_speed():
    out, _, ear, remote = make()
    out.set_route("remote")
    await out.say("hi")
    assert len(remote.played) == 1 and len(ear.played) == 0
    audio = np.arange(16000, dtype=np.int16)
    await out.play_audio(audio, 16000, speed=2.0)
    assert remote.played[-1][0].size == 8000
    assert await out.play_audio(np.zeros(0, dtype=np.int16)) is False
