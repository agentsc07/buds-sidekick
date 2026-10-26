#!/bin/bash
# Refresh site/demo from the real dashboard, and make it start in demo mode (fixture data, no backend).
set -e
cd "$(dirname "$0")"
rm -rf demo && cp -R ../assistant/buds_assistant/dashboard/web demo
python3 - <<'PY'
p = "demo/index.html"; s = open(p).read()
boot = '<script>if (!/[?&]demo=/.test(location.search)) history.replaceState(null, "", "?demo=1&state=autopilot" + location.hash);</script>\n'
icon = '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 32 32\'%3E%3Crect width=\'32\' height=\'32\' rx=\'9\' fill=\'%237c5cff\'/%3E%3C/svg%3E">\n'
open(p, "w").write(s.replace('<script type="module"', icon + boot + '<script type="module"', 1))
PY
