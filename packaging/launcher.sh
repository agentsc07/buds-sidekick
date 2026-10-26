#!/bin/bash
# Launcher inside Buds Sidekick.app. First run: install into ~/Library/Application Support/Buds Sidekick/venv (with a dialog, no Terminal),
# then open Sidekick in its own window. Models are downloaded from inside the app (Setup, "Download what is missing").
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
HOME_DIR="$HOME/Library/Application Support/Buds Sidekick"
VENV="$HOME_DIR/venv"
LOG="$HOME_DIR/logs/install.log"
mkdir -p "$HOME_DIR/logs"
WHEEL=$(ls "$RES"/buds_sidekick-*.whl | head -1)

alert() { osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with title \"Buds Sidekick\" with icon caution" >/dev/null 2>&1; }

if [ ! -x "$VENV/bin/buds-sidekick" ] || [ "$WHEEL" -nt "$VENV/.installed" ]; then
  PY=""
  for c in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$c" ] && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then PY="$c"; break; fi
  done
  if [ -z "$PY" ]; then
    alert "Buds Sidekick needs Python 3.11 or newer. Install it from python.org (or with: brew install python), then open the app again."
    open "https://www.python.org/downloads/macos/"; exit 1
  fi
  osascript -e 'display dialog "Setting up Buds Sidekick for the first time.\n\nThis takes a few minutes and needs internet. The app opens by itself when it is ready." buttons {"OK"} default button 1 with title "Buds Sidekick" giving up after 900' >/dev/null 2>&1 &
  DLG=$!
  if "$PY" -m venv "$VENV" >"$LOG" 2>&1 && "$VENV/bin/pip" install -q "$WHEEL" >>"$LOG" 2>&1; then touch "$VENV/.installed"; else
    kill $DLG 2>/dev/null; alert "The install did not finish. Check your internet connection and open the app again. Details: $LOG"; exit 1
  fi
  kill $DLG 2>/dev/null
fi
exec "$VENV/bin/buds-sidekick" app
