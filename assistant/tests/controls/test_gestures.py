from buds_assistant.controls.gestures import Binding, GestureRecognizer

B = [Binding("ask", ("L:double",), "ask"), Binding("rep", ("R:double",), "repeat"),
     Binding("time", ("L:single", "R:single"), "time"), Binding("hold", ("L:hold",), "ask_hold", "hold"),
     Binding("trip", ("L:triple",), "battery")]


def acts(ms):
    return [(m.binding.action, m.phase) for m in ms]


def test_single_gesture_fires_immediately():
    r = GestureRecognizer(B)
    assert acts(r.feed("L:double", 0)) == [("ask", "fire")]
    assert acts(r.feed("R:double", 1)) == [("repeat", "fire")]


def test_sequence_and_timeout():
    r = GestureRecognizer(B, 0.7)
    assert r.feed("L:single", 0) == []                       # waits: could become the L,R sequence
    assert acts(r.feed("R:single", 0.4)) == [("time", "fire")]
    assert r.feed("L:single", 5) == []                       # first half only ...
    assert r.poll(5.9) == []                                 # ... times out with nothing bound to it alone
    assert r.feed("R:single", 6.0) == []                     # a late second half does not complete it


def test_hold_start_end():
    r = GestureRecognizer(B)
    assert acts(r.feed("L:hold_start", 0)) == [("ask_hold", "start")]
    assert acts(r.feed("L:hold_end", 3)) == [("ask_hold", "end")]
    assert r.feed("R:hold_start", 4) == []                   # no binding on the right


def test_unbound_gesture_ignored_and_wrong_continuation_restarts():
    r = GestureRecognizer(B)
    assert r.feed("R:triple", 0) == []
    r.feed("L:single", 1)
    assert acts(r.feed("L:triple", 1.2)) == [("battery", "fire")]   # wrong continuation, but valid on its own


def test_exact_match_waits_when_longer_exists():
    b = [Binding("a", ("L:single",), "time"), Binding("b", ("L:single", "R:single"), "battery")]
    r = GestureRecognizer(b, 0.7)
    assert r.feed("L:single", 0) == []
    assert acts(r.poll(0.8)) == [("time", "fire")]


def test_hold_toggle_treats_a_burst_as_one_hold():
    b = [Binding("t", ("L:hold",), "ask_toggle", "toggle")]
    r = GestureRecognizer(b, hold_debounce=1.2)
    assert acts(r.feed("L:hold_start", 0.0)) == [("ask_toggle", "toggle")]
    # the buds send repeated start/end events during one continuous press
    for t, tok in [(0.3, "L:hold_end"), (0.6, "L:hold_start"), (0.9, "L:hold_end"), (1.5, "L:hold_start"), (2.0, "L:hold_end")]:
        assert r.feed(tok, t) == []
    assert acts(r.feed("L:hold_start", 4.0)) == [("ask_toggle", "toggle")]      # second, separate hold
    assert r.feed("R:hold_start", 4.1) == []                                    # right has no binding


def test_load_bindings_defaults(tmp_path):
    from pathlib import Path
    from buds_assistant.controls.gestures import load_bindings
    bs, timeout, deb = load_bindings(Path(__file__).resolve().parents[2] / "buds_assistant" / "config" / "gestures.yaml")
    assert timeout == 0.7 and deb == 1.2
    assert {b.action for b in bs if b.mode == "toggle"} == {"ask_toggle", "note_toggle"}
