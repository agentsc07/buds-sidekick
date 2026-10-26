"""`buds-sidekick setup`: check Ollama, pull the language models, fetch the speaker model, warm the speech models.

Safe to run again; it only downloads what is missing. Nothing is sent anywhere except the model downloads themselves.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from buds_assistant.core.config import APP_HOME, SPEAKER_MODEL_URL, Config


def _say(msg: str) -> None:
    print(msg, flush=True)


def ollama_models() -> set[str] | None:
    """Names of the models Ollama already has, or None if its server is not reachable."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            return {m["name"] for m in json.load(r).get("models", [])}
    except Exception:
        return None


def _have(name: str, have: set[str]) -> bool:
    return name in have or f"{name}:latest" in have


def fetch_speaker_model(dest: Path) -> bool:
    if dest.exists():
        _say(f"  voice model: already there ({dest.stat().st_size // 1_000_000} MB)")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    _say("  voice model: downloading (38 MB)...")
    try:
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(SPEAKER_MODEL_URL, tmp)
        tmp.rename(dest)
        return True
    except Exception as exc:
        _say(f"  could not download the voice model: {exc}\n  Download it by hand from {SPEAKER_MODEL_URL}\n  and put it at {dest}")
        return False


def warm_speech(cfg: Config) -> None:
    _say(f"  speech recognition: fetching '{cfg.whisper_model}' and the language detector (first time only)...")
    try:
        from faster_whisper import WhisperModel
        for name in (cfg.whisper_model, "tiny"):
            WhisperModel(name, device="cpu", compute_type="int8")
    except Exception as exc:
        _say(f"  could not prepare speech recognition: {exc}")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    cfg = Config.load(None)
    ok = True
    _say("Buds Sidekick setup\n")
    _say("1. Language models (Ollama)")
    have = ollama_models()
    if have is None:
        if shutil.which("ollama") is None:
            _say("  Ollama is not installed. Get it from https://ollama.com/download, open it once, then run this again.")
            _say("  (You can still try the dashboard: buds-sidekick --simulate)")
            ok = False
        else:
            _say("  Ollama is installed but not running. Open the Ollama app, then run this again.")
            ok = False
    else:
        wanted = [cfg.chat_model, cfg.embed_model] + ([cfg.translate_model] if cfg.translate_model != cfg.chat_model else [])
        for name in wanted:
            if _have(name, have):
                _say(f"  {name}: ready")
            elif "--check" in args:
                _say(f"  {name}: missing"); ok = False
            else:
                _say(f"  {name}: pulling (this can take several minutes)...")
                ok = subprocess.run(["ollama", "pull", name]).returncode == 0 and ok
    _say("\n2. Voice model")
    if "--check" not in args:
        ok = fetch_speaker_model(cfg.speaker_model) and ok
    else:
        _say(f"  voice model: {'ready' if cfg.speaker_model.exists() else 'missing'}")
        ok = cfg.speaker_model.exists() and ok
    if "--check" not in args:
        _say("\n3. Speech recognition")
        warm_speech(cfg)
    _say(f"\nYour data lives in: {APP_HOME}")
    _say("\nAll set. Start it with:  buds-sidekick" if ok else "\nSome steps need attention (see above). Re-run:  buds-sidekick setup")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
