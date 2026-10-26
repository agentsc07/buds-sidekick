"""Live interpreter: phrase in, translated speech out, with backlog, echo and uncertainty handling."""
import time
from dataclasses import dataclass

import pytest

from buds_assistant.core.config import Config
from buds_assistant.core.events import EventBus
from buds_assistant.speech.interpreter import Interpreter, Phrase
from buds_assistant.audio.output import FakePlayer, FakeTTS, OutputArbiter


@dataclass
class R:
    ok: bool
    text: str
    src: str = ""
    dst: str = ""
    error: str = ""


class FakeTranslator:
    def __init__(self, fail=False): self.calls, self.fail = [], fail

    def translate(self, text, src="auto", dst=None):
        self.calls.append((text, src, dst))
        return R(False, "", src, dst, "model unavailable") if self.fail else R(True, f"[{dst}] {text}", src, dst)


def build(two_way=False, fail=False):
    cfg = Config(interpreter_two_way=two_way)
    ev = EventBus()
    ear, mac = FakePlayer(), FakePlayer()
    tts = FakeTTS()
    out = OutputArbiter(tts, {"ear": ear, "remote": mac}, ev)
    tr = FakeTranslator(fail)
    return Interpreter(cfg, tr, out, ev), out, tr, ev, ear, mac, tts


def ph(text, lang="te", t1=None, **k):
    t1 = t1 or time.time()
    return Phrase(text, lang, k.pop("t0", t1 - 2), t1, k.pop("speaker", "Speaker A"), k.pop("person_id", None), k.pop("is_self", False), k.pop("conf", 0.9))


def spoken(out):
    return [(x["text"], x["lang"], x["route"]) for x in out.log if x["kind"] == "speak"]


async def test_their_telugu_is_spoken_in_english_in_your_ear():
    it, out, tr, ev, ear, mac, tts = build()
    it.submit(ph("రేపు కలుద్దాం"))
    await it.process_all()
    assert tr.calls == [("రేపు కలుద్దాం", "te", "en")] and spoken(out) == [("[en] రేపు కలుద్దాం", "en", "ear")] and len(ear.played) == 1


async def test_english_is_left_alone_in_one_way_mode():
    it, out, tr, *_ = build()
    it.submit(ph("hello there", "en", is_self=True))
    await it.process_all()
    assert tr.calls == [] and spoken(out) == []


async def test_two_way_speaks_your_english_as_telugu_on_the_mac_speakers():
    it, out, tr, ev, ear, mac, tts = build(two_way=True)
    it.submit(ph("see you tomorrow", "en", is_self=True))
    await it.process_all()
    assert spoken(out) == [("[te] see you tomorrow", "te", "remote")] and len(mac.played) == 1 and ear.played == []


async def test_two_way_does_not_translate_a_known_other_persons_english():
    it, out, tr, *_ = build(two_way=True)
    it.submit(ph("how are you", "en", person_id=5, speaker="Ravi"))
    await it.process_all()
    assert tr.calls == []


async def test_the_translation_we_just_played_aloud_is_not_translated_back():
    it, out, tr, ev, *_ = build(two_way=True)
    now = time.time()
    it.submit(ph("see you tomorrow", "en", is_self=True, t1=now))
    await it.process_all()
    assert it.mute_until > time.time() - 0.5                                   # speaker output + a tail guard
    it.submit(ph("[te] see you tomorrow", "te", t0=now + 0.1, t1=now + 2))     # the Mac mic heard our own speaker
    await it.process_all()
    assert len(tr.calls) == 1
    assert any(e["type"] == "translation_skipped" and e["data"]["reason"] == "echo" for e in ev.recent())


async def test_a_backlog_speeds_the_voice_up_and_merges_phrases():
    it, out, tr, ev, ear, mac, tts = build()
    for i in range(4):
        it.submit(ph(f"phrase {i}", t1=time.time() - 8))                      # queued 8 s behind
    await it.process_all()
    assert len(tr.calls) < 4 and any("phrase 0" in c[0] and "phrase 1" in c[0] for c in tr.calls)     # merged
    assert max(w for w in tts.wpms if w) > 185                                  # spoken faster


async def test_stale_filler_is_skipped_but_never_silently():
    it, out, tr, ev, *_ = build()
    it.submit(ph("ఔను", t1=time.time() - 30))                                   # one word, 30 s old
    await it.process_all()
    assert tr.calls == []
    assert any(e["type"] == "translation_skipped" and e["data"]["reason"] == "caught_up" for e in ev.recent())


async def test_a_low_confidence_phrase_says_unclear_instead_of_guessing():
    it, out, tr, ev, ear, mac, tts = build()
    it.submit(ph("???", conf=0.1))
    await it.process_all()
    assert tr.calls == [] and spoken(out) == []
    assert any(e["type"] == "translation_skipped" and e["data"]["reason"] == "unclear" for e in ev.recent())
    assert any(x["kind"] == "earcon" and x["name"] == "never_mind" for x in out.log)


async def test_a_translation_failure_is_reported_not_swallowed():
    it, out, tr, ev, *_ = build(fail=True)
    it.submit(ph("రేపు కలుద్దాం"))
    await it.process_all()
    t = [e for e in ev.recent(types={"translation"})][-1]["data"]
    assert t["ok"] is False and "unavailable" in t["error"]
    assert any(x["kind"] == "earcon" and x["name"] == "error" for x in out.log)


async def test_translation_events_carry_the_latency_and_a_running_median():
    it, out, tr, ev, *_ = build()
    it.submit(ph("రేపు కలుద్దాం", t1=time.time() - 1.0))
    await it.process_all()
    d = ev.recent(types={"translation"})[-1]["data"]
    assert d["ok"] and 0.9 < d["latency"] < 5 and d["translated"].startswith("[en]") and d["p50"] == d["latency"]


async def test_speech_that_happened_before_our_speaker_started_is_not_mistaken_for_an_echo():
    """Translating takes seconds: a real person who spoke while we were busy must still be translated afterwards."""
    it, out, tr, ev, *_ = build(two_way=True)
    now = time.time()
    it.submit(ph("see you tomorrow", "en", is_self=True, t1=now))
    await it.process_all()
    it.submit(ph("రేపు కలుద్దాం", "te", t0=now - 8, t1=now - 6))               # spoken (by a person) long before our output began
    await it.process_all()
    assert len(tr.calls) == 2
