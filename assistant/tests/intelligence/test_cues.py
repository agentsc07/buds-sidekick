import numpy as np

from buds_assistant.legacy.audio_io import chime, make_cue


def test_chimes_are_soft_and_finite():
    for kind in ("ready", "done", "error"):
        x = chime(kind)
        assert x.dtype == np.float32 and 0.2 < len(x) / 16000 < 0.8
        assert 0.02 < np.max(np.abs(x)) < 0.5            # audible but never loud
        assert abs(x[0]) < 0.05 and abs(x[-1]) < 0.02    # no click at start or end


def test_cue_never_raises(tmp_path):
    make_cue("chime", {"ready": str(tmp_path / "missing.wav")})("ready")   # missing file: silently ignored
    make_cue("off")("done")
