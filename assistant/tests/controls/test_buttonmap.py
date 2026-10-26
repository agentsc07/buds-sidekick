import json

from buds_assistant.controls.buttonmap import ButtonMapGuard
from buds_assistant.core.events import EventBus


async def test_apply_saves_original_before_sending(tmp_path):
    sent = []

    async def send(l, r):
        assert json.loads((tmp_path / "buttonmap.json").read_text()) == {"left": "noise_control", "right": "noise_control"}
        sent.append((l, r))
    g = ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus())
    await g.apply("noise_control", "noise_control", "other_l", "other_r")
    assert sent == [("other_l", "other_r")]


async def test_second_apply_never_overwrites_the_saved_original(tmp_path):
    async def send(l, r): pass
    g = ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus())
    await g.apply("noise_control", "noise_control", "other_l", "other_r")
    await g.apply("other_l", "other_r", "other_l", "other_r")          # we now read OUR remap back from the buds
    assert json.loads((tmp_path / "buttonmap.json").read_text())["left"] == "noise_control"


async def test_restore_sends_original_and_clears_file(tmp_path):
    sent = []

    async def send(l, r): sent.append((l, r))
    g = ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus())
    await g.apply("volume", "spotify", "other_l", "other_r")
    await g.restore()
    assert sent[-1] == ("volume", "spotify") and not (tmp_path / "buttonmap.json").exists()


async def test_recover_after_crash_restores_on_next_start(tmp_path):
    (tmp_path / "buttonmap.json").write_text(json.dumps({"left": "noise_control", "right": "volume"}))
    sent = []

    async def send(l, r): sent.append((l, r))
    await ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus()).recover()
    assert sent == [("noise_control", "volume")] and not (tmp_path / "buttonmap.json").exists()


async def test_send_failure_is_reported_not_raised(tmp_path):
    async def send(l, r): raise RuntimeError("buds gone")
    ev = EventBus()
    await ButtonMapGuard(tmp_path / "buttonmap.json", send, ev).apply("volume", "volume", "other_l", "other_r")
    assert ev.recent(types={"error"})


async def test_failed_restore_keeps_the_file_so_next_start_retries(tmp_path):
    (tmp_path / "buttonmap.json").write_text(json.dumps({"left": "volume", "right": "volume"}))

    async def send(l, r): raise RuntimeError("buds gone")
    await ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus()).restore()
    assert (tmp_path / "buttonmap.json").exists()


async def test_sidekick_restores_crashed_mapping_before_anything_else(tmp_path):
    from buds_assistant.core.config import Config
    from buds_assistant.intelligence.llm import FakeLLM
    from test_dashboard import _make
    sk = _make(Config(data_dir=tmp_path, button_remap=True), FakeLLM())
    (tmp_path / "buttonmap.json").write_text(json.dumps({"left": "noise_control", "right": "volume"}))
    sent = []

    async def send(l, r): sent.append((l, r))
    sk.buttons.send = send
    await sk._init_buttons()
    assert sent == [("noise_control", "volume")] and not (tmp_path / "buttonmap.json").exists()


async def test_remap_is_off_by_default(tmp_path):
    from buds_assistant.core.config import Config
    from buds_assistant.intelligence.llm import FakeLLM
    from test_dashboard import _make
    sk = _make(Config(data_dir=tmp_path), FakeLLM())

    class L:                                                   # a link whose state already knows the touch options
        class state:
            snapshot = staticmethod(lambda: {"touch_option_l": "noise_control", "touch_option_r": "noise_control"})
    sk.link = L
    sent = []

    async def send(l, r): sent.append((l, r))
    sk.buttons.send = send
    await sk._init_buttons()
    assert sent == [] and not (tmp_path / "buttonmap.json").exists()
