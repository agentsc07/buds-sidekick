import numpy as np
import pytest

from buds_assistant.core.config import Config
from buds_assistant.core.events import EventBus
from buds_assistant.controls.gestures import Binding
from buds_assistant.core.modes import ModeManager, load_profiles
from buds_assistant.audio.output import FakePlayer, FakeTTS, OutputArbiter
from buds_assistant.audio.capture import RingBuffer
from buds_assistant.core.store import Store
from pathlib import Path


class Src:
    def __init__(self, name): self.name, self.stopped = name, False
    def start(self, cb): self.cb = cb
    def stop(self): self.stopped = True


class FakePipeline:
    def __init__(self): self.conv_id, self.source, self.current_speaker, self.placement = None, None, None, "ear"; self.log = []
    def start(self, source, mode, placement):
        self.conv_id, self.source = 7, source; self.log.append(("start", source.name, placement)); return 7
    def set_source(self, source): self.source = source; self.log.append(("source", source.name))
    def stop(self, extract=True, discard=False): self.conv_id, self.source = None, None; self.log.append(("stop", extract))


class FakePolicy:
    def __init__(self): self.enabled = False


def make(tmp_path, placement="auto"):
    cfg = Config(data_dir=tmp_path, placement=placement, live_translation=True)
    ev, store, ring = EventBus(), Store(tmp_path), RingBuffer(8)
    ear, remote = FakePlayer(), FakePlayer()
    out = OutputArbiter(FakeTTS(), {"ear": ear, "remote": remote}, ev)
    amb = []

    async def ambient(on): amb.append(on)
    pipe = FakePipeline()
    profiles = load_profiles(Path(__file__).resolve().parents[2] / "buds_assistant" / "config" / "sidekick_gestures.yaml")
    mc = ModeManager(cfg, ev, out, ring, pipe, FakePolicy(), store, lambda pl: Src("buds-mic" if pl == "ear" else "mac-mic"),
                        profiles, {}, ambient)
    return mc, pipe, out, ring, amb, ear, remote, ev, store


async def test_both_buds_out_means_remote_placement_with_mac_audio(tmp_path):
    mc, pipe, out, ring, amb, ear, remote, ev, store = make(tmp_path)
    await mc.on_wear("L", 1); await mc.on_wear("R", 1)
    assert mc.placement == "ear"
    await mc.on_wear("L", 2); await mc.on_wear("R", 3)                       # out of ear / in case
    assert mc.placement == "remote" and out.route == "remote"
    await mc.on_wear("R", 1)                                                  # one bud back in
    assert mc.placement == "ear" and out.route == "ear"


async def test_conversation_switches_microphone_when_buds_come_out(tmp_path):
    mc, pipe, out, ring, amb, *_ = make(tmp_path)
    await mc.on_wear("L", 1); await mc.on_wear("R", 1)
    await mc.set_mode("listen")
    assert pipe.log[0] == ("start", "buds-mic", "ear") and amb == [True]      # ambient sound on while talking to people
    await mc.on_wear("L", 2); await mc.on_wear("R", 2)
    assert pipe.log[-1] == ("source", "mac-mic")                              # conversation continues on the Mac mic
    await mc.set_mode("standby")
    assert pipe.log[-1][0] == "stop" and amb == [True, False]


async def test_private_mode_clears_buffer_and_stops_everything(tmp_path):
    mc, pipe, out, ring, amb, *_ = make(tmp_path)
    await mc.set_mode("autopilot")
    assert mc.policy.enabled
    ring.push(np.ones(16000, dtype=np.int16))
    await mc.dispatch("private_toggle")
    assert mc.mode == "private" and ring.seconds == 0 and not mc.policy.enabled and pipe.log[-1] == ("stop", False)
    await mc.dispatch("private_toggle")
    assert mc.mode == "standby"


async def test_replay_plays_last_n_seconds_on_current_route(tmp_path):
    mc, pipe, out, ring, amb, ear, remote, *_ = make(tmp_path)
    await mc.dispatch("replay")
    assert out.log[-1]["kind"] in ("speak", "speak_done")                     # nothing buffered: says so
    await mc.set_mode("listen")
    ring.push(np.arange(16000 * 10, dtype=np.int16) % 100)
    await mc.dispatch("replay")
    assert len(ear.played) >= 1 and ear.played[-1][0].size == 8 * 16000       # default window 8 s
    await mc.set_placement("remote")
    await mc.dispatch("replay")
    assert remote.played[-1][0].size == 8 * 16000


