"""End to end with REAL voices (macOS `say`) and the real speaker model; transcripts are scripted (Whisper is covered
elsewhere). Ground truth is known, so we can measure identity accuracy and privacy rules."""
import time

import numpy as np

from buds_assistant.intelligence.brain import Brain
from buds_assistant.intelligence.agent import RuleAgent
from buds_assistant.audio.capture import FileSource, RingBuffer
from buds_assistant.core.config import Config
from buds_assistant.core.events import EventBus
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.intelligence.memory import Memory
from buds_assistant.core.pipeline import ConversationPipeline
from buds_assistant.intelligence.policy import Policy
from buds_assistant.speech.speaker import SherpaEmbedder, SpeakerEngine
from buds_assistant.core.store import Store
from buds_assistant.speech.transcribe import FakeTranscriber
from buds_assistant.speech.translate import Translator
from helpers import MODEL, needs_model, needs_say, synth

SR = 16000
CONVO = [("Albert", "The budget for the third quarter is two million dollars"),
         ("Samantha", "That sounds fine, when can you send me the full report"),
         ("Daniel", "Excuse me, I have a question about the parking permit"),
         ("Albert", "I will send you the report by Friday afternoon"),
         ("Daniel", "The permit expires at the end of the month"),
         ("Samantha", "Thank you, I will check it on Friday")]
ENROL = {"Albert": ["Let us review the schedule for next week", "Please confirm the delivery address again"],
         "Samantha": ["We should call the client tomorrow morning", "I prefer to meet on Wednesday afternoon"]}


def silence(s):
    return (np.random.default_rng(1).standard_normal(int(s * SR)) * 40).astype(np.int16)


def build(tmp_path):
    cfg = Config(data_dir=tmp_path, self_name="Me")
    store, ev, ring = Store(tmp_path), EventBus(), RingBuffer(8)
    llm = FakeLLM()
    mem = Memory(store, llm)
    spk = SpeakerEngine(SherpaEmbedder(MODEL), store)
    spk.enroll("Me", [synth("Samantha", t, tmp_path / "e.wav") for t in ENROL["Samantha"]], "own voice")
    spk.enroll("Ravi", [synth("Albert", t, tmp_path / "e.wav") for t in ENROL["Albert"]], "verbal consent")
    pipe = ConversationPipeline(cfg, store, spk, FakeTranscriber([t for _, t in CONVO]), mem, Policy(cfg, store, mem), ev, ring)
    parts = [silence(1.0)]
    for v, t in CONVO:
        parts += [synth(v, t, tmp_path / "c.wav"), silence(1.2)]
    return cfg, store, ev, ring, llm, mem, spk, pipe, np.concatenate(parts)


@needs_model
@needs_say
def test_conversation_identity_privacy_replay_naming_and_answer(tmp_path):
    cfg, store, ev, ring, llm, mem, spk, pipe, audio = build(tmp_path)
    src = FileSource(audio=audio, realtime=False)
    pipe.start(src, "conversation", "ear")
    assert src.done.wait(30)
    pipe.drain()

    # replay buffer holds the most recent audio, bounded to the configured window (RAM only)
    assert ring.last(3.0).size == 3 * SR and ring.seconds <= 8.5

    truth = ["Ravi", "Me", "Speaker A", "Ravi", "Speaker A", "Me"]
    got = [e["speaker"] for e in pipe.window]
    assert len(got) == len(truth)
    assert sum(g == t for g, t in zip(got, truth)) / len(truth) >= 0.83, (got, truth)         # 5 of 6 at least
    daniels = [e for e in pipe.window if e["person_id"] is None]
    assert len(daniels) == 2 and len({e["cluster"] for e in daniels}) == 1                    # one stable "Speaker A"

    # privacy: the stranger left no trace in the database; enrolled speakers are stored and indexed
    stored = store.segments()
    assert {s["speaker"] for s in stored} <= {"Me", "Ravi"} and len(stored) == 4
    assert all(s["embedding"] is None for s in stored)                                        # (not loaded by default)
    assert all(store.segments(with_embedding=True)[i]["embedding"] is not None for i in range(4))

    # retroactive naming: "Speaker A was Dev" persists what Dev said earlier in this conversation
    dev = pipe.name_cluster("Speaker A", "Dev", "agreed verbally")
    assert len(store.segments(person_id=dev)) == 2 and [e["speaker"] for e in daniels] == ["Dev", "Dev"]

    # manual mode: answer grounded in what Ravi actually said
    brain = Brain(mem, Translator(llm), llm, RuleAgent(tmp_path / "n.jsonl"), store)
    llm.replies = ["Ravi said he will send the report by Friday afternoon."]
    r = brain.respond("what did Ravi say about the report", {"window": pipe.recent(600)})
    assert "Friday" in r.text and r.sources
    assert {s["speaker"] for s in store.segments() if s["id"] in r.sources} == {"Ravi"}
    pipe.stop(extract=False)
    assert store.q("SELECT COUNT(*) c FROM conversations WHERE end IS NOT NULL")[0]["c"] == 1


@needs_model
@needs_say
def test_auto_mode_whispers_identity_cue_and_never_for_strangers(tmp_path):
    cfg, store, ev, ring, llm, mem, spk, pipe, audio = build(tmp_path)
    ravi = store.person_by_name("Ravi")["id"]
    store.add_fact(ravi, "commitment", "send the Q3 report", "Friday", None, owner="Ravi")
    pipe.policy.enabled = True
    hints = []
    pipe.on_hint = hints.append
    src = FileSource(audio=audio, realtime=False)
    pipe.start(src, "auto", "ear")
    assert src.done.wait(30)
    pipe.drain()
    pipe.stop(extract=False)
    assert hints and hints[0].trigger == "identity" and "Ravi" in hints[0].text
    me = store.person_by_name("Me")["id"]
    assert all(h.person_id in (ravi, me) for h in hints)                                      # no hints about strangers
    assert store.decisions() and all(d["conv_id"] for d in store.decisions())                  # decisions know their conversation
    assert any(h.trigger == "capture" for h in hints)                                         # Me: "I will check it on Friday"
