"""Sidekick: wires the buds, the conversation pipeline, the brain, output and the dashboard together.

    python -m buds_assistant.sidekick               real buds (stop the lab first: one control client at a time)
    python -m buds_assistant.sidekick --simulate    no buds: drive gestures/placement from the dashboard
"""
from __future__ import annotations

import argparse
import asyncio
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from . import _LAB  # noqa: F401
from buds_assistant.intelligence.agent import RuleAgent
from buds_assistant.intelligence.brain import Brain, Reply
from buds_assistant.audio.capture import MicSource, RingBuffer
from buds_assistant.core.config import APP_HOME, CHECKOUT, CONFIG_DIR, HERE, Config, simulator_dir
from buds_assistant.core.events import EventBus
from buds_assistant.audio.listener import ManualListener
from buds_assistant.intelligence.llm import OllamaClient
from buds_assistant.intelligence.memory import Memory
from buds_assistant.intelligence.autopilot import REASONS
from buds_assistant.controls.buttonmap import ButtonMapGuard
from buds_assistant.intelligence import voice_lines
from buds_assistant.speech.interpreter import Interpreter, Phrase
from buds_assistant.intelligence.judge import Judge
from buds_assistant.intelligence.wake import wake_query
from buds_assistant.intelligence.personal import Personal
from buds_assistant.core.models import ModelManager
from buds_assistant.core.modes import CAPTURING, ModeManager, load_profiles
from buds_assistant.audio.output import FakePlayer, SayRenderTTS, SoundDevicePlayer, OutputArbiter
from buds_assistant.core.pipeline import ConversationPipeline
from buds_assistant.intelligence.policy import Policy
from buds_assistant.core.pulls import Downloads
from buds_assistant.core.store import Store
from buds_assistant.core.uistate import UiState
from buds_assistant.speech.translate import Translator, detect_lang


