#!/bin/bash
# Start Buds Sidekick (real buds). Phone Bluetooth off first. Add --simulate for no buds. Dashboard: http://127.0.0.1:8770
cd "$(dirname "$0")" && exec ../.venv/bin/python -m buds_assistant.sidekick --port 8770 "$@"
