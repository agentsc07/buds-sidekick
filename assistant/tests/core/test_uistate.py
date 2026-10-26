from buds_assistant.core.config import Config
from buds_assistant.core.events import EventBus
from buds_assistant.core.uistate import UiState


def test_reduces_events_into_one_snapshot_and_pushes_it():
    ev = EventBus(); ui = UiState(ev, Config())
    ev.publish("mode", mode="listen", placement="ear", memory_level="remember", autopilot=False, route="ear",
               conversation_id=3, ring_seconds=2.0)
    ev.publish("battery", left=80, right=79, case=50)
    ev.publish("wear", side="L", placement=1)
    ev.publish("model_state", chat="ready", embed="ready", translate="unloaded")
    s = ui.snapshot()
    assert s["mode"] == "listen" and s["buds"]["battery"]["left"] == 80 and s["models"]["chat"] == "ready"
    assert s["buds"]["wear"]["L"] == "in_ear" and s["autopilot"]["sensitivity"] == "proactive"
    assert ev.recent(types={"ui_state"})[-1]["data"]["mode"] == "listen"


def test_feed_keeps_last_30_decisions():
    ev = EventBus(); ui = UiState(ev, Config())
    for i in range(40):
        ev.publish("autopilot_decision", outcome="held_back", reason="too_soon", text=f"h{i}")
    feed = ui.snapshot()["autopilot"]["feed"]
    assert len(feed) == 30 and feed[-1]["text"] == "h39"


def test_buds_disconnect_sets_banner_and_reconnect_clears_it():
    ev = EventBus(); ui = UiState(ev, Config())
    ev.publish("buds", message="buds: error (timed out opening RFCOMM)")
    assert ui.snapshot()["banner"]
    ev.publish("buds", message="buds: connected")
    assert ui.snapshot()["banner"] is None


def test_ignores_its_own_ui_state_events():
    ev = EventBus(); UiState(ev, Config())
    ev.publish("battery", left=1, right=2, case=3)
    assert len(ev.recent(types={"ui_state"})) == 1                      # no feedback loop


def test_sensitivity_follows_config():
    cfg = Config(); ev = EventBus(); ui = UiState(ev, cfg)
    cfg.autopilot_sensitivity = "quiet"
    ev.publish("mode", mode="standby", placement="ear", memory_level="remember", autopilot=False, route="ear",
               conversation_id=None, ring_seconds=0)
    assert ui.snapshot()["autopilot"]["sensitivity"] == "quiet"
