from budslab.protocol.frames import EOM, SOM, Frame, FrameCodec, Junk, crc16_xmodem

from conftest import FE_FRAME


def test_crc_check_value():
    assert crc16_xmodem(b"123456789") == 0x31C3          # CRC-16/XMODEM standard check value


def test_decode_real_fe_frame():
    (f,) = FrameCodec().feed(FE_FRAME)
    assert isinstance(f, Frame) and f.crc_ok
    assert f.msg_id == 97 and len(f.payload) == 46
    assert f.type_bit and not f.fragment
    assert f.raw == FE_FRAME


def test_encode_matches_real_frame_byte_for_byte():
    (f,) = FrameCodec().feed(FE_FRAME)
    assert FrameCodec().encode(f.msg_id, f.payload, type_bit=True) == FE_FRAME


def test_roundtrip_various_payloads():
    c = FrameCodec()
    for pid, payload in [(120, b"\x01"), (81, b"\x78\x00"), (160, b""), (97, bytes(range(200)))]:
        (f,) = FrameCodec().feed(c.encode(pid, payload))
        assert (f.msg_id, f.payload, f.crc_ok) == (pid, payload, True)


def test_bad_crc_is_flagged_not_dropped():
    bad = bytearray(FE_FRAME)
    bad[10] ^= 0xFF
    (f,) = FrameCodec().feed(bytes(bad))
    assert not f.crc_ok and f.msg_id == 97


def test_streaming_split_and_concatenated():
    c = FrameCodec()
    two = FE_FRAME + c.encode(119, b"\x01")
    out = []
    for i in range(0, len(two), 5):                       # arbitrary chunking
        out += c.feed(two[i:i + 5])
    frames = [x for x in out if isinstance(x, Frame)]
    assert [f.msg_id for f in frames] == [97, 119]


def test_resync_after_garbage():
    out = FrameCodec().feed(b"\x00\x01\x02" + FE_FRAME)
    assert isinstance(out[0], Junk) and isinstance(out[1], Frame)


def test_bad_eom_is_junk_then_recovers():
    broken = bytearray(FE_FRAME)
    broken[-1] = 0x00
    out = FrameCodec().feed(bytes(broken) + FE_FRAME)
    assert any(isinstance(x, Junk) for x in out)
    assert sum(isinstance(x, Frame) and x.crc_ok for x in out) == 1


def test_flags_and_constants():
    raw = FrameCodec().encode(1, b"", type_bit=True, fragment=True)
    assert raw[0] == SOM and raw[-1] == EOM
    (f,) = FrameCodec().feed(raw)
    assert f.type_bit and f.fragment


def test_legacy_framing_roundtrip():
    c = FrameCodec(0xFE, 0xEE, True)
    (f,) = c.feed(c.encode(0x60, b"\x01\x02"))
    assert f.crc_ok and f.payload == b"\x01\x02"
