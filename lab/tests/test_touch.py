from budslab.protocol.frames import Frame
from budslab.protocol.messages import decode

# payloads observed on a real Buds FE (left single tap, right single tap, left hold start / end)


def test_touch_on_buds_decoding():
    f = decode(Frame(45, bytes.fromhex("010120d9")))
    assert f.known and f.fields["side"] == "L" and f.fields["gesture"] == "single"
    assert decode(Frame(45, bytes.fromhex("000120d9"))).fields["side"] == "R"
    assert decode(Frame(45, bytes.fromhex("010520d9"))).fields["gesture"] == "hold_start"
    assert decode(Frame(45, bytes.fromhex("010720d9"))).fields["gesture"] == "hold_end"
