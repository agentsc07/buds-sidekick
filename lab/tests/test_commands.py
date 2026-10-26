import asyncio

import pytest

from budslab.core.commands import CommandService
from budslab.core.events import Event
from budslab.core.hub import Hub
from budslab.core.state import DeviceState
from budslab.core.store import Store
from budslab.protocol import commands as C
from budslab.protocol.frames import FrameCodec


def test_only_allowlisted_ids_can_be_sent():
    for bad in (80, 82, 83, 176, 187, 212, 41, 38, 999, 0):         # reset, reboot, poweroff, FOTA, dumps, debug
        with pytest.raises(C.CommandError):
            C.check_tx_id(bad)
    for c in C.COMMANDS.values():
        C.check_tx_id(c.msg_id)
    assert not (C.ALLOWED_TX_IDS & C.DENYLIST)


def test_unknown_command_name_and_bad_args_rejected():
    with pytest.raises(C.CommandError):
        C.build("factory_reset", {}, {})
    with pytest.raises(C.CommandError):
        C.build("noise_control", {"mode": "turbo"}, {})
    with pytest.raises(C.CommandError):
        C.build("ambient_volume", {"level": 99}, {})


def test_payloads():
    assert C.build("noise_control", {"mode": "anc"}, {})[1] == b"\x01"
    assert C.build("equalizer", {"preset": "off"}, {})[1] == b"\x00"
    assert C.build("equalizer", {"preset": 2}, {})[1] == b"\x03"
    assert C.build("touchpad_option", {"left": "noise_control", "right": "volume"}, {})[1] == b"\x02\x03"
    assert len(C.build("update_time", {}, {})[1]) == 12


def test_lock_needs_known_state_and_preserves_gestures():
    with pytest.raises(C.CommandError):
        C.build("lock_touchpad", {"locked": True}, {})
    st = dict(touch_single_on=True, touch_double_on=True, touch_triple_on=False, touch_hold_on=True,
              touch_double_call_on=False, touch_hold_call_on=False)
    assert C.build("lock_touchpad", {"locked": True}, st)[1] == bytes([0, 1, 1, 0, 1, 0, 0])
    assert C.build("lock_touchpad", {"locked": False}, st)[1][0] == 1


def _svc(tmp_path, connected=True):
    store = Store(tmp_path, "t")
    hub = Hub(store)
    sent = []

    async def send(b):
        sent.append(b)
    svc = CommandService(hub, DeviceState(), FrameCodec(), send, lambda: connected, lambda *a: None)
    return svc, sent, store


def test_read_only_by_default_and_confirmation_gate(tmp_path):
    async def go():
        svc, sent, store = _svc(tmp_path)
        with pytest.raises(C.CommandError, match="disabled"):
            await svc.send("noise_control", {"mode": "anc"})
        svc.set_enabled(True)
        with pytest.raises(C.CommandError, match="confirmation"):
            await svc.send("find_my_start", {})
        assert sent == []                                          # nothing hit the wire
        store.close()
    asyncio.run(go())


def test_not_connected_refused(tmp_path):
    async def go():
        svc, sent, store = _svc(tmp_path, connected=False)
        svc.set_enabled(True)
        with pytest.raises(C.CommandError, match="not connected"):
            await svc.send("noise_control", {"mode": "off"})
        store.close()
    asyncio.run(go())
