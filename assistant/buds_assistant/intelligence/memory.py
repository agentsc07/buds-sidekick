"""Memory: retrieval over what each person said (RAG keyed by speaker), fact/commitment extraction, dossiers."""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass

import numpy as np

from buds_assistant.intelligence.llm import LLMError
from buds_assistant.core.store import Store

STOP = set("a an the of to and or is are was were be been i you he she it we they my your his her their our me him them "
           "what who when where why how did do does about said say tell on in at for with that this".split())


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


@dataclass
class Hit:
    segment: dict
    score: float


def _facts_list(data) -> list:
    """Models answer with a list, {\"facts\": [...]}, or a single fact object; accept all three."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "segment_id" in data:
            return [data]
        return next((v for v in data.values() if isinstance(v, list)), [])
    return []


class Memory:
    def __init__(self, store: Store, llm, sim_floor: float = 0.6) -> None:
        self.store, self.llm, self.sim_floor = store, llm, sim_floor      # unrelated text still scores ~0.4-0.5 on real models

    # ---- indexing -------------------------------------------------------------------------
    def index_segment(self, sid: int, text: str) -> bool:
        try:
            self.store.set_segment_embedding(sid, self.llm.embed([text])[0])
            return True
        except (LLMError, KeyError, IndexError):
            return False                                   # keyword search still works without embeddings

    # ---- retrieval --------------------------------------------------------------------------
    def retrieve(self, query: str, person_id: int | None = None, k: int = 5, since: float | None = None) -> list[Hit]:
        segs = [s for s in self.store.segments(person_id=person_id, since=since, with_embedding=True, limit=5000)
                if s["text"] and s["speaker_id"] is not None and not s["experimental"]]
        if not segs:
            return []
        qv = None
        try:
            qv = self.llm.embed([query])[0]
            qv = qv / (np.linalg.norm(qv) or 1.0)
        except (LLMError, KeyError, IndexError):
            qv = None
        qw, now, hits = _words(query), time.time(), []
        for s in segs:
            kw = len(qw & _words(s["text"])) / (len(qw) or 1)
            sim = 0.0
            if qv is not None and s["embedding"] is not None:
                e = s["embedding"]
                sim = float(qv @ (e / (np.linalg.norm(e) or 1.0)))
            sim = sim if sim >= self.sim_floor else 0.0                     # weak semantic matches are noise
            score = max(sim, kw) * 0.7 + min(sim, kw) * 0.3 if sim else kw
            score *= 1.0 + 0.2 * math.exp(-(now - s["t1"]) / (14 * 86400))        # mild recency boost
            if score > 0.15:
                hits.append(Hit(s, score))
        hits.sort(key=lambda h: -h.score)
        return hits[:k]

    # ---- facts ------------------------------------------------------------------------------------
    def extract_facts(self, conv_id: int, model: str | None = None) -> list[int]:
        segs = [s for s in self.store.segments(conv_id=conv_id) if s["speaker_id"] is not None and s["text"]
                and not s["experimental"]]
        if not segs:
            return []
        lines = "\n".join(f"[{s['id']}] {s['speaker']}: {s['text']}" for s in segs[-60:])
        prompt = ("Extract what is worth remembering from this conversation transcript. 'Me' is the user; the other names are the people they talked to. Reply with ONLY a JSON object "
                  '{"facts": [ ... ]}. Each item: {"segment_id": <the [id] of the line it came from>, "kind": one of '
                  '"commitment" (someone promises to do something), "date", "preference", "fact", "text": short statement, '
                  '"due": deadline or null}. Include EVERY promise ("I will", "I\'ll", "we will") and every date, deadline '
                  "or number that is mentioned. Use only what is explicitly said.\n"
                  'Example: line "[7] Ana: I will email the contract on Monday." gives '
                  '{"facts":[{"segment_id":7,"kind":"commitment","text":"email the contract","due":"Monday"}]}. '
                  'If there is nothing, reply {"facts":[]}.\n\nTranscript:\n' + lines)
        try:
            raw = self.llm.chat([{"role": "user", "content": prompt}], model=model, max_tokens=500, json_mode=True)
            data = _facts_list(json.loads(raw))
        except (LLMError, json.JSONDecodeError, TypeError):
            return []
        by_id = {s["id"]: s for s in segs}
        ids = []
        for f in data:
            s = by_id.get(f.get("segment_id")) if isinstance(f, dict) else None
            if not s or f.get("kind") not in ("commitment", "date", "preference", "fact") or not f.get("text"):
                continue                                    # unverifiable facts (no real source segment) are dropped
            ids.append(self.store.add_fact(s["speaker_id"], f["kind"], str(f["text"])[:200], f.get("due"), s["id"],
                                           owner=s["speaker"]))
        return ids

    def commitments(self, person_id: int | None = None, status: str = "open") -> list[dict]:
        rows = self.store.facts(person_id=person_id, kind="commitment", status=status)
        for r in rows:
            p = self.store.person(r["person_id"]) if r["person_id"] else None
            r["person"] = p["name"] if p else None
        return rows

    def dossier(self, person_id: int) -> dict:
        p = self.store.person(person_id)
        if not p:
            return {}
        segs = self.store.segments(person_id=person_id, limit=400)
        words: dict[str, int] = {}
        for s in segs:
            for w in _words(s["text"]):
                words[w] = words.get(w, 0) + 1
        return {"person": p, "facts": self.store.facts(person_id=person_id), "segments": len(segs),
                "last_seen": segs[-1]["t1"] if segs else None, "recent": [s["text"] for s in segs[-5:]],
                "topics": [w for w, _ in sorted(words.items(), key=lambda kv: -kv[1])[:8]]}
