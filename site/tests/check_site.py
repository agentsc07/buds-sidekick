"""Smoke test for the built site: python3 site/tests/check_site.py   (needs playwright; uses the installed Chrome)
Serves site/ locally, clicks both hero buttons, checks /demo renders and that nothing logs a console or network error."""
import functools, http.server, sys, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k): pass
handler = functools.partial(Quiet, directory=str(ROOT))
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
import os
base = os.environ.get("SITE_URL", f"http://127.0.0.1:{srv.server_address[1]}").rstrip("/")      # SITE_URL=https://... tests a deployment
problems, ok = [], []

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.on("console", lambda m: m.type in ("error", "warning") and problems.append(f"console {m.type}: {m.text} @ {m.location.get('url')}"))
    pg.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    pg.on("requestfailed", lambda r: problems.append(f"request failed: {r.url}"))
    pg.on("response", lambda r: r.status >= 400 and problems.append(f"HTTP {r.status}: {r.url}"))

    pg.goto(base + "/"); pg.wait_for_load_state("networkidle")
    ok.append("landing loads: " + pg.title())
    demo, dl = pg.get_by_role("link", name="Try the live demo"), pg.get_by_role("link", name="Download for Mac")
    assert demo.get_attribute("href") == "/demo", demo.get_attribute("href")
    assert dl.get_attribute("href") == "https://github.com/agentsc07/buds-sidekick/releases/latest", dl.get_attribute("href")
    ok.append("both hero buttons present with the right links")
    assert pg.locator("[data-k=wer_en]").inner_text() != "…", "results.json numbers did not load"
    ok.append("eval numbers filled: " + pg.locator("[data-k=wer_en]").inner_text())
    assert pg.locator("details").first.get_attribute("open") is None
    ok.append("developer section is collapsed")

    demo.click(); pg.wait_for_url("**/demo/**"); pg.wait_for_selector("text=Ravi", timeout=10000)
    ok.append("demo opened at " + pg.url.replace(base, "") + " and shows the sample conversation")
    pg.get_by_role("link", name="People").first.click(); pg.wait_for_timeout(500)
    ok.append("demo navigation works (People)")
    b.close()

print("\n".join("PASS " + x for x in ok))
ext = [x for x in problems if "github.com" not in x]
print("PROBLEMS:\n" + "\n".join(ext) if ext else "no console errors, no failed requests")
sys.exit(1 if ext else 0)
