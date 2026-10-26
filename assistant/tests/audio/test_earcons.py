import asyncio

import numpy as np

from buds_assistant.audio.earcons import NAMES, Earcons, render
from buds_assistant.audio.output import FakePlayer, FakeTTS, OutputArbiter


def test_all_names_render_short_soft_and_distinct():
    sigs = {}
    for n in NAMES:
        a = render(n)
        assert a.dtype == np.int16 and 0.04 < a.size / 22050 < 0.7
        assert np.abs(a).max() <= 0.45 * 32767                      # soft
        sigs[n] = a
    assert len({a.tobytes() for a in sigs.values()}) == len(NAMES)  # all different


def test_required_set_exists():
    for n in ("mode_on", "mode_off", "listen_start", "listen_stop", "accepted", "command", "whisper", "noted",
              "error", "reminder", "thinking", "never_mind"):
        assert n in NAMES


def test_earcons_are_cached():
    e = Earcons()
    assert e.get("accepted")[0] is e.get("accepted")[0]


async def test_arbiter_plays_earcon_without_cutting_an_answer():
    p = FakePlayer()
    out = OutputArbiter(FakeTTS(), {"ear": p, "remote": FakePlayer()})
    out.earcon("accepted")
    await asyncio.sleep(0.05)
    assert len(p.played) == 1
    out._cur_task = asyncio.ensure_future(asyncio.sleep(0.2)); out._cur_prio = 3
    out.earcon("accepted")
    await asyncio.sleep(0.05)
    assert len(p.played) == 1                                         # skipped while an answer is playing
    out.earcon("error")
    await asyncio.sleep(0.05)
    assert len(p.played) == 2                                         # errors always sound
