import numpy as np

from buds_assistant.audio.capture import CHUNK, FileSource, RingBuffer, resample


def test_ring_buffer_is_bounded_and_returns_recent_audio():
    rb = RingBuffer(seconds=2, rate=16000)
    for i in range(10):                                   # 10 s of audio, value = second index
        rb.push(np.full(16000, i, dtype=np.int16))
    assert rb.seconds <= 3.0                              # never grows past capacity (+ one chunk)
    last = rb.last(1.0)
    assert last.size == 16000 and (last == 9).all()
    assert rb.last(2.0).size == 32000 and rb.last(2.0)[0] == 8


def test_last_longer_than_available_and_empty():
    rb = RingBuffer(seconds=8)
    assert rb.last(5).size == 0                           # empty buffer: no crash
    rb.push(np.ones(16000, dtype=np.int16))
    assert rb.last(5).size == 16000                       # asked for more than exists: what exists
    rb.clear()
    assert rb.seconds == 0 and rb.last(1).size == 0


def test_resize_clamps():
    rb = RingBuffer(seconds=8)
    rb.resize(1000)
    assert rb.capacity == 60 * 16000
    rb.resize(1)
    assert rb.capacity == 5 * 16000


def test_resample_48k_to_16k():
    x = (np.sin(np.linspace(0, 100, 48000)) * 8000).astype(np.int16)
    assert abs(resample(x, 48000).size - 16000) <= 1
    assert resample(x, 16000) is not None


def test_file_source_delivers_everything_in_order():
    audio = np.arange(CHUNK * 5, dtype=np.int16)
    got = []
    src = FileSource(audio=audio, tail_silence=0.0)
    src.start(got.append)
    assert src.done.wait(2)
    assert np.concatenate(got)[:audio.size].tolist() == audio.tolist()
