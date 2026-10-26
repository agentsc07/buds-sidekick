"""The assistant loop: gesture -> beep -> listen -> transcribe -> agent -> speak."""
from __future__ import annotations

import asyncio
import functools
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from buds_assistant.intelligence.agent import Agent
from buds_assistant.controls.gestures import GestureRecognizer, Match
from buds_assistant.legacy.stt import STT
from buds_assistant.legacy.tts import TTS


class Assistant:
    def __init__(self, recognizer: GestureRecognizer, agent: Agent, stt: STT, tts: TTS, recorder,
                 battery: Callable[[], dict | None], data_dir: Path,
                 beep: Callable[[str], None] = lambda kind: None, say: Callable[[str], None] = print) -> None:
        self.rec, self.agent, self.stt, self.tts, self.recorder = recognizer, agent, stt, tts, recorder
        self.battery, self.beep, self.say = battery, beep, say
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.last_reply = ""
        self._task: asyncio.Task | None = None
        self._stop_rec: threading.Event | None = None
        self._hold: threading.Event | None = None

    # ---- input ---------------------------------------------------------------------
    async def on_token(self, token: str) -> None:
        self.say(f"gesture: {token}")
        for m in self.rec.feed(token, time.monotonic()):
            await self.dispatch(m)

    async def poll_forever(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            for m in self.rec.poll(time.monotonic()):
                await self.dispatch(m)

    # ---- actions ---------------------------------------------------------------------
    async def dispatch(self, m: Match) -> None:
        a = m.binding.action
        self.say(f"action: {a} ({m.phase})")
        if a in ("ask_toggle", "note_toggle"):
            if self._hold is not None and not self._hold.is_set() and self._task and not self._task.done():
                self._hold.set()                        # second hold: stop listening, go answer
            else:
                self._hold = threading.Event()
                self._launch(self._listen("note" if a == "note_toggle" else "ask", self._hold))
        elif a in ("ask_hold", "note_hold"):
            if m.phase == "start":
                self._hold = threading.Event()
                self._launch(self._listen("note" if a == "note_hold" else "ask", self._hold))
            elif m.phase == "end" and self._hold:
                self._hold.set()
        elif a in ("ask", "note"):
            self._launch(self._listen(a, None))
        elif a == "repeat":
            self._launch(self._speak(self.last_reply or "I have nothing to repeat yet."))
        elif a == "stop":
            self._cancel()
        elif a == "battery":
            self._launch(self._speak(self.agent.respond("battery", self._ctx()).text))
        elif a == "time":
            self._launch(self._speak(self.agent.respond("what time is it", self._ctx()).text))
        else:
            self.say(f"unknown action {a!r}")

    def _ctx(self) -> dict:
        return {"battery": self.battery(), "now": datetime.now()}

    def _cancel(self) -> None:
        self.tts.stop()
        if self._stop_rec:
            self._stop_rec.set()
        if self._task and not self._task.done():
            self._task.cancel()

    def _launch(self, coro) -> None:
        self._cancel()                       # barge-in: a new request interrupts whatever is happening
        self._task = asyncio.create_task(coro)

    async def _speak(self, text: str) -> None:
        self.last_reply = text
        self.say(f"assistant: {text}")
        await self.tts.speak(text)

    # ---- the pipeline ----------------------------------------------------------------
    async def _listen(self, kind: str, hold: threading.Event | None) -> None:
        loop = asyncio.get_running_loop()
        t0 = time.time()
        rec_info: dict = {}
        audio16k = None
        if self.stt.needs_audio:
            if hasattr(self.recorder, "open"):
                self.say("opening mic…")
                await loop.run_in_executor(None, self.recorder.open)   # buds flip to call mode here, BEFORE the cue
            await loop.run_in_executor(None, self.beep, "ready")
            self.say("listening…")
            self._stop_rec = hold or threading.Event()
            rec = await loop.run_in_executor(None, functools.partial(
                self.recorder.record, self._stop_rec, kind, hold is not None))
            t_rec = time.time()
            rec_info = {"wav": str(rec.path), "device": rec.device, "rate": rec.rate,
                        "seconds": round(len(rec.audio) / rec.rate, 2)}
            await loop.run_in_executor(None, self.beep, "done")
            if not rec.heard_speech:
                await loop.run_in_executor(None, self.beep, "error")
                self.say("(no speech heard)")
                return
            audio16k = rec.to_16k()
        else:
            t_rec = time.time()
        text = await loop.run_in_executor(None, self.stt.transcribe, audio16k)
        t_stt = time.time()
        self.say(f"heard: {text!r}")
        if kind == "note":
            text = "note " + text
        reply = self.agent.respond(text, self._ctx())
        t_reply = time.time()
        self._log({"kind": kind, "heard": text, "reply": reply.text, "intent": reply.intent, **rec_info,
                   "t_record": round(t_rec - t0, 2), "t_stt": round(t_stt - t_rec, 2),
                   "t_agent": round(t_reply - t_stt, 3)})
        await self._speak(reply.text)

    def _log(self, row: dict) -> None:
        with open(self.data_dir / "assistant.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), **row}) + "\n")
