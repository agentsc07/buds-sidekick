"""End-to-end Interpreter latency on synthetic speech: end of a phrase -> start of its translation.

    ../.venv/bin/python -m buds_assistant.eval.latency_bench [--lang te|en] [--gap 1.0]

Stop the app first (it shares Ollama and the CPU) and close other heavy programs: a busy Mac makes everything 3-10x slower.
Prints, per phrase, the stages the Interpreter itself reports (listen + recognise, queued, translate) and the end-to-end latency."""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import tempfile
import time
from pathlib import Path


async def run(lang: str, gap: float) -> None:
    from buds_assistant.audio.capture import FileSource
    from buds_assistant.core.config import Config
    from buds_assistant.audio.demo import demo_audio
    from ..sidekick import Sidekick
    cfg = Config(data_dir=Path(tempfile.mkdtemp()))
    sk = Sidekick(cfg, Path(__file__).resolve().parents[2] / "buds_assistant" / "config" / "sidekick_gestures.yaml", simulate=True, silent=True)
    sk.models.start = lambda: None
    await sk.start()
    load = os.getloadavg()[0]
    t = time.time()
    await sk.modes.set_mode("interpreter")
    print(f"load average {load:.1f}; interpreter ready in {time.time() - t:.1f}s {sk.models.state()}")
    audio, _ = demo_audio(gap=gap, language=lang)
    sk.pipeline.set_source(FileSource(audio=audio, realtime=True, speed=1.0))
    await asyncio.sleep(len(audio) / 16000 + 30)
    lat = []
    for e in sk.events.recent(400, {"segment", "translation"}):
        d = e["data"]
        if e["type"] == "segment":
            print(f"HEARD  {d['t1'] - d['t0']:.1f}s speech, waited {d['timing']['arrived_after_speech_ended']:.1f}s, recognised in {d['timing']['recognise']:.1f}s  [{d['lang']}] {d['text'][:50]}")
        elif d.get("ok"):
            lat.append(d["latency"]); print(f"  -> {d['latency']:.1f}s end-to-end {d['stages']}")
    if lat:
        print(f"median {statistics.median(lat):.1f}s over {len(lat)} phrases (target 2.5-3.0 s on a quiet Mac)")
    await sk.stop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="te")
    ap.add_argument("--gap", type=float, default=1.0)
    a = ap.parse_args()
    asyncio.run(run(a.lang, a.gap))


if __name__ == "__main__":
    main()