class Sidekick:
    def __init__(self, cfg: Config, gestures: Path, simulate: bool = False, silent: bool = False,
                 llm=None, speaker=None, transcriber=None, player_factory=None) -> None:
        self.cfg, self.simulate, self.silent = cfg, simulate, silent
        self.gestures_path = Path(gestures)
        self.events = EventBus()
        self.store = Store(cfg.data_dir)
        self.ring = RingBuffer(cfg.ring_seconds)
        self.llm = llm or OllamaClient(cfg.ollama_host, cfg.chat_model, cfg.embed_model)
        self.downloads = Downloads(cfg.ollama_host)
        self.memory = Memory(self.store, self.llm)
        self.translator = Translator(self.llm, cfg.translate_model)
        self.rules = RuleAgent(cfg.data_dir / "notes.jsonl")
        self.personal = Personal(self.store)
        self.personal.seed_sample(datetime.now())             # flagged sample data, once, until you clear it
        self.brain = Brain(self.memory, self.translator, self.llm, self.rules, self.store, cfg.deep_model, personal=self.personal)
        self.speaker = speaker or self._make_speaker()
        self._real_stt = transcriber is None                      # real recognisers (not injected test fakes): worth preloading
        self.transcriber = transcriber or self._make_transcriber()
        self.policy = Policy(cfg, self.store, self.memory, self.events, self.personal)
        self.link = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        self._dictating = False
        tts = SayRenderTTS({"en": cfg.voice_en, "te": cfg.voice_te})
        mk = player_factory or (lambda hint: FakePlayer() if silent else SoundDevicePlayer(hint))
        self.output = OutputArbiter(tts, {"ear": mk(cfg.ear_output_hint), "remote": mk(cfg.remote_output_hint)}, self.events, cfg.hint_ttl)
        self.interpreter = Interpreter(cfg, self.translator, self.output, self.events)
        self.pipeline = ConversationPipeline(cfg, self.store, self.speaker, self.transcriber, self.memory, self.policy,
                                             self.events, self.ring, self._on_hint, self._on_foreign)
        self.modes = ModeManager(cfg, self.events, self.output, self.ring, self.pipeline, self.policy, self.store,
                                    self._source, load_profiles(gestures), self._handlers(), self._ambient)
        self.models = ModelManager(self.llm, cfg, self.events)
        self.models.hooks = {"enter": self._load_interpreter_speech, "leave": self._unload_interpreter_speech}
        self._te_before = False
        self.ui = UiState(self.events, cfg)
        self.ui._s["practice"] = bool(simulate)                # the dashboard says "practice mode" instead of "buds not connected"
        self.ui.voice_ready_fn = lambda: (lambda me: me is None or self.speaker.ready_for(me["id"]))(self.store.person_by_name(cfg.self_name))
        self.buttons = ButtonMapGuard(Path(cfg.data_dir) / "buttonmap.json", self._send_touch, self.events)
        self._buttons_started = False
        self.modes.models = self.models
        self.judge = Judge(cfg, self.llm, self.personal, self.memory, self.policy, self._on_hint, speaking=lambda: self.output.speaking)
        self.pipeline.on_turn = self._on_turn
        self.pipeline.own_voice = self.output.overlap_fraction
        self.listener = ManualListener(self._source, lambda: self.modes.placement)
        self._prev_noise: str | None = None
        self._last_reply = ""
        self.last_hint = None
        self.try_until = 0.0                                   # gesture 'try it' mode: show the gesture, do nothing (expires)

    # ---- factories ------------------------------------------------------------------------------------
    def _make_speaker(self):
        from buds_assistant.speech.speaker import SherpaEmbedder, SpeakerEngine
        return SpeakerEngine(SherpaEmbedder(self.cfg.speaker_model), self.store, self.cfg.speaker_threshold,
                             self.cfg.min_identify_seconds)

    def ensure_assistant_voice(self) -> int:
        """The assistant's own speaking voice as a built-in profile (not a person): if the mic ever hears it, it is recognised as the assistant and ignored."""
        from .eval.voice_bench import buds_like
        existing = next((p for p in self.store.people() if p.get("kind") == "assistant"), None)
        if existing and self.speaker.ready_for(existing["id"]):
            return existing["id"]
        pid = existing["id"] if existing else self.store.add_person("Sidekick (my own voice)", "Built in: the assistant's own speaking voice", "none", kind="assistant")
        phrases = [("en", t) for t in ("Your calendar is clear today.", "I've added that to your to-dos.", "Quick answer: it is about three hundred metres.",
                                       "Sorry, I didn't catch that. Could you say it again?", "Your meeting starts in ten minutes.", "I'm here. How can I help?")] \
            + [("te", t) for t in ("నమస్కారం, ఎలా ఉన్నారు", "మీ సమావేశం రేపు మధ్యాహ్నం ఉంటుంది")]
        for i, (lang, text) in enumerate(phrases):
            try:
                audio, rate = self.output.tts.render(text, lang)
            except Exception:  # noqa: BLE001  a missing voice must not stop the app
                continue
            x = audio.astype(np.float32) / 32768.0
            if rate != 16000 and x.size:
                x = np.interp(np.linspace(0, x.size - 1, int(x.size * 16000 / rate)), np.arange(x.size), x).astype(np.float32)
            for y in (x, buds_like(x, i)):
                self.store.add_voice_sample(pid, self.speaker.embed(y), "assistant")
        self.speaker.reload()
        return pid

    def _make_transcriber(self):
        from buds_assistant.speech.transcribe import LanguageGate, RoutingTranscriber, WhisperEn, WhisperTe
        en = WhisperEn(self.cfg.whisper_model)
        if not self.cfg.telugu_stt:
            return en
        return RoutingTranscriber(en, lambda: WhisperTe(self.cfg.telugu_model), LanguageGate("tiny"))

    def _router(self):
        """The Telugu-aware recogniser (language gate + Telugu model), built once and kept loaded: switching Translate on and off only swaps it in."""
        from buds_assistant.speech.transcribe import LanguageGate, RoutingTranscriber
        if getattr(self, "_te_router", None) is None:
            cur = self.transcriber
            if isinstance(cur, RoutingTranscriber):
                self._te_router = cur
            else:
                from buds_assistant.speech.transcribe import WhisperTe
                self._te_router = RoutingTranscriber(cur, lambda: WhisperTe(self.cfg.telugu_model), LanguageGate("tiny"))
        return self._te_router

    def set_telugu(self, on: bool) -> None:
        """Switch Telugu speech recognition on/off at runtime (the recogniser itself stays loaded)."""
        from buds_assistant.speech.transcribe import RoutingTranscriber
        self.cfg.telugu_stt = on
        router = self._router()
        self.transcriber = router if on else router.english
        self.pipeline.transcriber = self.transcriber
        if on and isinstance(self.transcriber, RoutingTranscriber):
            self.transcriber.eager = self.modes.mode == "interpreter" or getattr(self, "_entering_interpreter", False)

    def _warm_translation(self) -> None:
        """The first real phrase must not pay for cold caches: one recognition and a translation each way, once."""
        if getattr(self, "_warmed", False):
            return
        self._warmed = True
        try:
            from buds_assistant.audio.demo import render
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                clip = render("Geeta", "నమస్కారం, ఎలా ఉన్నారు", Path(d) / "w.wav")
            self.transcriber.transcribe(clip)
            self.translator.translate("నమస్కారం, ఎలా ఉన్నారు", "te", "en")
            self.translator.translate("Hello, how are you", "en", "te")
        except Exception as exc:  # noqa: BLE001  warm-up is best effort (no macOS voice, model down...)
            self._warmed = False
            self.events.publish("error", where="interpreter warm-up", error=repr(exc))

    def preload_interpreter(self) -> None:
        """At start (after the language model is up): load the Telugu recogniser and warm the translator, so Translate is ready before it is clicked."""
        self._router().warm()
        saved, self.transcriber = self.transcriber, self._router()
        try:
            self._warm_translation()
        finally:
            self.transcriber = saved
        self.models.mark_speech_ready()

    def _load_interpreter_speech(self) -> None:
        """Entering Interpreter: swap the (already loaded) Telugu recogniser in. Blocking; runs in the models executor."""
        self._te_before = self.cfg.telugu_stt
        self._entering_interpreter = True
        self.set_telugu(True)
        self._router().warm()                                   # no-op when preloaded
        self._warm_translation()                                # no-op when preloaded

    def _unload_interpreter_speech(self) -> None:
        self._entering_interpreter = False
        if hasattr(self.transcriber, "eager"):
            self.transcriber.eager = False
        if not self._te_before:
            self.set_telugu(False)

    def _start_models(self) -> None:
        self.models.start()
        if self._real_stt and self.cfg.preload_translator and self.models.one_model and self.models.state()["chat"] == "ready":
            try:
                self.preload_interpreter()
            except Exception as exc:  # noqa: BLE001  Translate still loads on demand
                self.events.publish("error", where="interpreter preload", error=repr(exc))

    def _on_foreign(self, e: dict) -> None:
        """Interpreting: every phrase the pipeline hears goes to the interpreter queue (thread-safe)."""
        if not self.loop:
            return
        ph = Phrase(e["text"], e["lang"], e["t0"], e["t1"], e["speaker"], e.get("person_id"), bool(e.get("is_self")), e.get("tconf", 1.0))
        self.loop.call_soon_threadsafe(self.interpreter.submit, ph)

    def _source(self, placement: str):
        return MicSource("buds" if placement == "ear" else "mac")

    def _on_turn(self, e: dict) -> None:
        """Every spoken line: addressed to the assistant by name, or something Autopilot's judgement may want to comment on."""
        if not self.loop or self.modes.mode not in ("listen", "autopilot"):
            return
        q = wake_query(e.get("text") or "")
        if q is not None:
            asyncio.run_coroutine_threadsafe(self._addressed(q), self.loop)
            return
        self.judge.on_turn(e)

    async def _addressed(self, query: str) -> None:
        if not query:
            await self.output.say(voice_lines.here(), "en", "answer")
            return
        await self.answer(query)

    def _on_hint(self, hint) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._deliver(hint), self.loop)

    def _held(self, hint, reason: str) -> None:
        """The whisper never played: rewrite its row (it was logged as said/noted when it was decided) instead of logging twice."""
        if not (hint.id and self.store.update_decision(hint.id, "held_back", reason)):
            self.store.log_decision(hint.trigger, "held_back", reason, hint.text, hint.person_id, self.pipeline.conv_id, hint.id)
        self.events.publish("autopilot_decision", trigger=hint.trigger, outcome="held_back", reason=reason, reason_text=REASONS.get(reason),
                            text=hint.text, person_id=hint.person_id, hint_id=hint.id, fact_id=hint.fact_id, conv_id=self.pipeline.conv_id)

    def _may_play(self, hint) -> bool:
        m = self.modes.mode
        return m == "autopilot" or (hint.any_mode and m != "private")

    async def _agenda_tick(self, now: float) -> None:
        """Things that come from the clock: reminders you set (any mode but Private) and meetings (Autopilot only)."""
        mode = self.modes.mode
        if mode == "private":
            return
        for r in self.personal.due_reminders(now):
            self.personal.complete_reminder(r["id"])
            h = self.policy.system_hint("reminder", voice_lines.reminder(r["text"]), now, any_mode=True)
            if h:
                await self._deliver(h)
        if mode == "autopilot":
            for e, mins in self.personal.upcoming_to_announce(now):
                h = self.policy.system_hint("meeting", voice_lines.meeting_soon(e["title"], 10 if mins == 10 else 2, ", ".join(e["people"]) or None), now)
                if h:
                    await self._deliver(h)

    async def _agenda_loop(self) -> None:
        while True:
            await asyncio.sleep(15)
            try:
                self.ui.refresh()
                await asyncio.get_running_loop().run_in_executor(None, self.models.ensure)       # Ollama came up after us: load the models now
                await self._agenda_tick(time.time())
            except Exception as exc:  # noqa: BLE001  the clock must keep ticking
                self.events.publish("error", where="agenda", error=repr(exc))

    async def _deliver(self, hint) -> None:
        """Whisper a hint: never while someone is mid-sentence (wait for a gap), drop it if it goes stale (spec 5.4)."""
        deadline, was_speaking = hint.ts + self.cfg.hint_ttl, False
        while True:
            if not self._may_play(hint):                        # Private / Standby / Interpreter since it was decided
                self._held(hint, "mode_changed")
                return
            if time.time() > deadline:
                self._held(hint, "you_were_speaking" if was_speaking else "stale")
                return
            if not self.pipeline.user_speaking():
                break
            was_speaking = True
            await asyncio.sleep(0.1)
        self.last_hint = hint
        kind = "noted" if hint.kind == "noted" else "whisper"
        self.modes.context.open(kind, time.monotonic(), ttl=30)    # open while it plays, so a double tap dismisses it
        self.output.earcon("noted" if kind == "noted" else "whisper")
        await asyncio.sleep(0.25)                              # let the earcon finish before the words
        if not self._may_play(hint):
            self.modes.context.close(kind)
            self._held(hint, "mode_changed")
            return
        spoken = await self.output.say(hint.text, "en", "hint", whisper=True)
        if spoken:
            self.pipeline.note_assistant(hint.text)
            self.modes.context.open(kind, time.monotonic())        # then 4-5 s of grace after the last word
        else:
            self.modes.context.close(kind)

    async def _ambient(self, on: bool) -> None:
        """Ambient sound while talking to people (restored afterwards). Allowlisted `noise_control` command only."""
        if self.link is None:
            return
        from budslab.protocol import commands as C
        st = self.link.state.snapshot()
        if on:
            self._prev_noise = st.get("noise_mode")
            mode = "ambient"
        else:
            mode = self._prev_noise if self._prev_noise in ("off", "anc", "ambient") else "off"
        spec, payload = C.build("noise_control", {"mode": mode}, st)
        C.check_tx_id(spec.msg_id)
        await self.link.transport.send(self.link.codec.encode(spec.msg_id, payload))

    async def _send_touch(self, left: str, right: str) -> None:
        """Set the touch-and-hold action per side (allowlisted `touchpad_option` command only)."""
        if self.link is None:
            raise RuntimeError("buds not connected")
        from budslab.protocol import commands as C
        spec, payload = C.build("touchpad_option", {"left": left, "right": right}, self.link.state.snapshot())
        C.check_tx_id(spec.msg_id)
        await self.link.transport.send(self.link.codec.encode(spec.msg_id, payload))

    async def _init_buttons(self) -> None:
        """Once per run, when the buds first report state: undo a crashed run's remap, else apply ours (if enabled)."""
        if self.buttons.path.exists():
            await self.buttons.recover()                      # the saved mapping is the user's real one; put it back first
            self.events.publish("buds", message="restored the buds' button mapping from a previous run")
            return
        st = self.link.state.snapshot() if self.link else {}
        if self.cfg.button_remap and "touch_option_l" in st:
            await self.buttons.apply(st["touch_option_l"], st["touch_option_r"], self.cfg.hold_remap_left, self.cfg.hold_remap_right)

    # ---- forgetting ----------------------------------------------------------------------------------------------------
    def forget_person(self, pid: int) -> dict:
        """Forget a person everywhere: database, files, and every in-memory trace (events, feed, replay buffer, hints)."""
        p = self.store.person(pid)
        name = (p["name"] if p else "").lower()
        counts = self.store.forget(pid)
        self.speaker.reload()
        self.pipeline.window[:] = [e for e in self.pipeline.window if e.get("person_id") != pid]
        self.events.scrub(lambda ev: ev["data"].get("person_id") == pid or (name and (str(ev["data"].get("speaker", "")).lower() == name
                                                                                      or (ev["type"] == "reply" and name in str(ev["data"].get("text", "")).lower()))))
        self.ui.scrub(lambda d: d.get("person_id") == pid)
        self.ring.clear()                                        # the replay buffer may hold their voice
        if (self.pipeline.current_speaker or {}).get("person_id") == pid:
            self.pipeline.current_speaker = None
        if self.last_hint is not None and self.last_hint.person_id == pid:
            self.last_hint = None
        for d in (self.policy.last_cue, self.policy.last_mention, self.policy.last_spoke):
            d.pop(pid, None)
        self.events.publish("forgotten", deleted=counts)             # counts only: nothing that identifies who
        return counts

    async def delete_everything(self) -> dict:
        await self.modes.set_mode("standby")                    # stop capturing first: no new rows into a wiped database
        counts = self.store.wipe()
        self.speaker.reload()
        self.speaker.reset_session()
        self.pipeline.window.clear()
        self.pipeline.current_speaker = None
        self.events.scrub(lambda ev: ev["type"] in ("segment", "hint", "reply", "autopilot_decision", "heard", "translation", "bookmark", "ui_state"))
        self.ui.scrub()
        self.ring.clear()
        self.last_hint, self._last_reply = None, ""
        for d in (self.policy.last_cue, self.policy.last_mention, self.policy.last_spoke):
            d.clear()
        self.events.publish("forgotten", person_id=None, deleted=counts)
        return counts

    # ---- context & replies ------------------------------------------------------------------------------------
    def ctx(self, **extra) -> dict:
        win = self.pipeline.recent(300)
        last = next((e for e in reversed(self.pipeline.window) if not e.get("is_self") and not e.get("assistant")), None)
        return {"now": datetime.now(), "battery": self.link.battery() if self.link else None,
                "speaker": self.pipeline.current_speaker, "window": win,
                "last_text": last["text"] if last else "", **extra}

    async def say_reply(self, reply: Reply, query: str = "", t0: float | None = None, speak: bool = True) -> None:
        self._last_reply = reply.text or self._last_reply
        self.events.publish("reply", text=reply.text, lang=reply.lang, intent=reply.intent, query=query,
                            sources=reply.sources, latency=round(time.time() - t0, 2) if t0 else None)
        if reply.action:
            act, _, arg = reply.action.partition(":")
            if act == "auto":
                await self.modes.set_mode("autopilot" if arg == "on" else "listen")
            elif act == "private":
                await self.modes.set_mode("private")
            elif act == "conversation_on":
                await self.modes.set_mode("listen")
            elif act == "conversation_off":
                await self.modes.set_mode("standby")
            else:
                await self.modes.dispatch(act)
        if reply.text and speak:
            self.pipeline.note_assistant(reply.text, reply.lang)
            await self.output.say(reply.text, reply.lang, "answer")

    async def answer(self, text: str, **extra) -> Reply:
        """Answer once per question: the same question asked again while it is being worked on shares the answer instead of being spoken again."""
        key = " ".join(text.lower().split()).rstrip("?.! ")
        if not hasattr(self, "_inflight"):
            self._inflight: dict[str, asyncio.Future] = {}
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            t0 = time.time()
            loop = asyncio.get_running_loop()
            reply = await loop.run_in_executor(None, lambda: self.brain.respond(text, self.ctx(**extra)))
            late = time.time() - t0 > self.cfg.answer_stale_s
            fut.set_result(reply)                                    # others who asked the same thing share this answer...
            self._inflight.pop(key, None)                            # ...but only while it is being worked out, not while it is being spoken
            await self.say_reply(reply, text, t0, speak=not late)
            if late:
                self.events.publish("reply_stale", query=text, seconds=round(time.time() - t0, 1))
            return reply
        except BaseException as exc:  # noqa: BLE001
            fut.set_exception(exc) if not fut.done() else None
            fut.exception()
            raise
        finally:
            self._inflight.pop(key, None)

    # ---- manual-mode handlers ----------------------------------------------------------------------------------------
    def _handlers(self):
        return {"ask": self._ask, "who": self._who, "catch_up": self._catch_up, "tell_more": self._tell_more,
                "not_useful": self._not_useful, "undo_commitment": self._undo_commitment}

    async def _transcribe(self, audio: np.ndarray | None) -> str:
        if audio is None or audio.size < 3200:
            return ""
        t = await asyncio.get_running_loop().run_in_executor(None, self.transcriber.transcribe, audio)
        return t.text

    async def _ask(self, **_) -> None:
        live = self.modes.mode in CAPTURING
        self.events.publish("listening", live=live)
        if live:
            fut = self.pipeline.wait_utterance(asyncio.get_running_loop())
            try:
                audio = await asyncio.wait_for(fut, self.cfg.ask_timeout)
            except asyncio.TimeoutError:
                self.pipeline.drop_waiter(fut)                  # nobody spoke: the next sentence belongs to the conversation
                await self.output.say(voice_lines.didnt_catch(), "en", "chime", whisper=True)
                return
        else:
            audio = await self.listener.utterance(10.0)
        text = await self._transcribe(audio)
        self.events.publish("heard", text=text)
        if not text:
            await self.output.say(voice_lines.didnt_catch(), "en", "chime", whisper=True)
            return
        await self.answer(text)

    async def _who(self, **_) -> None:
        await self.answer("who is talking")

    async def _catch_up(self, **_) -> None:
        await self.answer("catch me up")

    async def _tell_more(self, **_) -> None:
        h = self.last_hint
        rows = self.store.q("SELECT * FROM segments WHERE id=?", (h.sources[0],)) if h and h.sources else []
        if not rows:
            await self.output.say("No more detail.", "en", "answer")
            return
        day = datetime.fromtimestamp(rows[0]["t1"]).strftime("%A")
        await self.output.say(f"From {day}: {rows[0]['text']}", "en", "answer")

    async def _not_useful(self, **_) -> None:
        h = self.last_hint
        if h and h.id:
            self.policy.feedback(h.id, False, h.trigger)
            self.output.earcon("accepted")

    async def _undo_commitment(self, **_) -> None:
        h = self.last_hint
        if h and h.fact_id:
            self.store.set_fact_status(h.fact_id, "cancelled")
            self.personal.cancel_for_fact(h.fact_id)
            self.output.earcon("mode_off")
            await self.output.say("Undone.", "en", "chime", whisper=True)

    _impostors: list | None = None

    def impostor_clips(self) -> list[np.ndarray]:
        """Stand-ins for strangers when calibrating: sentences in several macOS voices (empty off macOS)."""
        if self._impostors is None:
            from buds_assistant.audio.demo import render
            import tempfile
            self._impostors = []
            lines = ["Please send me the quarterly budget before the meeting on Friday", "I think we should move the review to Thursday afternoon"]
            with tempfile.TemporaryDirectory() as d:
                for v in ("Daniel", "Karen", "Moira", "Fred", "Tessa", "Rishi", "Albert", "Samantha"):
                    try:
                        self._impostors += [render(v, t, Path(d) / "i.wav") for t in lines]
                    except Exception:  # noqa: BLE001  voice not installed
                        continue
        return self._impostors

    def record_sample(self, seconds: float) -> np.ndarray:
        """Blocking: record `seconds` from the current placement's microphone (used for enrolment)."""
        return self.record_from(self.modes.placement, seconds)

    def record_from(self, placement: str, seconds: float) -> np.ndarray:
        """Blocking: record from the buds mic (placement "ear") or the Mac mic ("remote")."""
        chunks: list[np.ndarray] = []
        src = self._source(placement)
        src.start(chunks.append)
        try:
            time.sleep(seconds)
        finally:
            src.stop()
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)

    # ---- run ----------------------------------------------------------------------------------------------------------------
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._tasks.append(asyncio.create_task(self._poll(), name="gesture-poll"))
        self._tasks.append(asyncio.create_task(self._agenda_loop(), name="agenda"))
        self._tasks.append(asyncio.create_task(self.interpreter.run(), name="interpreter"))
        threading.Thread(target=self._start_models, daemon=True, name="models-start").start()
        threading.Thread(target=lambda: self.ensure_assistant_voice(), daemon=True, name="assistant-voice").start()     # avoid a cold first question
        if not self.simulate:
            await self._start_link()

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            await self.modes.poll(time.monotonic())

    async def gesture(self, token: str) -> None:
        self.events.publish("token", token=token)
        if time.time() < self.try_until:
            return
        await self.modes.on_token(token, time.monotonic())

    async def _start_link(self) -> None:
        from budslab.transport.rfcomm import make_rfcomm
        from buds_assistant.controls.bridge import BudsLink
        loop = asyncio.get_running_loop()

        def on_event(ev):
            if ev.type == "wear" and ev.side:
                self.events.publish("wear", side=ev.side, placement=ev.data.get("placement", 0))
                asyncio.run_coroutine_threadsafe(self.modes.on_wear(ev.side, ev.data.get("placement", 0)), loop)
            if not self._buttons_started and ev.type in ("wear", "battery", "anc"):
                self._buttons_started = True
                asyncio.run_coroutine_threadsafe(self._init_buttons(), loop)
            if ev.type == "battery":
                self.events.publish("battery", **{k: ev.data.get(k) for k in ("left", "right", "case")})

        self.link = BudsLink(make_rfcomm(self.cfg_device, None),
                             lambda t: asyncio.run_coroutine_threadsafe(self.gesture(t), loop), self._log, on_event)
        self._tasks.append(asyncio.create_task(self.link.run(), name="buds-link"))

    cfg_device = "auto"

    def _log(self, msg: str) -> None:
        self.events.publish("buds", message=msg)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await self.buttons.restore()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.modes.set_mode("standby")
        except Exception:  # noqa: BLE001
            pass
        self.listener.close()
        self.output.stop()

    def status(self) -> dict:
        return {**self.modes.state(), "simulate": self.simulate, "link": getattr(self.link, "transport", None) is not None,
                "llm": self.llm.available(), "people": len(self.store.people()), "clusters": self.speaker.clusters(),
                "battery": self.link.battery() if self.link else None, "telugu_stt": self.cfg.telugu_stt, "interpreter": self.cfg.interpreter}