async def test_mark_records_bookmark_with_speaker(tmp_path):
    mc, pipe, out, ring, amb, ear, remote, ev, store = make(tmp_path)
    await mc.set_mode("listen")
    pipe.current_speaker = {"name": "Ravi", "person_id": None}
    await mc.dispatch("mark")
    assert store.bookmarks(7) and any(e["type"] == "bookmark" and e["data"]["speaker"] == "Ravi" for e in ev.recent())


async def test_ear_and_remote_share_one_gesture_map(tmp_path):
    mc, *_ = make(tmp_path)
    key = lambda p: sorted((b.name, b.pattern, b.action) for b in mc.recognizers[p].bindings)   # noqa: E731
    assert key("ear") == key("remote")
    await mc.set_placement("remote")
    await mc.on_token("R:hold_start", 100.0)                                  # same hold toggles listening in the remote profile
    assert mc.mode == "listen"



async def test_unknown_action_is_reported_not_raised(tmp_path):
    mc, pipe, out, ring, amb, ear, remote, ev, store = make(tmp_path)
    await mc.dispatch("bogus")
    assert any(e["type"] == "error" for e in ev.recent())


async def test_autopilot_from_standby_starts_listen_then_whispers(tmp_path):
    mc, pipe, out, ring, amb, *_ = make(tmp_path)
    await mc.on_wear("L", 1); await mc.on_wear("R", 1)
    await mc.set_mode("autopilot")
    assert pipe.log[0] == ("start", "buds-mic", "ear") and mc.policy.enabled and amb == [True]
    await mc.dispatch("autopilot_toggle")                      # off -> back to listen, mic stays on
    assert mc.mode == "listen" and not mc.policy.enabled and pipe.conv_id == 7


async def test_interpreter_pauses_autopilot_and_restores_it(tmp_path):
    mc, pipe, *_ = make(tmp_path)
    await mc.on_wear("L", 1); await mc.on_wear("R", 1)
    await mc.set_mode("autopilot")
    await mc.set_mode("interpreter")
    assert not mc.policy.enabled and mc.cfg.interpreter
    assert ("source", "mac-mic") in pipe.log                   # Mac mic by default
    await mc.dispatch("interpreter_toggle")                    # off
    assert mc.mode == "autopilot" and mc.policy.enabled and not mc.cfg.interpreter
    assert pipe.log[-1] == ("source", "buds-mic")


async def test_private_wins_and_returns_to_standby_even_if_asked_for_autopilot(tmp_path):
    mc, pipe, *_ = make(tmp_path)
    await mc.set_mode("autopilot")
    await mc.set_mode("private")
    assert mc.mode == "private" and not mc.policy.enabled and pipe.log[-1] == ("stop", False)
    await mc.set_mode("autopilot")
    assert mc.mode == "standby"


async def test_replay_in_standby_says_listen_first(tmp_path):
    mc, pipe, out, *_ = make(tmp_path)
    await mc.dispatch("replay")
    assert any("Listen first" in x.get("text", "") for x in out.log)


async def test_every_mode_change_is_audited_and_published(tmp_path):
    mc, pipe, out, ring, amb, ear, remote, ev, store = make(tmp_path)
    await mc.set_mode("listen")
    assert store.audit_log()[0]["kind"] == "mode"
    last = ev.recent(types={"mode"})[-1]["data"]
    assert last["mode"] == "listen" and last["memory_level"] == "remember"


async def test_recording_level_needs_a_listening_mode(tmp_path):
    mc, pipe, out, ring, amb, ear, remote, ev, store = make(tmp_path)
    try:
        await mc.set_memory_level("recording")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Listen" in str(exc)
    await mc.set_mode("listen")
    await mc.set_memory_level("recording")
    assert mc.memory_level == "recording" and any(a["kind"] == "recording_start" for a in store.audit_log())
    await mc.set_mode("standby")
    assert mc.memory_level == "remember"                        # recording is per conversation


async def test_pocket_burst_is_cut_off_after_three_taps(tmp_path):
    mc, *_ = make(tmp_path)
    for i in range(4):                                          # 4 double-taps in 0.3 s: only the first 3 count
        await mc.on_token("R:double", 50.0 + i * 0.1)
    assert mc.mode == "autopilot"                               # on, off, on (a 4th toggle would leave it in listen)


