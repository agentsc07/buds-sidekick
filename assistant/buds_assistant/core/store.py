"""SQLite store: people, voiceprints, conversations, segments, facts, bookmarks, hints, audit.

Privacy rules enforced here: `forget()` removes every trace of a person (rows, audio files, voiceprint);
secure_delete is on so freed pages are overwritten.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT UNIQUE, created REAL, consent_note TEXT,
  consent_ts REAL, policy TEXT DEFAULT 'transcript', retention_days INTEGER DEFAULT 0, color TEXT);
CREATE TABLE IF NOT EXISTS voice_samples(id INTEGER PRIMARY KEY, person_id INTEGER, embedding BLOB, ts REAL, source TEXT);
CREATE TABLE IF NOT EXISTS conversations(id INTEGER PRIMARY KEY, start REAL, end REAL, mode TEXT, placement TEXT, title TEXT);
CREATE TABLE IF NOT EXISTS segments(id INTEGER PRIMARY KEY, conv_id INTEGER, t0 REAL, t1 REAL, speaker_id INTEGER,
  cluster TEXT, conf REAL, text TEXT, lang TEXT, audio_ref TEXT, embedding BLOB, experimental INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_seg_speaker ON segments(speaker_id);
CREATE INDEX IF NOT EXISTS ix_seg_conv ON segments(conv_id);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, person_id INTEGER, kind TEXT, text TEXT, due TEXT,
  source_segment INTEGER, status TEXT DEFAULT 'open', created REAL, owner TEXT);
CREATE TABLE IF NOT EXISTS bookmarks(id INTEGER PRIMARY KEY, conv_id INTEGER, ts REAL, speaker_id INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS hints(id INTEGER PRIMARY KEY, ts REAL, trigger TEXT, text TEXT, person_id INTEGER,
  spoken INTEGER, feedback INTEGER, sources TEXT);
CREATE TABLE IF NOT EXISTS autopilot_decisions(id INTEGER PRIMARY KEY, ts REAL, conv_id INTEGER, trigger TEXT, outcome TEXT,
  reason TEXT, text TEXT, person_id INTEGER, hint_id INTEGER, fact_id INTEGER);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, title TEXT, start REAL, end REAL, people TEXT, place TEXT,
  sample INTEGER DEFAULT 0, announced INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, text TEXT, due REAL, status TEXT DEFAULT 'open', sample INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS todos(id INTEGER PRIMARY KEY, text TEXT, due_text TEXT, due REAL, status TEXT DEFAULT 'open', source TEXT,
  fact_id INTEGER, created REAL, sample INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS unnamed_voices(id INTEGER PRIMARY KEY, conv_id INTEGER, label TEXT, first_seen REAL, last_seen REAL,
  count INTEGER, seconds REAL, centroid BLOB, clip BLOB, last_text TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, detail TEXT);
"""
PALETTE = ["#2f6fed", "#e0762b", "#1a9c57", "#9b59d0", "#c2385a", "#0e9aa7", "#8a6d00", "#5b6b8a"]


def _vec(b: bytes | None) -> np.ndarray | None:
    return None if b is None else np.frombuffer(b, dtype=np.float32).copy()


