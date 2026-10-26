from pathlib import Path

import pytest

from buds_assistant.controls.gestures import GestureRecognizer
from buds_assistant.core.modes import load_profiles

GEST = Path(__file__).resolve().parents[2] / "buds_assistant" / "config" / "sidekick_gestures.yaml"
TABLE = [("L:single", "ask"), ("L:double", "replay"), ("L:triple", "private_toggle"),
         ("R:single", "mark"), ("R:double", "autopilot_toggle"), ("R:triple", "who")]


@pytest.mark.parametrize("profile", ["ear", "remote"])
@pytest.mark.parametrize("token,action", TABLE)
def test_tap_map(profile, token, action):
    bindings, timeout, deb = load_profiles(GEST)[profile]
    r = GestureRecognizer(bindings, timeout, deb)
    got = r.feed(token, 10.0) or r.poll(10.0 + timeout + 0.01)
    assert [m.binding.action for m in got] == [action]


@pytest.mark.parametrize("profile", ["ear", "remote"])
@pytest.mark.parametrize("token,action", [("L:hold_start", "interpreter_toggle"), ("R:hold_start", "listen_toggle")])
def test_hold_toggles_once_per_burst(profile, token, action):
    bindings, timeout, deb = load_profiles(GEST)[profile]
    r = GestureRecognizer(bindings, timeout, deb)
    fired = [m for t in (0.0, 0.2, 0.5, 0.9) for m in r.feed(token, t)]
    assert [m.binding.action for m in fired] == [action]


def test_no_sequences_left():
    for profile in load_profiles(GEST).values():
        assert all(len(b.pattern) == 1 for b in profile[0])
