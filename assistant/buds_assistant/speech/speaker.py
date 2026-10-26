"""Speaker identity: embeddings (WeSpeaker ONNX via sherpa-onnx), enrolment, open-set identification,
provisional clusters for unknown voices ("Speaker A"), retroactive naming and correction."""
from __future__ import annotations

import string
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from buds_assistant.core.store import Store


class Embedder(Protocol):
    def embed(self, audio16k: np.ndarray) -> np.ndarray: ...


class SherpaEmbedder:
    def __init__(self, model: Path, threads: int = 2) -> None:
        import sherpa_onnx
        if not Path(model).exists():
            raise FileNotFoundError(f"speaker model missing: {model}")
        self._ex = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model), num_threads=threads))
        self._lock = threading.Lock()
        self.dim = int(getattr(self._ex, "dim", 0)) or None

    def embed(self, audio16k: np.ndarray) -> np.ndarray:
        with self._lock:
            s = self._ex.create_stream()
            s.accept_waveform(16000, audio16k.astype(np.float32))
            s.input_finished()
            return np.array(self._ex.compute(s), dtype=np.float32)


def _norm(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _src_key(x: str) -> str:
    k = x.split(":")[-1] if ":" in x else (x.split("-", 1)[1] if "-" in x else x)
    return {"ear": "buds", "remote": "laptop", "mac": "laptop"}.get(k, k)


def top_k(scores, k: int = 3) -> float:
    """A person is scored by their k closest samples, not by one average: one voice on two microphones is two clouds."""
    s = np.sort(np.asarray(scores, dtype=np.float32))[::-1][:k]
    return float(s.mean()) if s.size else 0.0


def snorm(raw: float, probe_vs_cohort: np.ndarray, person_vs_cohort: np.ndarray, n: int = 20) -> float:
    """Symmetric score normalisation: the score relative to how similar the probe, and the person's voiceprint, are to other voices."""
    def z(x):
        top = np.sort(np.asarray(x, dtype=np.float32))[-n:]
        return (raw - float(top.mean())) / max(float(top.std()), 0.05)
    return 0.5 * (z(probe_vs_cohort) + z(person_vs_cohort))


def chunks(audio: np.ndarray, seconds: float = 4.0, overlap: float = 1.0) -> list[np.ndarray]:
    """Split one long recording into several overlapping voiceprint-sized pieces (one 20 s embedding is fragile; five 4 s ones are not)."""
    size, step = int(16000 * seconds), max(1, int(16000 * (seconds - overlap)))
    if audio.size <= size:
        return [audio]
    out = [audio[i:i + size] for i in range(0, audio.size - size + 1, step)]
    rest = audio[len(out) * step:]
    if rest.size >= 16000 * 2 and not np.array_equal(rest, out[-1][-rest.size:]):
        out.append(rest)
    return out


def to_f32(audio: np.ndarray) -> np.ndarray:
    return audio.astype(np.float32) / 32768.0 if audio.dtype == np.int16 else audio.astype(np.float32)


@dataclass
class Match:
    person_id: int | None
    name: str | None
    cluster: str | None          # provisional label for unknown voices, e.g. "Speaker A"
    score: float
    confident: bool = False
    too_short: bool = False
    pooled: bool = False
    promoted: bool = False       # this voice was unknown until enough of it was heard together; `cluster` is the label it had
    embedding: np.ndarray | None = field(default=None, repr=False)


@dataclass
class _Cluster:
    label: str
    embs: list = field(default_factory=list)
    person_id: int | None = None                       # set once the whole cluster has been recognised as an enrolled person
    audio: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int16))     # last few seconds, RAM only, for "who is this?" playback

    @property
    def centroid(self) -> np.ndarray:
        return _norm(np.mean(self.embs, axis=0))


