"""Frame captured from a real Buds FE over RFCOMM (macOS, 2026-09-29)."""
import pathlib

from budslab.protocol.frames import FrameCodec
from budslab.protocol.messages import decode

RAW = (pathlib.Path(__file__).parent / "fe_ext_status_rev3_live.bin").read_bytes()


def test_live_rev3_frame():
    (f,) = FrameCodec().feed(RAW)
    assert f.crc_ok and f.msg_id == 97 and len(f.payload) == 48
    assert f.flags == 0x0800 and not f.type_bit           # differs from the reference's 0x1000 sample
    x = decode(f).fields
    assert (x["revision"], x["battery_l"], x["battery_r"], x["battery_case"]) == (3, 100, 100, 42)
    assert (x["placement_l"], x["placement_r"]) == (2, 3)   # left out, right in case (as held when captured)