async def amain(args) -> None:
    import uvicorn

    from .dashboard.server import create_app
    cfg = Config.load(args.config)
    if args.simulate:
        cfg.data_dir = simulator_dir(cfg.data_dir)             # never mix synthetic voices into the real data
    sk = Sidekick(cfg, args.gestures, simulate=args.simulate, silent=args.silent)
    sk.cfg_device = args.device
    await sk.start()
    server = uvicorn.Server(uvicorn.Config(create_app(sk), host="127.0.0.1", port=args.port, log_level="warning"))
    print(f"Sidekick dashboard: http://127.0.0.1:{args.port}   ({'simulated buds' if args.simulate else 'real buds'})")
    ready["loop"], ready["server"] = asyncio.get_running_loop(), server
    try:
        await server.serve()
    finally:
        await sk.stop()


ready: dict = {}


def main() -> None:
    ap = argparse.ArgumentParser(prog="buds-sidekick")
    ap.add_argument("--simulate", action="store_true", help="no buds; use the dashboard to drive gestures/placement")
    ap.add_argument("--silent", action="store_true", help="never play audio (demos/tests)")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--device", default="auto")
    own = APP_HOME / "sidekick.yaml"                                   # your overrides, if you made any
    ap.add_argument("--config", type=Path, default=own if own.exists() else CONFIG_DIR / "sidekick.yaml")
    ap.add_argument("--gestures", type=Path, default=CONFIG_DIR / "sidekick_gestures.yaml" if CHECKOUT else APP_HOME / "sidekick_gestures.yaml")
    args = ap.parse_args()
    if not CHECKOUT and not args.gestures.exists():                    # installed: the dashboard edits a copy, not the packaged file
        args.gestures.parent.mkdir(parents=True, exist_ok=True)
        args.gestures.write_text((CONFIG_DIR / "sidekick_gestures.yaml").read_text())

    def target() -> None:
        asyncio.run(amain(args))

    def stop() -> None:
        if "server" in ready:
            ready["server"].should_exit = True

    if args.simulate:
        try:
            target()
        except KeyboardInterrupt:
            pass
    else:
        from budslab.runloop import run_main
        run_main(target, stop)


if __name__ == "__main__":
    main()
