"""Minimal probe: connect RFCOMM and print raw frames for N seconds. Passive: transmits nothing.

    python -m budslab.probe [--device ADDR] [--seconds 60] [--channel N] [--legacy-framing]

Tap the buds, wear/remove them, open/close the case while it runs. Success looks like frames
with crc=OK and ids such as 96/97 (status). If you only see junk or no bytes: see README > Troubleshooting.
"""
from __future__ import annotations

import argparse
import asyncio
import time

from .protocol.frames import Frame, FrameCodec, Junk
from .protocol.messages import decode
from .transport.rfcomm import make_rfcomm


async def probe(args) -> None:
    t = make_rfcomm(args.device, args.channel)
    codec = FrameCodec(*((0xFE, 0xEE, True) if args.legacy_framing else ()))
    t0 = time.time()
    counts: dict[int, int] = {}
    raw_total = 0

    def on_state(s, info):
        print(f"[{time.time()-t0:6.1f}s] link: {s} {info if s != 'connected' else t.describe()}")

    def on_data(b: bytes):
        nonlocal raw_total
        raw_total += len(b)
        for item in codec.feed(b):
            ts = time.time() - t0
            if isinstance(item, Junk):
                print(f"[{ts:6.1f}s] JUNK ({item.reason}) {item.raw_hex}")
                continue
            d = decode(item)
            counts[item.msg_id] = counts.get(item.msg_id, 0) + 1
            print(f"[{ts:6.1f}s] rx id={item.msg_id:3d} {d.name:<28} crc={'OK ' if item.crc_ok else 'BAD'} "
                  f"len={len(item.payload):3d} {item.payload.hex()[:96]}")
            if d.known and d.fields:
                print(f"           {d.fields}")

    task = asyncio.create_task(t.run(on_data, on_state))
    try:
        await asyncio.sleep(args.seconds)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await t.close()
    print(f"\nDone. {raw_total} bytes; message ids seen: {dict(sorted(counts.items()))}")
    if not raw_total:
        print("No bytes received. Is another client holding the channel? Were the buds in range/out of the case?")


def main() -> None:
    from .runloop import run_main
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="auto")
    ap.add_argument("--channel", type=int)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--legacy-framing", action="store_true")
    args = ap.parse_args()
    run_main(lambda: asyncio.run(probe(args)), lambda: None)


if __name__ == "__main__":
    main()
