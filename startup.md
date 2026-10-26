# Startup: Buds Sidekick

## Prerequisites
- macOS on Apple silicon, 16 GB memory, Python 3.11+ (3.14 tested)
- [Ollama](https://ollama.com/download) installed and opened once
- Optional: Samsung Galaxy Buds FE (phone Bluetooth off, buds connected to the Mac)

## Install (end user)
```bash
brew install pipx && pipx ensurepath
pipx install "git+https://github.com/agentsc07/buds-sidekick.git"
buds-sidekick setup        # pulls the Ollama models, fetches the voice model, warms speech recognition
```

## Run
```bash
buds-sidekick --simulate   # no buds: practice mode
buds-sidekick              # real buds
```
Open **http://127.0.0.1:8770**. Stop with Ctrl+C. Your data is in `~/Library/Application Support/Buds Sidekick`.

## Run from a checkout (development)
```bash
python3 -m venv ~/.venvs/buds && ~/.venvs/buds/bin/pip install -e ".[test]"
cd assistant && ~/.venvs/buds/bin/python -m buds_assistant.sidekick --simulate
~/.venvs/buds/bin/python -m pytest -m "not slow"     # tests (~80 s); add -m slow for the real-model ones
```
Keep the virtualenv outside `Desktop/` and `Documents/`: iCloud evicts files there and Python then hangs while importing.

## Evaluation
`python -m buds_assistant.eval.submission_eval wer | latency | autopilot | record` (see `docs/validation/recording-script.md`).

## Common problems
| Symptom | Fix |
|---|---|
| Setup says "Thinking engine not running" | Open the Ollama app, then Check again |
| First answer takes 10-25 s | The model was asleep; it is warm after the first one. Close heavy apps (a busy Mac is 3-10x slower) |
| "Buds not connected" | Turn Bluetooth off on your phone, connect the buds in System Settings, restart |
| Python hangs at start (checkout) | The project or `.venv` is on iCloud Desktop; create the venv elsewhere |
| Port 8770 busy | `buds-sidekick --port 8771` |
