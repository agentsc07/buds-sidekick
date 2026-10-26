from buds_assistant.controls.touchfilter import TouchFilter


def test_taps_within_guard_after_wear_change_are_ignored():
    f = TouchFilter()
    f.note_wear(10.0)
    assert not f.accept("L:single", 10.5)
    assert f.accept("L:single", 11.1)


def test_pocket_burst_is_ignored():
    f = TouchFilter()
    results = [f.accept("L:single", 20.0 + i * 0.2) for i in range(5)]    # 5 taps in 0.8 s
    assert results[:3] == [True, True, True] and results[3:] == [False, False]


def test_slow_taps_are_fine():
    f = TouchFilter()
    assert all(f.accept("R:double", t) for t in (1.0, 2.5, 4.0, 5.5, 7.0))


def test_hold_burst_passes():
    f = TouchFilter()
    assert all(f.accept("L:hold_start", 30.0 + i * 0.1) for i in range(8))
