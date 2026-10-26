import numpy as np

from buds_assistant.audio.segmenter import Segmenter

SR = 16000
rng = np.random.default_rng(0)


def noise(s, level=0.002):
    return (rng.standard_normal(int(s * SR)) * level * 32768).astype(np.int16)


def speech(s, level=0.15):
    t = np.arange(int(s * SR)) / SR
    sig = sum(np.sin(2 * np.pi * f * t) for f in (180, 360, 540)) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))
    return (sig / 3 * level * 32768).astype(np.int16)


def run(parts):
    seg, out = Segmenter(), []
    for p in parts:
        for i in range(0, p.size, 320):
            out += seg.feed(p[i:i + 320])
    out += seg.flush()
    return out


def test_one_utterance_with_preroll():
    segs = run([noise(1.0), speech(1.5), noise(1.5)])
    assert len(segs) == 1
    s = segs[0]
    assert 0.7 <= s.t0 <= 1.0           # speech starts at 1.0 s; ~0.25 s pre-roll is included
    assert 2.4 < s.t1 < 3.0 and 1.5 < s.seconds < 2.2


def test_two_utterances_one_second_apart():
    segs = run([noise(1.0), speech(1.2), noise(1.0), speech(1.0), noise(1.5)])
    assert len(segs) == 2 and segs[1].t0 > segs[0].t1


def test_click_and_steady_noise_yield_nothing():
    click = np.zeros(int(0.2 * SR), dtype=np.int16)
    click[:200] = 12000
    assert run([noise(1.0), click, noise(2.0)]) == []
    assert run([noise(5.0, level=0.03)]) == []            # a loud steady room is not speech


def test_long_speech_is_split():
    segs = run([noise(0.6), speech(45.0), noise(1.0)])
    assert len(segs) >= 2 and all(s.seconds <= 20.5 for s in segs)


def run_with(parts, **kw):
    seg, out = Segmenter(**kw), []
    for p in parts:
        for i in range(0, p.size, 320):
            out += seg.feed(p[i:i + 320])
    out += seg.flush()
    return out


def test_interpreter_hears_quiet_speech_from_a_speaker_across_the_room():
    """Real use: a video playing on the Mac speakers, picked up by the Mac mic, was detected only now and then."""
    from buds_assistant.core.modes import INTERPRETER_SEG
    parts = [noise(1.0, 0.003), speech(2.0, 0.012), noise(1.0, 0.003), speech(2.0, 0.012), noise(1.0, 0.003)]
    assert len(run_with(parts, **INTERPRETER_SEG)) == 2


def test_interpreter_catches_speech_that_is_already_playing_when_it_starts():
    from buds_assistant.core.modes import INTERPRETER_SEG
    parts = [speech(3.0, 0.06), noise(1.2, 0.004), speech(2.0, 0.06), noise(1.2, 0.004)]
    assert len(run_with(parts, **INTERPRETER_SEG)) >= 1
    assert len(run_with(parts, **INTERPRETER_SEG)) == 2


def test_normal_listening_is_not_made_trigger_happy():
    assert len(run([noise(3.0, 0.003)])) == 0
    assert len(run([noise(1.0), speech(1.5), noise(1.5)])) == 1


def _dip_speech(first, gap, second, level=0.06):
    return [noise(0.6, 0.003), speech(first, level), noise(gap, 0.003), speech(second, level), noise(1.0, 0.003)]


def test_interpreter_cuts_a_long_sentence_at_a_brief_pause_so_the_first_half_can_be_translated_early():
    from buds_assistant.core.modes import INTERPRETER_SEG
    parts = _dip_speech(3.0, 0.25, 3.0)
    assert len(run_with(parts, **INTERPRETER_SEG)) == 2                        # clause by clause
    assert len(run_with(parts)) == 1                                           # normal listening keeps the sentence whole


def test_a_short_phrase_is_not_chopped_at_a_tiny_dip():
    from buds_assistant.core.modes import INTERPRETER_SEG
    assert len(run_with(_dip_speech(1.0, 0.25, 1.0), **INTERPRETER_SEG)) == 1
