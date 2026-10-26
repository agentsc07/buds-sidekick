from budslab.protocol.frames import Frame, FrameCodec
from budslab.protocol.messages import decode

from conftest import FE_FRAME


def test_real_fe_extended_status_matches_reference_expectations():
    # expected values are the ones asserted by the reference project's Buds FE test
    (f,) = FrameCodec().feed(FE_FRAME)
    d = decode(f)
    assert d.known and d.name == "EXTENDED_STATUS_UPDATED"
    x = d.fields
    assert (x["revision"], x["battery_l"], x["battery_r"]) == (2, 58, 89)
    assert x["placement_l"] == x["placement_r"] == 1 and x["battery_case"] == 0
    assert x["touch_locked"] is False and x["touch_option_l"] == x["touch_option_r"] == "volume"
    assert x["noise_mode"] == "off" and x["eq_mode"] == 0 and x["ambient_volume"] == 1
    assert not (x["charging_l"] or x["charging_r"] or x["charging_case"])
    assert x["touch_single_on"] and x["touch_double_on"] and x["touch_triple_on"] and x["touch_hold_on"]
    assert not x["touch_double_call_on"]


def test_unknown_id_decodes_to_raw_without_crashing():
    d = decode(Frame(0xF1, b"\x01\x02"))
    assert not d.known and d.fields["payload_hex"] == "0102" and d.confidence == "Unknown"


def test_truncated_payload_does_not_raise():
    d = decode(Frame(97, b"\x02\x06"))
    assert not d.known and d.error


def test_resp_and_ack():
    d = decode(Frame(81, bytes([120, 0])))
    assert d.fields["action_name"] == "NOISE_CONTROLS" and d.fields["result_name"] == "SUCCESS"
    assert decode(Frame(66, bytes([144, 1, 2]))).fields["action_name"] == "LOCK_TOUCHPAD"
