"""Live interpreter: phrase in, translated speech out.

Their Telugu is spoken to you in English (in your ear, or on the Mac speakers when the buds are out). With two-way on, your English is also
spoken as Telugu on the Mac speakers for the other person. Phrases queue; when we fall behind the voice speeds up and short phrases merge;
nothing is dropped silently (a "caught up" note is published); what we play aloud is not translated back (half-duplex echo guard)."""
from __future__ import annotations

import asyncio
import statistics
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Phrase:
    text: str
    lang: str
    t0: float
    t1: float
    speaker: str = ""
    person_id: int | None = None
    is_self: bool = False
    conf: float = 1.0
    submitted: float = 0.0                       # when it reached the interpreter (after listening + speech recognition)


class Interpreter:
    WPM = 205                                    # a little faster than conversation: the listener is waiting for the end of the phrase
    TAIL = 0.6                                   # seconds of silence after our own speaker output before we listen again

    def __init__(self, cfg, translator, output, events) -> None:
        self.cfg, self.translator, self.output, self.events = cfg, translator, output, events
        self.queue: deque[Phrase] = deque()
        self.mute_from = 0.0
        self.mute_until = 0.0
        self.latencies: list[float] = []
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---- input ------------------------------------------------------------------------------------------------
    def submit(self, phrase: Phrase) -> None:
        phrase.submitted = time.time()
        self.queue.append(phrase)
        self._wake.set()

    def behind(self) -> float:
        return max(0.0, time.time() - self.queue[0].t1) if self.queue else 0.0

    async def run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            await self.process_all()

    async def process_all(self) -> None:
        while self.queue:
            await self._handle(self.queue.popleft())

    # ---- one phrase ---------------------------------------------------------------------------------------------
    def _skip(self, ph: Phrase, reason: str) -> None:
        self.events.publish("translation_skipped", reason=reason, text=ph.text, lang=ph.lang, behind=round(self.behind(), 1))

    def _direction(self, ph: Phrase) -> tuple[str, str] | None:
        if ph.lang == "te":
            return "te", "en"
        if ph.lang == "en" and self.cfg.interpreter_two_way and (ph.person_id is None or ph.is_self):
            return "en", "te"                    # my English, or someone not enrolled: assume it is for the Telugu listener
        return None

    async def _handle(self, ph: Phrase) -> None:
        loop = asyncio.get_running_loop()
        d = self._direction(ph)
        if d is None:
            return
        if ph.t0 < self.mute_until and ph.t1 > self.mute_from:     # overlaps the time OUR speaker was playing (not merely 'earlier')
            return self._skip(ph, "echo")
        lag = time.time() - ph.t1
        if lag > 15 and len(ph.text.split()) < 3:
            self.output.earcon("accepted")
            return self._skip(ph, "caught_up")
        if ph.conf < 0.3:
            self.output.earcon("never_mind")
            return self._skip(ph, "unclear")
        if lag > 6 or len(self.queue) >= 2:               # behind: say several short phrases in one go
            while self.queue and self.queue[0].lang == ph.lang and len(ph.text.split()) < 40 and not (self.queue[0].t0 < self.mute_until and self.queue[0].t1 > self.mute_from):
                nxt = self.queue.popleft()
                ph = Phrase(ph.text + " " + nxt.text, ph.lang, ph.t0, max(ph.t1, nxt.t1), ph.speaker, ph.person_id, ph.is_self, min(ph.conf, nxt.conf), min(ph.submitted, nxt.submitted))
        src, dst = d
        t_translate = time.time()
        r = await loop.run_in_executor(None, self.translator.translate, ph.text, src, dst)
        translate_s = time.time() - t_translate
        if not r.ok:
            self.output.earcon("error")
            self.events.publish("translation", text=ph.text, translated="", ok=False, error=r.error, src=src, dst=dst, speaker=ph.speaker)
            return
        behind = lag > 6 or bool(self.queue)
        speed = 1.25 if behind else 1.0
        latency = time.time() - ph.t1
        self.latencies = (self.latencies + [latency])[-50:]
        self.events.publish("translation", text=ph.text, translated=r.text, ok=True, error="", src=src, dst=dst, speaker=ph.speaker,
                            latency=round(latency, 2), p50=round(statistics.median(self.latencies), 2), behind=round(self.behind(), 1),
                            sped_up=behind,
                            stages={"listen_and_recognise": round(max(0.0, ph.submitted - ph.t1), 2), "queued": round(max(0.0, t_translate - ph.submitted), 2),
                                    "translate": round(translate_s, 2)})
        route = "remote" if dst == "te" else None
        on_mac_speakers = (route or self.output.route) == "remote"
        started = time.time()
        if on_mac_speakers:
            self.mute_from, self.mute_until = started, started + 30            # until it finishes: do not hear ourselves
        await self.output.say(r.text, dst, "answer", route=route, wpm=int(self.WPM * speed))
        if on_mac_speakers:
            self.mute_until = time.time() + self.TAIL
