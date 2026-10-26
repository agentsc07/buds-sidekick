"""Conversation pipeline: capture -> ring buffer + segmenter -> (speaker-ID + transcription) -> store/memory -> policy.

Runs its heavy work on one worker thread so the audio callback never blocks. Unknown speakers stay in RAM only
(and can be named afterwards); known speakers are persisted per their own policy."""
from __future__ import annotations

import asyncio  # noqa: F401  (type hints)
import queue
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from buds_assistant.audio.capture import RATE, CaptureSource, RingBuffer
from buds_assistant.speech.speaker import Match
from buds_assistant.audio.segmenter import Segment, Segmenter


class ConversationPipeline:
    def __init__(self, cfg, store, speaker, transcriber, memory, policy, events, ring: RingBuffer,
                 on_hint: Callable[[object], None] = lambda h: None,
                 on_foreign: Callable[[dict], None] = lambda e: None) -> None:
        self.cfg, self.store, self.speaker, self.transcriber = cfg, store, speaker, transcriber
        self.memory, self.policy, self.events, self.ring, self.on_hint = memory, policy, events, ring, on_hint
        self.on_foreign = on_foreign                 # called for non-English segments (interpreter mode)
        self.own_voice: Callable[[float, float], float] = lambda a, b: 0.0       # how much of [a, b] was the assistant itself speaking
        self.on_turn: Callable[[dict], None] = lambda e: None      # every spoken line (the wake word and Autopilot's judgement listen here)
        self.window: list[dict] = []                 # everything said in this conversation (RAM; includes unknown voices)
        self.conv_id: int | None = None
        self.source: CaptureSource | None = None
        self.source_key = "laptop"                              # which microphone family is capturing: "buds" or "laptop"
        self.segmenter: Segmenter | None = None
        self._q: queue.Queue = queue.Queue(maxsize=64)
        self._worker: threading.Thread | None = None
        self._stream_start = 0.0
        self.current_speaker: dict | None = None
        self.mode = "listen"
        self.placement = "ear"
        self._waiters: list = []                     # manual 'ask' while live: the NEXT utterance is the query
        self.tap: list | None = None                 # raw chunks while a toggle-dictation is running
        self.seg_kwargs: dict = {}                   # Segmenter settings (interpreter mode uses shorter phrases)
        self.persist = True                          # memory level 'live': show everything, store nothing
        self._closed = False                         # set while stopping with discard: in-flight work must not store or whisper

    # ---- lifecycle -------------------------------------------------------------------------------------
    def start(self, source: CaptureSource, mode: str = "listen", placement: str = "ear") -> int:
        self.mode, self.placement = mode, placement
        self._closed = False
        if self.conv_id is None:
            self.conv_id = self.store.start_conversation(mode, placement)
            if hasattr(self.policy, "conv_id"):
                self.policy.conv_id = self.conv_id
            self.window.clear()
            self.speaker.reset_session()
            self.events.publish("conversation_started", id=self.conv_id, mode=mode, placement=placement)
        self.set_source(source)
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, daemon=True, name="pipeline")
            self._worker.start()
        return self.conv_id

    def set_source(self, source: CaptureSource) -> None:
        """Swap the microphone (e.g. buds -> Mac mic when the buds come out) without ending the conversation."""
        if self.source is not None:
            self.source.stop()
        self.segmenter = Segmenter(**self.seg_kwargs)
        self._stream_start = time.time()
        self.source = source
        self.source_key = "buds" if "bud" in str(getattr(source, "name", "")).lower() else "laptop"
        source.start(self._on_chunk)
        self.events.publish("capture", source=getattr(source, "name", "?"), placement=self.placement)

    def drain(self, timeout: float = 60.0) -> None:
        """Wait until every queued segment has been processed (tests / graceful stop)."""
        t = time.time()
        while self._q.unfinished_tasks and time.time() - t < timeout:
            time.sleep(0.02)

    def stop(self, extract: bool = True, discard: bool = False) -> None:
        """End the conversation. discard=True (Private) drops queued and in-flight audio instead of processing it."""
        if self.source is not None:
            self.source.stop()
            self.source = None
        alive = self._worker is not None and self._worker.is_alive()
        if discard:
            self._closed = True
            while True:
                try:
                    self._q.get_nowait(); self._q.task_done()
                except queue.Empty:
                    break
        elif alive:
            for s in (self.segmenter.flush() if self.segmenter else []):
                self._q.put(s)
        if alive:                                                 # a sentinel with no worker would kill the NEXT worker at once
            self._q.put(None)
            self._worker.join(timeout=30)
        self._worker = None
        self._waiters.clear()
        cid, self.conv_id = self.conv_id, None
        if cid is not None:
            self.store.end_conversation(cid)
            self.events.publish("conversation_ended", id=cid)
            if extract and self.persist and self.memory is not None:
                threading.Thread(target=self._extract, args=(cid,), daemon=True, name="extract-facts").start()
        self.ring.clear()
        self.current_speaker = None

    def _extract(self, cid: int) -> None:
        try:                                              # best effort, slow (local LLM): never on the event loop
            ids = self.memory.extract_facts(cid)
            self.events.publish("facts_extracted", conversation=cid, count=len(ids))
        except Exception as exc:  # noqa: BLE001
            self.events.publish("error", where="extract_facts", error=repr(exc))

    # ---- audio path ---------------------------------------------------------------------------------------
    def wait_utterance(self, loop) -> "asyncio.Future":
        fut = loop.create_future()
        self._waiters.append((loop, fut))
        return fut

    def drop_waiter(self, fut) -> None:
        """A question that timed out must not eat the next real utterance."""
        self._waiters[:] = [(l, f) for l, f in self._waiters if f is not fut]

    def _on_chunk(self, chunk: np.ndarray) -> None:
        self.ring.push(chunk)
        if self.tap is not None:
            self.tap.append(chunk)
        if self.segmenter is None:
            return
        for seg in self.segmenter.feed(chunk):
            try:
                self._q.put_nowait(seg)
            except queue.Full:
                self.events.publish("dropped_segment", reason="backlog")      # drop work, never audio

    def user_speaking(self) -> bool:
        return self.segmenter is not None and self.segmenter.speaking

    def feed_segment(self, seg: Segment) -> None:
        """Test/offline helper: process a segment synchronously."""
        return self._process(seg)

    def merge_queued(self, first: Segment, queued: list[Segment], max_seconds: float = 12.0, max_gap: float = 1.5) -> Segment:
        """Behind while interpreting: join the phrases already waiting into ONE recognition pass. A pass costs ~1.3 s before it reads a word
        (the model always looks at a 30 s window), so three queued phrases cost three passes; merged they cost one. Only neighbours (a
        pause is a new turn), never more than ~12 s."""
        audio, t0, t1 = [first.audio], first.t0, first.t1
        for nxt in queued:
            if nxt.t0 - t1 > max_gap or nxt.t1 - t0 > max_seconds:
                break
            audio += [np.zeros(int(0.2 * RATE), dtype=first.audio.dtype), nxt.audio]
            t1 = nxt.t1
        return first if len(audio) == 1 else Segment(t0, t1, np.concatenate(audio))

    def _take_queued(self) -> list[Segment]:
        out: list[Segment] = []
        while True:
            try:
                nxt = self._q.get_nowait()
            except queue.Empty:
                return out
            if nxt is None:                                   # the stop sentinel: put it back for the loop to see
                self._q.put(None); self._q.task_done()
                return out
            out.append(nxt)

    def _run(self) -> None:
        while True:
            seg = self._q.get()
            extra = 0
            try:
                if seg is None:
                    return
                if self.mode == "interpreter" and not self.cfg.interpreter_two_way:
                    queued = self._take_queued()
                    extra = len(queued)
                    seg = self.merge_queued(seg, queued[:])
                    if queued and seg.t1 < queued[-1].t1:      # some were too far or too long to join: process the rest separately next
                        rest = [q for q in queued if q.t0 > seg.t1 - 1e-9]
                        for q in rest:
                            self._q.put(q)                    # (new entries: the originals are all marked done below)
                self._process(seg)
            except Exception as exc:  # noqa: BLE001  one bad segment must not kill the conversation
                self.events.publish("error", where="pipeline", error=repr(exc))
            finally:
                for _ in range(1 + extra):
                    self._q.task_done()

    # ---- one utterance --------------------------------------------------------------------------------------
    def _process(self, seg: Segment) -> dict | None:
        while self._waiters:                                  # this utterance is a question to the assistant, not conversation
            loop, fut = self._waiters.pop(0)
            if fut.done():                                    # asked and gave up: not a real listener any more
                continue
            loop.call_soon_threadsafe(lambda f=fut: f.done() or f.set_result(seg.audio))
            return None
        t_in = time.time()
        if self.own_voice(self._stream_start + seg.t0, self._stream_start + seg.t1) >= 0.6:
            self.events.publish("own_voice_dropped", seconds=round(seg.t1 - seg.t0, 1))      # the mic heard the assistant's own words: not a conversation
            return None
        prev = getattr(self, "_turn", None)
        no_id = self.mode == "interpreter" and not self.cfg.interpreter_two_way
        if no_id:
            m = Match(None, None, None, 0.0)                  # one-way interpreting does not use who is speaking: save the time
        else:
            m = self.speaker.identify(seg.audio, prev={**prev, "gap": seg.t0 - prev["t1"]} if prev else None)
        if m.person_id is not None and m.person_id in self.speaker.assistant_ids:
            self.events.publish("own_voice_dropped", seconds=round(seg.t1 - seg.t0, 1), reason="voice")      # it is the assistant's own voice
            return None
        if m.person_id is not None and m.embedding is not None:
            self._turn = {"emb": m.embedding, "seconds": seg.audio.size / RATE, "t1": seg.t1, "person_id": m.person_id}
        t_id = time.time()
        tr = self.transcriber.transcribe(seg.audio)
        t_stt = time.time()
        if not tr.text.strip() or self._closed:
            return None
        epoch0, epoch1 = self._stream_start + seg.t0, self._stream_start + seg.t1
        cs, inherited = self.current_speaker, False
        if m.too_short:                                       # one word is not enough to name anyone from
            if cs and epoch0 - cs["t"] <= 2.5 and (cs.get("name") or cs.get("cluster")):
                m.person_id, m.name, m.cluster, inherited = cs.get("person_id"), cs.get("name"), cs.get("cluster"), True   # same turn, probably
            else:
                m.person_id, m.name, m.cluster = None, "Unsure", None
        name = "" if no_id else (m.name or m.cluster or "Unknown")
        if m.promoted and m.cluster:                          # the cluster was just recognised: earlier lines of it get the name too
            for old in self.window:
                if old.get("cluster") == m.cluster and old.get("person_id") is None:
                    old.update(person_id=m.person_id, speaker=m.name, cluster=None)
            self.events.publish("segment_relabel", cluster=m.cluster, name=m.name, person_id=m.person_id)
        e = {"t0": epoch0, "t1": epoch1, "speaker": name, "person_id": m.person_id, "cluster": None if m.person_id is not None else m.cluster,
             "text": tr.text.strip(), "lang": tr.lang, "conf": round(m.score, 2), "seg_id": None,
             "is_self": bool(not inherited and m.name and m.name == self.cfg.self_name and (self.cfg.is_you(m.score) or m.promoted)),
             "inherited": inherited, "no_id": no_id, "pooled": m.pooled, "why": self._why(m, inherited),
             "experimental": tr.experimental, "tconf": tr.conf,
             "timing": {"arrived_after_speech_ended": round(t_in - (self._stream_start + seg.t1), 2), "voice_id": round(t_id - t_in, 2), "recognise": round(t_stt - t_id, 2)},
             "embedding": m.embedding}
        self._persist(e, seg)
        if e["is_self"] and not m.pooled and m.embedding is not None:      # learn the user's voice on this microphone, from clear turns only
            self.speaker.adapt(m.person_id, m.embedding, self.source_key, seg.audio.size / RATE, m.score)
        self.window.append(e)
        del self.window[:-400]
        if (m.person_id is not None or m.cluster) and not inherited:
            self.current_speaker = {"name": m.name, "cluster": m.cluster, "person_id": m.person_id, "t": epoch1}
        self._keep_unnamed(e, m, seg, inherited, no_id)
        self.events.publish("segment", **{k: v for k, v in e.items() if k != "embedding"})
        if self.cfg.interpreter and tr.text.strip():            # interpreting: every phrase goes to the interpreter, not just Telugu
            self.on_foreign(e)
        if tr.text.strip() and not tr.experimental:
            try:
                self.on_turn(e)
            except Exception as exc:  # noqa: BLE001  a listener must never break the conversation
                self.events.publish("error", where="on_turn", error=repr(exc))
        if self.policy and not tr.experimental:
            hint = self.policy.on_segment(e, time.time())
            if hint:
                self.events.publish("hint", id=hint.id, text=hint.text, trigger=hint.trigger, person_id=hint.person_id)
                self.on_hint(hint)
        return e

    def _keep_unnamed(self, e: dict, m, seg, inherited: bool, no_id: bool) -> None:
        """A voice I could not name is kept for a few days (a clip and its voiceprint) so People can ask who it was. Never while
        translating, not saving, or switched off in Settings; never a known person."""
        if m.promoted and m.cluster:
            self.store.delete_unnamed(conv_id=self.conv_id, label=m.cluster)         # it turned out to be someone I know
            return
        if (m.person_id is not None or not m.cluster or inherited or no_id or not self.persist or self.mode == "interpreter"
                or self.cfg.keep_unnamed_days <= 0 or self.conv_id is None):
            return
        info = self.speaker.cluster_info(m.cluster)
        if info:
            self.store.upsert_unnamed(self.conv_id, m.cluster, info[0], seg.audio, "" if e.get("experimental") else e["text"], round(seg.audio.size / RATE, 1))

    def _why(self, m, inherited: bool) -> str | None:
        """Plain reason for a label that is not a confident match (shown on tap in the transcript)."""
        if inherited:
            return "Too short to tell, so it follows the previous speaker."
        if m.too_short:
            return "Too short to tell who spoke."
        if m.person_id is None:
            return f"Closest known voice scored {m.score:.2f}; I need {self.cfg.speaker_threshold:.2f} to be sure."
        return "Joined the sentence before it." if m.pooled else None

    def _persist(self, e: dict, seg: Segment) -> None:
        pid = e["person_id"]
        if not self.persist:
            return                                              # live only: shown now, never stored
        if e["experimental"] or e.get("inherited"):
            return                                              # unreliable Telugu transcripts, and guessed speakers, never become memory
        if pid is None:
            if not self.cfg.store_unknown:
                return                                          # unknown voices stay in RAM only
        else:
            person = self.store.person(pid)
            if not person or person["policy"] == "none":
                return
        audio_ref = None
        if pid is not None and person["policy"] == "audio":
            d = Path(self.cfg.data_dir) / "people" / str(pid)
            d.mkdir(parents=True, exist_ok=True)
            audio_ref = str(d / f"{int(e['t0'] * 1000)}.wav")
            with wave.open(audio_ref, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(seg.audio.tobytes())
        e["seg_id"] = self.store.add_segment(self.conv_id, e["t0"], e["t1"], pid, e["cluster"], e["conf"], e["text"],
                                             e["lang"], audio_ref)
        if self.memory is not None:
            self.memory.index_segment(e["seg_id"], e["text"])

    # ---- naming / correction ----------------------------------------------------------------------------------
    def name_cluster(self, label: str, name: str, consent: str) -> int:
        """'Speaker A was Ravi': enrol the voice and persist what that voice said earlier in this conversation."""
        pid = self.speaker.name_cluster(label, name, consent)
        self.store.delete_unnamed(conv_id=self.conv_id, label=label)
        person = self.store.person(pid)
        for e in self.window:
            if e["cluster"] == label and e["person_id"] is None:
                e.update(person_id=pid, speaker=name, cluster=None)
                if person["policy"] != "none" and not e["experimental"]:
                    e["seg_id"] = self.store.add_segment(self.conv_id, e["t0"], e["t1"], pid, None, e["conf"], e["text"], e["lang"])
                    if self.memory is not None:
                        self.memory.index_segment(e["seg_id"], e["text"])
        self.events.publish("cluster_named", label=label, name=name, person_id=pid)
        return pid

    def correct(self, seg_id: int, person_id: int) -> None:
        """'That wasn't Ravi, that was Dev': relabel and learn from it."""
        seg = next((e for e in self.window if e["seg_id"] == seg_id), None)
        self.store.reassign_segment(seg_id, person_id)
        if seg is not None:
            p = self.store.person(person_id)
            seg.update(person_id=person_id, speaker=p["name"], cluster=None)
            if seg.get("embedding") is not None:
                self.speaker.add_sample(person_id, seg["embedding"], "correction")
        self.events.publish("label_corrected", segment=seg_id, person_id=person_id)

    def note_assistant(self, text: str, lang: str = "en") -> None:
        """What the assistant itself just said (an answer or a whisper), kept in the conversation context so recaps know whose words they are.
        Not a transcript line, not stored, not a person."""
        now = time.time()
        self.window.append({"t0": now, "t1": now, "speaker": "Sidekick", "assistant": True, "person_id": None, "cluster": None, "text": text,
                            "lang": lang, "conf": 1.0, "seg_id": None, "experimental": False, "is_self": False})
        del self.window[:-400]

    def recent(self, seconds: float = 120.0) -> list[dict]:
        cutoff = time.time() - seconds
        return [{"speaker": e["speaker"], "text": e["text"], "t1": e["t1"]} for e in self.window if e["t1"] >= cutoff]
