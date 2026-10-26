"""Experiment runner against the simulator (no hardware)."""
import asyncio
import shutil
from pathlib import Path

import pytest

from budslab.core import experiments as X
from budslab.core.lab import Config, Lab
from budslab.protocol import commands as C
from budslab.protocol.frames import FrameCodec

CATALOG = Path(__file__).parent.parent / "experiments.yaml"


@pytest.fixture
async def lab(tmp_path):
    cfg = Config(data_dir=tmp_path, catalog=CATALOG, simulate=True, sim_speed=25.0)
    lab = Lab(cfg)
    for e in lab.catalog:                      # keep the suite fast: sim reacts within ~0.1 s at 25x
        e.timeout_seconds = min(e.timeout_seconds, 2.5)
    lab.runner.PAUSE_DEFAULT = 0.1
    await lab.start()
    for _ in range(100):
        if lab.transport.connected:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)                   # initial status snapshot
    yield lab
    await lab.stop()


async def run_one(lab, exp_id, confirm=False, wait=6.0):
    await lab.runner.start_run(ids=[exp_id])
    if confirm:
        await lab.runner.confirm()
    for _ in range(int(wait / 0.05)):
        await asyncio.sleep(0.05)
        r = lab.runner.results.get(exp_id)
        if r and lab.runner.state != "armed":
            return r
    raise AssertionError(f"{exp_id} did not finish: {lab.runner.state}")


async def test_touch_verified_with_side_and_gesture(lab):
    r = await run_one(lab, "touch-single-l")
    assert r["status"] == X.VERIFIED and r["matched"][0]["side"] == "L" and r["matched"][0]["detail"] == "single"
    r = await run_one(lab, "touch-double-r")
    assert r["status"] == X.VERIFIED and r["matched"][0]["side"] == "R"


async def test_wear_sequence_verified(lab):
    r = await run_one(lab, "wear-remove-l")
    assert r["status"] == X.VERIFIED
    assert {(m["side"], m["detail"]) for m in r["matched"]} == {("L", "out"), ("L", "in_ear")}


async def test_not_observed_when_nothing_happens(lab):
    r = await run_one(lab, "touch-swipe")
    assert r["status"] == X.NOT_OBSERVED


async def test_unknown_signal_saved_and_correlated(lab):
    r = await run_one(lab, "case-open")
    assert r["status"] == X.UNKNOWN_SIGNAL
    from budslab.core import report
    rows = report.unknown_table(lab.store, True, lab.session_id)
    assert rows and rows[0]["msg_id"] == 0xF1 and "case-open" in rows[0]["actions"]


async def test_commands_need_toggle_then_verify_and_undo(lab):
    await lab.runner.start_run(ids=["noise-anc-on"])
    with pytest.raises(C.CommandError):
        await lab.runner.confirm()               # read-only by default
    await lab.runner.abort()
    lab.commands.set_enabled(True)
    assert lab.state.snapshot()["noise_mode"] == "off"
    r = await run_one(lab, "noise-anc-on", confirm=True)
    assert r["status"] == X.VERIFIED
    await asyncio.sleep(0.5)
    assert lab.state.snapshot()["noise_mode"] == "off"                 # undone
    cmds = lab.store.q("SELECT name, status, latency_ms FROM commands")
    assert [c["status"] for c in cmds] == ["acked", "acked"] and all(c["latency_ms"] > 0 for c in cmds)


async def test_rejected_command_is_partial(lab):
    lab.commands.set_enabled(True)
    r = await run_one(lab, "cmd-ambient-volume", confirm=True)
    assert r["status"] == X.PARTIAL
    assert lab.store.q("SELECT status FROM commands")[0]["status"] == "rejected"


async def test_lock_suppression_experiment(lab):
    lab.commands.set_enabled(True)
    r = await run_one(lab, "touch-locked-l", confirm=True)
    assert r["status"] == X.VERIFIED                                    # no media key arrived while locked
    await asyncio.sleep(0.5)
    assert lab.state.snapshot()["touch_locked"] is False                # undone


async def test_find_my_needs_confirmation_and_is_stopped(lab):
    lab.commands.set_enabled(True)
    await lab.runner.start_run(ids=["cmd-find-my"])
    assert lab.runner.state == "awaiting_confirm" and "LOUD" in lab.runner.public_state()["warning"]
    await lab.runner.confirm()
    for _ in range(200):
        await asyncio.sleep(0.05)
        if lab.runner.state != "armed":
            break
    await asyncio.sleep(0.5)
    assert lab.commands.find_my_active is False
    names = [c["name"] for c in lab.store.q("SELECT name FROM commands")]
    assert names == ["find_my_start", "find_my_stop"]


async def test_skip_and_manual_verify_and_queue(lab):
    await lab.runner.start_run(ids=["touch-swipe", "touch-single-r"])
    await lab.runner.skip()
    assert lab.runner.results["touch-swipe"]["status"] == X.SKIPPED
    await asyncio.sleep(0.5)                                            # auto-advance
    assert lab.runner.current.id == "touch-single-r"
    await lab.runner.mark_verified()
    assert lab.runner.results["touch-single-r"] == lab.runner.last_result
    assert lab.runner.results["touch-single-r"]["manual"] is True


async def test_nothing_outside_allowlist_reaches_transport(lab):
    codec = FrameCodec()
    for bad_id in (80, 82, 176, 212):
        with pytest.raises(C.CommandError):
            await lab._send_bytes(codec.encode(bad_id, b""))
    with pytest.raises(C.CommandError):
        await lab._send_bytes(b"\x01\x02\x03")


async def test_matrix_and_exports(lab, tmp_path):
    from budslab.core import report
    await run_one(lab, "touch-single-l")
    m = report.capability_matrix(lab.store, lab.catalog, include_simulated=True)
    row = next(r for r in m["capabilities"] if r["id"] == "touch-single-l")
    assert row["status"] == "Verified" and row["reliability"] == "1 of 1 attempts" and row["layer"] == "B"
    # simulator sessions are excluded from evidence unless asked for
    m2 = report.capability_matrix(lab.store, lab.catalog, include_simulated=False)
    assert m2["sessions"] == [] and all(r["status"] == "Not tested" for r in m2["capabilities"])
    out = report.write_exports(lab.store, lab.catalog, tmp_path / "exp", tmp_path / "docs" / "pf.md", True)
    assert Path(out["json"]).exists() and "Verified" in Path(out["md"]).read_text()
