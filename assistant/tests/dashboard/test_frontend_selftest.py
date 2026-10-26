"""Runs the dashboard's browser self-test (web/selftest.html) in headless Chrome, if Chrome is installed."""
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WEB = Path(__file__).resolve().parents[2] / "buds_assistant" / "dashboard" / "web"


@pytest.mark.skipif(not Path(CHROME).exists(), reason="needs Google Chrome")
def test_store_event_handling_in_a_real_browser():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(WEB)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        out = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=4000", "--dump-dom",
                              f"http://127.0.0.1:{port}/selftest.html?demo=1"], capture_output=True, text=True, timeout=60).stdout
    finally:
        srv.terminate()
    body = re.search(r'<pre id="out">(.*?)</pre>', out, re.S)
    assert body, out[-500:]
    assert "FAIL" not in body.group(1) and "ALL-PASS" in body.group(1), body.group(1)
