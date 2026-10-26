import numpy as np

from buds_assistant.legacy.audio_io import EnergyVAD, Recording


def run(levels, dt=0.02, **kw):
    v = EnergyVAD(**kw)
    for i, r in enumerate(levels):
        s = v.feed(r, dt)
        if s in ("done", "timeout"):
            return s, i * dt
    return "running", len(levels) * dt


def test_speech_then_silence_ends():
    noise, speech = [0.002] * 20, [0.08] * 40
    state, t = run(noise + speech + [0.002] * 80)
    assert state == "done" and 1.0 < t < 2.2


def test_no_speech_times_out():
    assert run([0.002] * 400)[0] == "timeout"


def test_loud_room_raises_threshold():
    v = EnergyVAD()
    for _ in range(20):
        v.feed(0.03, 0.02)
    assert v.threshold >= 0.09          # steady 0.03 noise must not count as speech
    assert v.feed(0.03, 0.02) == "waiting" or not v.heard


def test_resample_to_16k():
    x = (np.sin(np.linspace(0, 200, 48000)) * 10000).astype(np.int16)
    out = Recording(x, 48000, True, "t").to_16k()
    assert abs(len(out) - 16000) <= 1 and out.dtype == np.float32
