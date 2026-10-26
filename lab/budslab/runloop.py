"""macOS: IOBluetooth delivers its delegate callbacks on the MAIN thread's run loop.

So on macOS the main thread pumps the Cocoa run loop (and executes queued IOBluetooth calls) while the
asyncio/uvicorn application runs in a worker thread. Elsewhere this simply calls the target.
"""
from __future__ import annotations

import queue
import sys
import threading
from typing import Callable

_Q: queue.Queue = queue.Queue()


def post(fn: Callable[[], None]) -> None:
    """Run fn on the main (run loop) thread."""
    _Q.put(fn)


def run_main(target: Callable[[], None], stop: Callable[[], None]) -> None:
    if sys.platform != "darwin":
        target()
        return
    import signal
    from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop

    def _term(*_a):
        raise KeyboardInterrupt      # SIGTERM (kill, closing the terminal) takes the clean-shutdown path too
    signal.signal(signal.SIGTERM, _term)
    err: list[BaseException] = []

    def work() -> None:
        try:
            target()
        except BaseException as exc:  # noqa: BLE001
            err.append(exc)

    t = threading.Thread(target=work, name="app", daemon=True)
    t.start()
    import time
    stopped_at: float | None = None
    while t.is_alive():
        try:
            try:
                while True:
                    _Q.get_nowait()()
            except queue.Empty:
                pass
            NSRunLoop.currentRunLoop().runMode_beforeDate_(NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.02))
        except KeyboardInterrupt:
            if stopped_at is None:          # first Ctrl-C: ask the app to stop, but KEEP pumping so the
                stopped_at = time.time()    # RFCOMM channel is really closed (buds allow only one client)
                stop()
            else:
                break
        if stopped_at is not None and time.time() - stopped_at > 12:
            break
    if err and not isinstance(err[0], (KeyboardInterrupt, SystemExit)):
        raise err[0]