async def test_hold_toggles_listen_once_per_burst(tmp_path):
    mc, *_ = make(tmp_path)
    await mc.on_token("R:hold_start", 60.0); await mc.on_token("R:hold_start", 60.4)
    assert mc.mode == "listen"


async def test_double_tap_after_whisper_does_not_toggle_autopilot(tmp_path):
    mc, *_ = make(tmp_path)
    await mc.set_mode("listen")
    seen = []

    async def not_useful(**k): seen.append("nu")
    mc.handlers["not_useful"] = not_useful
    mc.context.open("whisper", 100.0)
    await mc.on_token("R:double", 101.0)
    assert seen == ["nu"] and mc.mode == "listen"
    await mc.on_token("R:double", 110.0)
    assert mc.mode == "autopilot"


async def test_mode_changes_play_earcon_and_say_short_phrase(tmp_path):
    import asyncio
    mc, pipe, out, *_ = make(tmp_path)
    await mc.set_mode("autopilot")
    await asyncio.sleep(0.5)
    assert any(x["kind"] == "earcon" and x["name"] == "mode_on" for x in out.log)
    assert any(x["kind"] == "speak" and x["text"] == "Autopilot on" for x in out.log)
    await mc.set_mode("standby")
    await asyncio.sleep(0.1)
    assert any(x["kind"] == "earcon" and x["name"] == "mode_off" for x in out.log)


async def test_gesture_is_acknowledged_with_an_earcon(tmp_path):
    import asyncio
    mc, pipe, out, *_ = make(tmp_path)
    await mc.on_token("R:single", 10.0)                          # mark
    await asyncio.sleep(0.05)
    assert any(x["kind"] == "earcon" and x["name"] in ("accepted", "noted") for x in out.log)


class FakeModels:
    def __init__(self): self.calls = []
    def state(self): return {"translate": "unloaded"}
    def enter(self, mode): self.calls.append(("enter", mode))
    def leave(self, mode): self.calls.append(("leave", mode))


async def test_interpreter_loads_and_unloads_models_via_manager(tmp_path):
    import asyncio
    mc, *_ = make(tmp_path)
    mc.models = FakeModels()
    await mc.set_mode("interpreter")
    assert mc.models.calls == [("enter", "interpreter")]
    await mc.set_mode("standby")
    await asyncio.sleep(0.05)
    assert mc.models.calls[-1] == ("leave", "interpreter")


async def test_the_ui_is_told_while_the_interpreter_is_getting_ready(tmp_path):
    """Real glitch: while the models took a minute to load, the mode still read 'listen', so the button flipped back and a second click switched Interpreter off."""
    mc, pipe, out, ring, amb, ear, remote, ev, store = make(tmp_path)
    seen = []

    class SlowModels(FakeModels):
        def enter(self, mode):
            seen.append([e["data"].get("mode") for e in ev.recent(50, {"mode_pending"})])
            super().enter(mode)

    mc.models = SlowModels()
    await mc.set_mode("interpreter")
    pend = [e["data"]["mode"] for e in ev.recent(50, {"mode_pending"})]
    assert pend == ["interpreter", None] and seen == [["interpreter"]]          # announced before loading, cleared after


def test_ui_snapshot_carries_the_pending_mode():
    from buds_assistant.core.config import Config
    from buds_assistant.core.events import EventBus
    from buds_assistant.core.uistate import UiState
    bus = EventBus(); ui = UiState(bus, Config())
    assert ui.snapshot()["pending_mode"] is None
    bus.publish("mode_pending", mode="interpreter")
    assert ui.snapshot()["pending_mode"] == "interpreter"
    bus.publish("mode_pending", mode=None)
    assert ui.snapshot()["pending_mode"] is None


async def test_translating_saves_nothing_even_if_remembering_is_on(tmp_path):
    """Translate needs the microphone, but a conversation that is only being translated must not become memory."""
    mc, pipe, *_ = make(tmp_path)
    pipe.persist = True
    await mc.set_mode("listen")
    assert pipe.persist is True
    await mc.set_mode("interpreter")
    assert pipe.persist is False
    await mc.set_memory_level("remember")                       # flipping the memory switch while translating must not turn saving on
    assert pipe.persist is False
    await mc.set_mode("listen")
    assert pipe.persist is True


async def test_live_translation_is_off_by_default(tmp_path):
    assert Config(data_dir=tmp_path).live_translation is False
    mc = make(tmp_path)[0]
    mc.cfg.live_translation = False
    with pytest.raises(ValueError):
        await mc.set_mode("interpreter")
    assert mc.mode != "interpreter"
