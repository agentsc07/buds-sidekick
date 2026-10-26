#!/bin/bash
# Launcher inside Buds Sidekick.app: first run installs into ~/Library/Application Support/Buds Sidekick/venv, then runs in Terminal.
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
HOME_DIR="$HOME/Library/Application Support/Buds Sidekick"
SCRIPT="$HOME_DIR/run.command"
mkdir -p "$HOME_DIR"
cat > "$SCRIPT" <<RUN
#!/bin/bash
cd "\$HOME"
clear; echo "Buds Sidekick"; echo
VENV="$HOME_DIR/venv"
WHEEL=\$(ls "$RES"/buds_sidekick-*.whl | head -1)
if [ ! -x "\$VENV/bin/buds-sidekick" ] || [ "\$WHEEL" -nt "\$VENV/.installed" ]; then
  PY=""
  for c in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "\$c" >/dev/null 2>&1 && "\$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then PY="\$c"; break; fi
  done
  if [ -z "\$PY" ]; then echo "Python 3.11 or newer is needed. Install it with:  brew install python  (or from python.org), then open this app again."; read -r -p "Press Enter to close"; exit 1; fi
  echo "First run: installing (a few minutes, needs internet)..."
  "\$PY" -m venv "\$VENV" && "\$VENV/bin/pip" install -q "\$WHEEL" && touch "\$VENV/.installed" || { echo "Install failed."; read -r -p "Press Enter to close"; exit 1; }
  "\$VENV/bin/buds-sidekick" setup
fi
echo; echo "Starting. Your browser will open. Close this window or press Ctrl+C to stop."
(sleep 6; open http://127.0.0.1:8770) &
read -r -t 8 -p "Using your Galaxy Buds? Press Enter within 8 s for buds mode, otherwise practice mode starts: " ans && MODE="" || MODE="--simulate"
exec "\$VENV/bin/buds-sidekick" \$MODE
RUN
chmod +x "$SCRIPT"
open -a Terminal "$SCRIPT"