class Store:
    def __init__(self, data_dir: Path, name: str = "sidekick.db") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / name, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.db.execute("PRAGMA secure_delete=ON")
            self.db.executescript(SCHEMA)
            cols = {r[1] for r in self.db.execute("PRAGMA table_info(autopilot_decisions)")}
            pcols = {r[1] for r in self.db.execute("PRAGMA table_info(people)")}
            if "kind" not in pcols:                                     # 'person' or 'assistant' (the assistant's own speaking voice)
                self.db.execute("ALTER TABLE people ADD COLUMN kind TEXT DEFAULT 'person'")
            if "fact_id" not in cols:                                   # tables made before the Undo button existed
                self.db.execute("ALTER TABLE autopilot_decisions ADD COLUMN fact_id INTEGER")
            self.db.commit()

    # ---- generic ---------------------------------------------------------------
    def _x(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def close(self) -> None:
        with self._lock:
            self.db.close()

    # ---- people ------------------------------------------------------------------
    def add_person(self, name: str, consent_note: str = "", policy: str = "transcript", kind: str = "person") -> int:
        n = self.q("SELECT COUNT(*) c FROM people")[0]["c"]
        cur = self._x("INSERT INTO people(name, created, consent_note, consent_ts, policy, color, kind) VALUES(?,?,?,?,?,?,?)",
                      (name, time.time(), consent_note, time.time(), policy, PALETTE[n % len(PALETTE)], kind))
        self.audit("enrol", {"person_id": cur.lastrowid, "consent": consent_note})
        return cur.lastrowid

    def people(self) -> list[dict]:
        rows = self.q("SELECT * FROM people ORDER BY name")
        for r in rows:
            r["samples"] = self.q("SELECT COUNT(*) c FROM voice_samples WHERE person_id=?", (r["id"],))[0]["c"]
        return rows

    def mark_assistant(self, pid: int) -> None:
        """This 'person' is the assistant's own speaking voice: it is not listed, and what it 'said' is not a conversation, so it is removed."""
        self._x("UPDATE people SET kind='assistant', policy='none' WHERE id=?", (pid,))
        with self._lock:
            for table, col in (("segments", "speaker_id"), ("facts", "person_id"), ("bookmarks", "speaker_id"), ("hints", "person_id"), ("autopilot_decisions", "person_id")):
                self.db.execute(f"DELETE FROM {table} WHERE {col}=?", (pid,))
            self.db.commit()
        self.audit("assistant_voice", {"person_id": pid})

    def person(self, pid: int) -> dict | None:
        r = self.q("SELECT * FROM people WHERE id=?", (pid,))
        return r[0] if r else None

    def person_by_name(self, name: str) -> dict | None:
        r = self.q("SELECT * FROM people WHERE lower(name)=lower(?)", (name,))
        return r[0] if r else None

    def rename_person(self, pid: int, name: str) -> None:
        self._x("UPDATE people SET name=? WHERE id=?", (name, pid))

    def set_policy(self, pid: int, policy: str, retention_days: int = 0) -> None:
        if policy not in ("none", "transcript", "audio"):
            raise ValueError("policy must be none|transcript|audio")
        self._x("UPDATE people SET policy=?, retention_days=? WHERE id=?", (policy, retention_days, pid))

    def add_voice_sample(self, pid: int, emb: np.ndarray, source: str = "enrol") -> None:
        self._x("INSERT INTO voice_samples(person_id, embedding, ts, source) VALUES(?,?,?,?)",
                (pid, np.asarray(emb, dtype=np.float32).tobytes(), time.time(), source))

    def delete_voice_samples(self, pid: int, source_like: str, since: float = 0.0, keep_newest: int = 0) -> int:
        """Delete samples of a person whose source matches (e.g. 'adapt:%'), newer than `since`; `keep_newest` spares the newest N."""
        rows = self.q("SELECT id FROM voice_samples WHERE person_id=? AND source LIKE ? AND ts>=? ORDER BY ts DESC", (pid, source_like, since))
        ids = [r["id"] for r in rows][keep_newest:]
        for i in ids:
            self._x("DELETE FROM voice_samples WHERE id=?", (i,))
        return len(ids)

    # ---- voices that were heard but not named (kept for a few days so People can ask about them) ----------------------
    def upsert_unnamed(self, conv_id: int, label: str, centroid: np.ndarray, clip: np.ndarray, text: str, seconds: float) -> int:
        now = time.time()
        rows = self.q("SELECT * FROM unnamed_voices WHERE conv_id=? AND label=?", (conv_id, label))
        c32 = np.asarray(centroid, dtype=np.float32)
        if not rows:
            return self._x("INSERT INTO unnamed_voices(conv_id, label, first_seen, last_seen, count, seconds, centroid, clip, last_text) VALUES(?,?,?,?,?,?,?,?,?)",
                           (conv_id, label, now, now, 1, seconds, c32.tobytes(), np.asarray(clip, dtype=np.int16)[-16000 * 6:].tobytes(), text)).lastrowid
        r = rows[0]
        old = np.frombuffer(r["clip"] or b"", dtype=np.int16)
        self._x("UPDATE unnamed_voices SET last_seen=?, count=count+1, seconds=seconds+?, centroid=?, clip=?, last_text=? WHERE id=?",
                (now, seconds, c32.tobytes(), np.concatenate([old, np.asarray(clip, dtype=np.int16)])[-16000 * 6:].tobytes(), text, r["id"]))
        return r["id"]

    def unnamed_voices(self) -> list[dict]:
        rows = self.q("SELECT * FROM unnamed_voices ORDER BY last_seen DESC")
        for r in rows:
            r["centroid"] = _vec(r["centroid"])
            r["clip"] = np.frombuffer(r["clip"] or b"", dtype=np.int16)
        return rows

    def delete_unnamed(self, ids: list[int] | None = None, conv_id: int | None = None, label: str | None = None) -> int:
        if ids is not None:
            return sum(self._x("DELETE FROM unnamed_voices WHERE id=?", (i,)).rowcount for i in ids)
        if conv_id is not None and label is not None:
            return self._x("DELETE FROM unnamed_voices WHERE conv_id=? AND label=?", (conv_id, label)).rowcount
        return self._x("DELETE FROM unnamed_voices").rowcount

    def expire_unnamed(self, days: int) -> int:
        return self._x("DELETE FROM unnamed_voices WHERE last_seen < ?", (time.time() - days * 86400,)).rowcount

    def voice_samples(self, pid: int | None = None) -> list[dict]:
        rows = self.q("SELECT * FROM voice_samples" + (" WHERE person_id=?" if pid else ""), (pid,) if pid else ())
        for r in rows:
            r["embedding"] = _vec(r["embedding"])
        return rows

    # ---- conversations / segments ----------------------------------------------------
    def start_conversation(self, mode: str, placement: str = "ear") -> int:
        return self._x("INSERT INTO conversations(start, mode, placement) VALUES(?,?,?)", (time.time(), mode, placement)).lastrowid

    def end_conversation(self, cid: int, title: str | None = None) -> None:
        self._x("UPDATE conversations SET end=?, title=COALESCE(?, title) WHERE id=?", (time.time(), title, cid))

    def conversations(self, limit: int = 50) -> list[dict]:
        rows = self.q("SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["segments"] = self.q("SELECT COUNT(*) c FROM segments WHERE conv_id=?", (r["id"],))[0]["c"]
        return rows

    def add_segment(self, cid: int, t0: float, t1: float, speaker_id: int | None, cluster: str | None, conf: float,
                    text: str, lang: str = "en", audio_ref: str | None = None, experimental: bool = False) -> int:
        return self._x("INSERT INTO segments(conv_id,t0,t1,speaker_id,cluster,conf,text,lang,audio_ref,experimental) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)", (cid, t0, t1, speaker_id, cluster, conf, text, lang, audio_ref,
                                                       int(experimental))).lastrowid

    def set_segment_embedding(self, sid: int, emb: np.ndarray) -> None:
        self._x("UPDATE segments SET embedding=? WHERE id=?", (np.asarray(emb, dtype=np.float32).tobytes(), sid))

    def reassign_segment(self, sid: int, person_id: int | None) -> None:
        self._x("UPDATE segments SET speaker_id=? WHERE id=?", (person_id, sid))
        self.audit("correct_label", {"segment": sid, "person_id": person_id})

    def segments(self, conv_id: int | None = None, person_id: int | None = None, since: float | None = None,
                 with_embedding: bool = False, limit: int = 2000) -> list[dict]:
        where, args = [], []
        if conv_id is not None:
            where.append("s.conv_id=?"); args.append(conv_id)
        if person_id is not None:
            where.append("s.speaker_id=?"); args.append(person_id)
        if since is not None:
            where.append("s.t0>=?"); args.append(since)
        sql = ("SELECT s.*, p.name AS speaker, p.color AS color FROM segments s LEFT JOIN people p ON p.id=s.speaker_id"
               + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY s.t0 DESC LIMIT ?")
        rows = self.q(sql, tuple(args) + (limit,))
        rows.reverse()
        for r in rows:
            e = _vec(r["embedding"])
            r["embedding"] = e if with_embedding else None
        return rows

    # ---- facts, bookmarks, hints, audit ------------------------------------------------
    def add_fact(self, person_id: int | None, kind: str, text: str, due: str | None = None,
                 source_segment: int | None = None, owner: str | None = None) -> int:
        return self._x("INSERT INTO facts(person_id, kind, text, due, source_segment, created, owner) VALUES(?,?,?,?,?,?,?)",
                       (person_id, kind, text, due, source_segment, time.time(), owner)).lastrowid

    def facts(self, person_id: int | None = None, kind: str | None = None, status: str | None = None) -> list[dict]:
        where, args = [], []
        for col, val in (("person_id", person_id), ("kind", kind), ("status", status)):
            if val is not None:
                where.append(f"{col}=?"); args.append(val)
        return self.q("SELECT * FROM facts" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id", tuple(args))

    def set_fact_status(self, fid: int, status: str) -> None:
        self._x("UPDATE facts SET status=? WHERE id=?", (status, fid))

    def add_bookmark(self, cid: int | None, ts: float, speaker_id: int | None, note: str = "") -> int:
        return self._x("INSERT INTO bookmarks(conv_id, ts, speaker_id, note) VALUES(?,?,?,?)", (cid, ts, speaker_id, note)).lastrowid

    def bookmarks(self, cid: int | None = None) -> list[dict]:
        return self.q("SELECT * FROM bookmarks" + (" WHERE conv_id=?" if cid else "") + " ORDER BY ts", (cid,) if cid else ())

    def log_hint(self, trigger: str, text: str, person_id: int | None, spoken: bool, sources: list | None = None) -> int:
        return self._x("INSERT INTO hints(ts, trigger, text, person_id, spoken, sources) VALUES(?,?,?,?,?,?)",
                       (time.time(), trigger, text, person_id, int(spoken), json.dumps(sources or []))).lastrowid

    def rate_hint(self, hid: int, useful: bool) -> None:
        self._x("UPDATE hints SET feedback=? WHERE id=?", (1 if useful else -1, hid))

    def hints(self, limit: int = 100) -> list[dict]:
        return self.q("SELECT * FROM hints ORDER BY id DESC LIMIT ?", (limit,))

    def log_decision(self, trigger: str, outcome: str, reason: str | None, text: str, person_id: int | None,
                     conv_id: int | None, hint_id: int | None, fact_id: int | None = None) -> int:
        """Every Autopilot candidate: said | noted | held_back (with a reason), so silence is explainable."""
        return self._x("INSERT INTO autopilot_decisions(ts, conv_id, trigger, outcome, reason, text, person_id, hint_id, fact_id) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (time.time(), conv_id, trigger, outcome, reason, text, person_id, hint_id, fact_id)).lastrowid

    def decisions(self, limit: int = 100) -> list[dict]:
        return self.q("SELECT * FROM autopilot_decisions ORDER BY id LIMIT ?", (limit,)) if limit >= 10 ** 6 else \
            list(reversed(self.q("SELECT * FROM autopilot_decisions ORDER BY id DESC LIMIT ?", (limit,))))

    def audit(self, kind: str, detail: dict | None = None) -> None:
        self._x("INSERT INTO audit(ts, kind, detail) VALUES(?,?,?)", (time.time(), kind, json.dumps(detail or {})))

    def audit_log(self, limit: int = 200) -> list[dict]:
        rows = self.q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["detail"] = json.loads(r["detail"] or "{}")
        return rows

    # ---- privacy ------------------------------------------------------------------------
    def forget_preview(self, pid: int) -> dict:
        """What forget() would delete (counts only). Deletes nothing."""
        with self._lock:
            counts = {"audio_files": self.db.execute("SELECT COUNT(*) FROM segments WHERE speaker_id=? AND audio_ref IS NOT NULL",
                                                     (pid,)).fetchone()[0]}
            for table, col in (("segments", "speaker_id"), ("facts", "person_id"), ("voice_samples", "person_id"),
                               ("bookmarks", "speaker_id"), ("hints", "person_id"), ("autopilot_decisions", "person_id")):
                counts[table] = self.db.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (pid,)).fetchone()[0]
            counts["people"] = self.db.execute("SELECT COUNT(*) FROM people WHERE id=?", (pid,)).fetchone()[0]
        return counts

    def forget(self, pid: int) -> dict:
        """Delete everything about a person. Returns counts only (never content) and logs that it happened."""
        counts: dict[str, int] = {}
        with self._lock:
            refs = [r["audio_ref"] for r in self.db.execute(
                "SELECT audio_ref FROM segments WHERE speaker_id=? AND audio_ref IS NOT NULL", (pid,)).fetchall()]
            for ref in refs:
                try:
                    Path(ref).unlink()
                except OSError:
                    pass
            counts["audio_files"] = len(refs)
            for table, col in (("segments", "speaker_id"), ("facts", "person_id"), ("voice_samples", "person_id"),
                               ("bookmarks", "speaker_id"), ("hints", "person_id"), ("autopilot_decisions", "person_id")):
                cur = self.db.execute(f"DELETE FROM {table} WHERE {col}=?", (pid,))
                counts[table] = cur.rowcount
            counts["people"] = self.db.execute("DELETE FROM people WHERE id=?", (pid,)).rowcount
            self.db.commit()
        shutil.rmtree(self.data_dir / "people" / str(pid), ignore_errors=True)
        self.audit("forget", {"person_id": pid, "deleted": counts})
        return counts

    def wipe(self) -> dict:
        """Delete every person, conversation, fact, hint and recording. Only the audit trail stays (plus one line saying this happened)."""
        counts: dict[str, int] = {}
        with self._lock:
            for table in ("segments", "facts", "bookmarks", "hints", "autopilot_decisions", "voice_samples", "conversations", "people",
                          "events", "reminders", "todos", "unnamed_voices"):
                counts[table] = self.db.execute(f"DELETE FROM {table}").rowcount
            self.db.commit()
        for name in ("people", "audio"):
            shutil.rmtree(self.data_dir / name, ignore_errors=True)
        (self.data_dir / "notes.jsonl").unlink(missing_ok=True)
        self.audit("delete_everything", counts)
        return counts

    def update_decision(self, hint_id: int, outcome: str, reason: str | None) -> int:
        return self._x("UPDATE autopilot_decisions SET outcome=?, reason=? WHERE hint_id=?", (outcome, reason, hint_id)).rowcount

    def sweep_retention(self, now: float | None = None) -> int:
        """Delete stored audio older than each person's retention_days (transcripts stay)."""
        now = now or time.time()
        n = 0
        for p in self.q("SELECT id, retention_days FROM people WHERE retention_days>0"):
            cutoff = now - p["retention_days"] * 86400
            for r in self.q("SELECT id, audio_ref FROM segments WHERE speaker_id=? AND audio_ref IS NOT NULL AND t1<?",
                            (p["id"], cutoff)):
                try:
                    Path(r["audio_ref"]).unlink()
                except OSError:
                    pass
                self._x("UPDATE segments SET audio_ref=NULL WHERE id=?", (r["id"],))
                n += 1
        return n
