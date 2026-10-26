"""`buds-sidekick app`: Sidekick in its own window (no Terminal, no browser needed).

The server runs as a child process (the buds link needs its own main thread); this process shows the dashboard in a native window and
stops the server when the window closes. "Open in Browser" is in the menu. Mode: real buds if a Galaxy Buds is connected, else practice mode.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from buds_assistant.core.config import APP_HOME

PORT = int(os.environ.get("BUDS_PORT", "8770"))
URL = f"http://127.0.0.1:{PORT}"
SPLASH = """<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#0b0a12;color:#f2f0fa;font:16px -apple-system,sans-serif">
<div style="text-align:center"><div style="width:56px;height:56px;border-radius:16px;margin:0 auto 18px;background:linear-gradient(135deg,#8b6cff,#ff7a59)"></div>
<div style="font-size:22px;font-weight:600">Buds Sidekick</div><p style="color:#a9a5c0">%s</p></div></body></html>"""


def buds_connected() -> bool:
    """Is a Galaxy Buds currently connected to this Mac? (System report; a second or two.)"""
    try:
        out = subprocess.run(["system_profiler", "SPBluetoothDataType"], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return False
    head, _, rest = out.partition("Not Connected:")
    return "Galaxy Buds" in head.partition("Connected:")[2]


def alive() -> bool:
    try:
        urllib.request.urlopen(URL + "/api/v2/state", timeout=1.5).read()
        return True
    except Exception:
        return False


def start_server(simulate: bool) -> subprocess.Popen | None:
    if alive():
        return None                                        # already running (e.g. from a terminal): just show it
    logs = APP_HOME / "logs"; logs.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "buds_assistant.sidekick", "--port", str(PORT)] + (["--simulate"] if simulate else [])
    return subprocess.Popen(cmd, stdout=open(logs / "sidekick.log", "ab"), stderr=subprocess.STDOUT)


def main(argv: list[str] | None = None) -> int:
    import webview
    args = argv if argv is not None else sys.argv[1:]
    simulate = "--simulate" in args or ("--buds" not in args and not buds_connected())
    window = webview.create_window("Buds Sidekick", html=SPLASH % ("Starting up…" if not alive() else "Opening…"), width=1280, height=820, min_size=(900, 600),
                                   background_color="#0b0a12")
    proc: list[subprocess.Popen | None] = [None]

    def boot() -> None:
        proc[0] = start_server(simulate)
        for i in range(240):
            if alive():
                window.load_url(URL)
                if os.environ.get("BUDS_APP_TEST_SECONDS"):      # smoke test: close by itself
                    time.sleep(float(os.environ["BUDS_APP_TEST_SECONDS"])); window.destroy()
                return
            if proc[0] is not None and proc[0].poll() is not None:
                window.load_html(SPLASH % f"Sidekick could not start. Details: {APP_HOME / 'logs' / 'sidekick.log'}"); return
            if i == 20:
                window.load_html(SPLASH % "Still starting (the first launch loads the speech models)…")
            time.sleep(0.5)
        window.load_html(SPLASH % "Sidekick did not start in time. Check the log in Application Support.")

    menu = None
    try:
        from webview.menu import Menu, MenuAction
        menu = [Menu("Sidekick", [MenuAction("Open in Browser", lambda: webbrowser.open(URL)),
                                  MenuAction("Show Log Folder", lambda: subprocess.run(["open", str(APP_HOME / "logs")]))])]
    except Exception:
        pass
    try:
        webview.start(boot, menu=menu) if menu else webview.start(boot)
    finally:
        if proc[0] is not None and proc[0].poll() is None:
            proc[0].terminate()
            try:
                proc[0].wait(8)
            except subprocess.TimeoutExpired:
                proc[0].kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
