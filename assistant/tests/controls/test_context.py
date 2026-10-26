from buds_assistant.controls.context import GestureContext


def test_any_single_tap_stops_speech():
    c = GestureContext()
    assert c.intercept("R:single", 1.0, speaking=True) == "stop"
    assert c.intercept("R:double", 1.0, speaking=True) is None        # only singles stop


def test_whisper_window_single_and_double():
    c = GestureContext()
    c.open("whisper", 10.0)
    assert c.intercept("L:single", 12.0, False) == "tell_more"
    c.open("whisper", 10.0)
    assert c.intercept("R:double", 12.0, False) == "not_useful"       # does NOT fall through to autopilot toggle
    assert c.intercept("R:double", 12.5, False) is None               # window is consumed


def test_window_expires():
    c = GestureContext()
    c.open("whisper", 10.0)
    assert c.intercept("R:double", 14.5, False) is None               # > 4 s


def test_noted_window_double_undoes():
    c = GestureContext()
    c.open("noted", 20.0)
    assert c.intercept("L:double", 24.0, False) == "undo_commitment"
    c.open("noted", 20.0)
    assert c.intercept("L:double", 25.5, False) is None               # > 5 s


def test_replay_window_left_double_escalates():
    c = GestureContext()
    c.open("replay", 30.0)
    assert c.intercept("L:double", 35.0, False) == "catch_up"
    c.open("replay", 30.0)
    assert c.intercept("R:double", 35.0, False) is None


def test_precedence_speaking_beats_whisper():
    c = GestureContext()
    c.open("whisper", 40.0)
    assert c.intercept("L:single", 41.0, speaking=True) == "stop"