class SpeakerEngine:
    def __init__(self, embedder: Embedder, store: Store, threshold: float = 0.62, min_seconds: float = 0.6,
                 margin: float = 0.04, cluster_threshold: float = 0.5) -> None:
        self.embedder, self.store = embedder, store
        self.dim: int | None = getattr(embedder, "dim", None)        # embedding size of the CURRENT model; samples of another size are kept but not used
        self.threshold, self.min_seconds, self.margin, self.cluster_threshold = threshold, min_seconds, margin, cluster_threshold
        self._centroids: dict[int, np.ndarray] = {}
        self._samples: dict[int, np.ndarray] = {}                  # person -> (n, dim) unit vectors
        self._sources: dict[int, list[str]] = {}
        self.cohort: list[np.ndarray] = []                         # other voices heard (unknown speakers): the "everybody else" for S-norm
        self.cohort_min, self.z_min, self.raw_floor = 10, 2.0, 0.06
        self.promote_min = 3                                       # segments of one cluster needed before it can be labelled as a person
        self._clusters: list[_Cluster] = []
        self.assistant_ids: set[int] = set()                       # people who are really the assistant's own speaking voice
        self._lock = threading.RLock()
        self.reload()

    # ---- enrolment -----------------------------------------------------------------
    def reload(self) -> None:
        with self._lock:
            by: dict[int, list] = {}
            src: dict[int, list] = {}
            for s in self.store.voice_samples():
                by.setdefault(s["person_id"], []).append(_norm(s["embedding"]))
                src.setdefault(s["person_id"], []).append(s.get("source") or "enrol")
            for pid, v in list(by.items()):                        # never mix embedding sizes (after a model switch)
                dim = self.dim or max({x.size for x in v}, key=lambda d: sum(x.size == d for x in v))
                keep = [i for i, x in enumerate(v) if x.size == dim]
                if not keep:
                    del by[pid], src[pid]
                    continue
                by[pid], src[pid] = [v[i] for i in keep], [src[pid][i] for i in keep]
            self.assistant_ids = {p["id"] for p in self.store.people() if p.get("kind") == "assistant"}
            self._samples = {pid: np.array(v) for pid, v in by.items()}
            self._sources = src
            self._centroids = {pid: _norm(np.mean(v, axis=0)) for pid, v in by.items()}

    def embed(self, audio: np.ndarray) -> np.ndarray:
        return _norm(self.embedder.embed(to_f32(audio)))

    def enroll(self, name: str, audios: list[np.ndarray], consent: str, source: str = "enrol") -> int:
        """Create (or extend) a person from >=1 audio samples. `consent` is recorded in the audit log."""
        if not consent.strip():
            raise ValueError("consent note is required to enrol a voice")
        person = self.store.person_by_name(name)
        pid = person["id"] if person else self.store.add_person(name, consent)
        for a in audios:
            self.store.add_voice_sample(pid, self.embed(a), source)
        self.reload()
        return pid

    def assistant_like(self, pid: int, floor: float = 0.45) -> bool:
        """Does this saved person sound like the assistant's own voice (it was probably picked up by the mic and saved by mistake)?"""
        mine = self._samples.get(pid)
        if mine is None or pid in self.assistant_ids:
            return False
        best = [self._samples[a] for a in self.assistant_ids if a in self._samples]
        if not best:
            return False
        a = np.concatenate(best)
        if a.shape[1] != mine.shape[1]:
            return False
        return float((mine @ a.T).max(axis=1).mean()) >= floor

    def ready_for(self, pid: int) -> bool:
        """Can this person be recognised right now (do they have samples made by the current model)?"""
        return pid in self._samples

    def person_score(self, e: np.ndarray, pid: int) -> float:
        m = self._samples.get(pid)
        return top_k(m @ e) if m is not None and m.shape[1] == e.size else 0.0

    def score(self, audio: np.ndarray, pid: int) -> float:
        """Closeness of this audio to a person's voiceprint (used to calibrate, not to decide)."""
        with self._lock:
            return self.person_score(self.embed(audio), pid)

    def sources(self, pid: int) -> dict[str, int]:
        """How many samples a person has per capture source ('laptop', 'buds', ...)."""
        out: dict[str, int] = {}
        for x in self._sources.get(pid, []):
            out[_src_key(x)] = out.get(_src_key(x), 0) + 1
        return out

    ADAPT_CAP = 40

    def adapt(self, pid: int, emb: np.ndarray, source: str, seconds: float, raw: float) -> bool:
        """Learn from a turn that was clearly this person (long enough, well above the threshold). Capped per microphone; reversible."""
        if seconds < 2.0 or raw < self.threshold + 0.05:
            return False
        tag = f"adapt:{source}"
        self.store.add_voice_sample(pid, _norm(emb), tag)
        self.store.delete_voice_samples(pid, tag, keep_newest=self.ADAPT_CAP)       # oldest beyond the cap go
        self.reload()
        return True

    def forget_adapted(self, pid: int, since: float = 0.0) -> int:
        n = self.store.delete_voice_samples(pid, "adapt:%", since)
        self.reload()
        return n

    def health(self, pid: int) -> dict:
        """How well can this person be told apart, per microphone: own scores (each sample vs the others) and the nearest stranger."""
        with self._lock:
            m, src = self._samples.get(pid), self._sources.get(pid, [])
            if m is None or len(m) < 2:
                return {"sources": {}, "nearest_stranger": 0.0, "verdict": "needs_more", "advice": "Record your voice first."}
            keys = [_src_key(x) for x in src]
            per: dict[str, dict] = {}
            for k in sorted(set(keys)):
                idx = [i for i, x in enumerate(keys) if x == k]
                own = []
                for i in idx:
                    rest = np.delete(m, i, 0)
                    own.append(top_k(rest @ m[i]))
                per[k] = {"samples": len(idx), "own_min": round(min(own), 2), "own_mean": round(float(np.mean(own)), 2)}
            coh = self._cohort_for(pid)
            near = float(max(top_k(m @ c) for c in coh)) if coh is not None else 0.0
        worst = min(v["own_min"] for v in per.values())
        gap = worst - near
        few = [k for k, v in per.items() if v["samples"] < 3]
        if coh is None:
            verdict, advice = "needs_more", "Keep talking with Sidekick on: it is still learning how other voices sound."
        elif gap >= 0.15 and not few:
            verdict, advice = "good", "Your voice is recognised well on every microphone you set up."
        elif gap > 0:
            verdict, advice = "fair", "Recognition works but close calls are possible. Record your voice once more on the microphone you use most."
        else:
            verdict, advice = "needs_more", "Some voices sound too much like yours on this microphone. Record 20 seconds on the buds and the Mac."
        return {"sources": per, "nearest_stranger": round(near, 2), "verdict": verdict, "advice": advice}

    def _cohort_for(self, pid: int) -> np.ndarray | None:
        pool = list(self.cohort)
        for other, m in self._samples.items():
            if other != pid:
                pool.extend(m)
        pool = [x for x in pool if x.size == self._centroids[pid].size] if pid in self._centroids else []
        return np.array(pool) if len(pool) >= self.cohort_min else None

    def z_score(self, e: np.ndarray, pid: int, raw: float) -> float | None:
        coh = self._cohort_for(pid)
        if coh is None:
            return None
        return snorm(raw, coh @ e, coh @ self._centroids[pid])

    def add_clips(self, pid: int, audios: list[np.ndarray], source: str = "enrol") -> int:
        for a in audios:
            self.store.add_voice_sample(pid, self.embed(a), source)
        self.reload()
        return len(audios)

    def add_sample(self, pid: int, audio_or_emb: np.ndarray, source: str = "adapt") -> None:
        emb = audio_or_emb if audio_or_emb.ndim == 1 and audio_or_emb.dtype == np.float32 and audio_or_emb.size == 256 \
            else self.embed(audio_or_emb)
        self.store.add_voice_sample(pid, _norm(emb), source)
        self.reload()

    def similar_voices(self, pid: int, threshold: float = 0.6) -> list[dict]:
        """Other enrolled people whose voiceprint is close to this person's (identification may confuse them)."""
        with self._lock:
            me = self._centroids.get(pid)
            if me is None:
                return []
            out = []
            for other, c in self._centroids.items():
                if other != pid and float(me @ c) >= threshold:
                    p = self.store.person(other)
                    out.append({"person_id": other, "name": p["name"] if p else "?", "score": round(float(me @ c), 2)})
            return sorted(out, key=lambda x: -x["score"])

    # ---- identification ----------------------------------------------------------------
    def _accept(self, e: np.ndarray) -> tuple[int, float] | tuple[None, float]:
        """Who (if anyone) does this embedding belong to? No side effects. Caller holds the lock."""
        scores = sorted(((self.person_score(e, pid), pid) for pid in self._samples), reverse=True)
        if scores and scores[0][0] >= self.threshold - self.raw_floor and (
                len(scores) == 1 or scores[0][0] - scores[1][0] >= self.margin):
            raw, pid = scores[0]
            z = self.z_score(e, pid, raw)
            ok = raw >= self.threshold if z is None else (z >= self.z_min or raw >= self.threshold + 0.1)
            if ok and self.store.person(pid):
                return pid, raw
        return None, scores[0][0] if scores else 0.0

    def identify(self, audio: np.ndarray, prev: dict | None = None) -> Match:
        """`prev` = the turn just before ({emb, seconds, gap, person_id}): a weak segment that clearly continues it is scored as part of it."""
        seconds = audio.size / 16000
        if seconds < self.min_seconds:
            return Match(None, None, None, 0.0, too_short=True)
        e = self.embed(audio)
        with self._lock:
            pid, raw = self._accept(e)
            pooled = False
            if pid is None and prev and prev.get("gap", 9) <= 0.8 and prev.get("person_id") is not None \
                    and raw >= self.threshold - 0.10 and float(e @ prev["emb"]) >= 0.5:
                mix = _norm(e * seconds + prev["emb"] * prev["seconds"])
                pid2, raw2 = self._accept(mix)
                if pid2 == prev["person_id"]:
                    pid, raw, pooled = pid2, raw2, True
            if pid is not None:
                return Match(pid, self.store.person(pid)["name"], None, raw, True, embedding=e, pooled=pooled)
            self.cohort.append(e)
            del self.cohort[:-200]
            c = self._assign_cluster(e, audio, raw)
            if c.person_id is None and len(c.embs) >= self.promote_min:     # cluster first, label the whole cluster from its pooled voice
                pid2, raw2 = self._accept(_norm(np.mean(c.embs, axis=0)))
                if pid2 is not None and raw2 >= self.threshold:
                    c.person_id = pid2
                    self.store.add_voice_sample(pid2, _norm(np.mean(c.embs, axis=0)), "adapt:cluster")
                    self.reload()
                    return Match(pid2, self.store.person(pid2)["name"], c.label, raw2, True, embedding=e, pooled=True, promoted=True)
            if c.person_id is not None:
                return Match(c.person_id, self.store.person(c.person_id)["name"], c.label, raw, True, embedding=e, pooled=True, promoted=True)
            return Match(None, None, c.label, raw, False, embedding=e)

    def _remember_clip(self, c: "_Cluster", audio: np.ndarray | None) -> None:
        if audio is None:
            return
        a = audio if audio.dtype == np.int16 else (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        c.audio = np.concatenate([c.audio, a])[-16000 * 6:]

    def clip(self, label: str) -> np.ndarray | None:
        with self._lock:
            c = next((x for x in self._clusters if x.label == label), None)
            return None if c is None or c.audio.size == 0 else c.audio.copy()

    def _assign_cluster(self, e: np.ndarray, audio: np.ndarray | None = None, raw: float = 1.0) -> "_Cluster":
        best, best_s = None, -1.0
        for c in self._clusters:
            if c.person_id is not None and raw < self.threshold - 0.2:
                continue                                              # a recognised cluster does not swallow a clearly different voice
            s = float(e @ c.centroid)
            if s > best_s:
                best, best_s = c, s
        if best is not None and best_s >= self.cluster_threshold:
            best.embs.append(e)
            del best.embs[:-30]
            self._remember_clip(best, audio)
            return best
        label = "Speaker " + (string.ascii_uppercase[len(self._clusters) % 26] + ("" if len(self._clusters) < 26 else str(len(self._clusters) // 26)))
        c = _Cluster(label, [e])
        self._remember_clip(c, audio)
        self._clusters.append(c)
        return c

    # ---- naming / correction ------------------------------------------------------------------
    def name_cluster(self, label: str, name: str, consent: str) -> int:
        """Promote a provisional cluster ("Speaker A") to an enrolled person."""
        if not consent.strip():
            raise ValueError("consent note is required to enrol a voice")
        with self._lock:
            c = next((x for x in self._clusters if x.label == label), None)
            if c is None:
                raise KeyError(f"no such cluster {label}")
            person = self.store.person_by_name(name)
            pid = person["id"] if person else self.store.add_person(name, consent)
            for e in c.embs[-10:]:
                self.store.add_voice_sample(pid, e, "cluster")
            self._clusters.remove(c)
        self.reload()
        return pid

    def cluster_info(self, label: str):
        """(pooled voice, last few seconds of audio) of a provisional cluster, or None."""
        with self._lock:
            c = next((x for x in self._clusters if x.label == label), None)
            return None if c is None else (_norm(np.mean(c.embs, axis=0)), c.audio.copy())

    def drop_cluster(self, label: str) -> None:
        with self._lock:
            self._clusters[:] = [c for c in self._clusters if c.label != label]

    def would_match(self, emb: np.ndarray) -> int | None:
        """The enrolled person this pooled voice belongs to, if any (used to hide stored unnamed voices that were enrolled since)."""
        with self._lock:
            return self._accept(_norm(emb))[0]

    def clusters(self) -> list[dict]:
        with self._lock:
            return [{"label": c.label, "samples": len(c.embs)} for c in self._clusters if c.person_id is None]

    def reset_session(self) -> None:
        with self._lock:
            self._clusters.clear()
