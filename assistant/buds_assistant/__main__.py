"""python -m buds_assistant [--keyboard] [--stt whisper|typed] [--tts say|print]"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from . import _LAB  # noqa: F401  (puts ../lab on sys.path)
from buds_assistant.intelligence.agent import RuleAgent
from buds_assistant.legacy.app import Assistant
from buds_assistant.controls.gestures import GestureRecognizer, load_bindings

HERE = Path(__file__).resolve().parent.parent


def build(args) -> tuple[Assistant, object]:
    from buds_assistant.legacy.stt import make_stt
    from buds_assistant.legacy.tts import PrintTTS, SayTTS
    bindings, timeout, debounce = load_bindings(args.gestures)
    data = args.data_dir
    stt = make_stt(args.stt, args.whisper_model)
    tts = PrintTTS() if args.tts == "print" else SayTTS(args.voice, args.rate)
    link_box: dict = {}
    recorder = None
    beep = lambda kind: None   # noqa: E731
    if stt.needs_audio:
        from buds_assistant.legacy.audio_io import Recorder, make_cue
        recorder = Recorder(data / "audio", device=args.input_device, session_seconds=args.session_seconds)
        files = {k: v for k, v in (("ready", args.ready_file), ("done", args.done_file), ("error", args.error_file)) if v}
        beep = make_cue("off" if args.no_beeps else args.tune, files)
    asst = Assistant(GestureRecognizer(bindings, timeout, debounce), RuleAgent(data / "notes.jsonl"), stt, tts, recorder,
                     lambda: link_box["link"].battery() if "link" in link_box else {"left": 80, "right": 80, "case": 50},
                     data, beep)
    return asst, link_box


async def amain(args, stop_evt: asyncio.Event, ready: dict) -> None:
    asst, link_box = build(args)
    ready["loop"], ready["evt"] = asyncio.get_running_loop(), stop_evt
    tasks = [asyncio.create_task(asst.poll_forever())]
    if args.keyboard:
        from buds_assistant.controls.bridge import keyboard_gestures
        tasks.append(asyncio.create_task(keyboard_gestures(lambda t: asyncio.get_running_loop().create_task(asst.on_token(t)))))
    else:
        from budslab.transport.rfcomm import make_rfcomm
        from buds_assistant.controls.bridge import BudsLink
        loop = asyncio.get_running_loop()
        link = BudsLink(make_rfcomm(args.device, args.channel), lambda t: loop.create_task(asst.on_token(t)))
        link_box["link"] = link
        tasks.append(asyncio.create_task(link.run()))
    print("ready. Gestures: see gestures.yaml. Ctrl-C to quit.")
    waiters = [asyncio.create_task(stop_evt.wait())] + tasks[1:]
    await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    asst.tts.stop()
    if asst.recorder is not None and hasattr(asst.recorder, 'close'):
        asst.recorder.close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="buds_assistant")
    ap.add_argument("--keyboard", action="store_true", help="no buds: type gestures instead")
    ap.add_argument("--stt", choices=["whisper", "typed"], default="whisper")
    ap.add_argument("--whisper-model", default="base.en", help="tiny.en (fast) | base.en | small.en (accurate)")
    ap.add_argument("--tts", choices=["say", "print"], default="say")
    ap.add_argument("--voice", help="macOS voice name, see `say -v '?'`")
    ap.add_argument("--rate", type=int, default=185)
    ap.add_argument("--device", default="auto", help="buds address (default: find paired Buds FE)")
    ap.add_argument("--channel", type=int)
    ap.add_argument("--input-device", type=int, help="force a microphone (index from the lab's Mic tab)")
    ap.add_argument("--tune", choices=["chime", "system", "off"], default="chime",
                    help="cues: soft synthesised chimes (default), macOS system sounds, or silent")
    ap.add_argument("--no-beeps", action="store_true", help="same as --tune off")
    ap.add_argument("--ready-file", help="your own sound (wav/aiff/mp3) for 'go ahead'")
    ap.add_argument("--done-file", help="your own sound for 'recording finished'")
    ap.add_argument("--error-file", help="your own sound for 'nothing heard'")
    ap.add_argument("--session-seconds", type=float, default=20.0,
                    help="keep the mic (and the buds' call mode) open this long after each use; 0 = off")
    ap.add_argument("--gestures", type=Path, default=HERE / "buds_assistant" / "config" / "gestures.yaml")
    ap.add_argument("--data-dir", type=Path, default=HERE / "data")
    args = ap.parse_args()

    ready: dict = {}

    def target() -> None:
        async def go():
            await amain(args, asyncio.Event(), ready)
        asyncio.run(go())

    def stop() -> None:
        if "loop" in ready:
            ready["loop"].call_soon_threadsafe(ready["evt"].set)

    if args.keyboard:
        try:
            target()
        except (KeyboardInterrupt, EOFError):
            pass
    else:
        from budslab.runloop import run_main       # macOS: IOBluetooth needs the main-thread run loop
        run_main(target, stop)


if __name__ == "__main__":
    main()
