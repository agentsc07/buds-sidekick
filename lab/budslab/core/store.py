"""SQLite (events, attempts, notes, commands, sessions) + JSONL raw capture per session."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .events import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, started REAL, mode TEXT, device TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, session_id TEXT, seq INTEGER, ts REAL, t REAL, layer TEXT, source TEXT, type TEXT,
  side TEXT, data TEXT, raw_hex TEXT, experiment_id TEXT);
CREATE INDEX IF NOT EXISTS ix_events_session ON events(session_id, seq);
CREATE INDEX IF NOT EXISTS ix_events_type ON events(type);
CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY, session_id TEXT, experiment_id TEXT, status TEXT, started REAL, ended REAL,
  matched TEXT, signals TEXT, manual INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, session_id TEXT, experiment_id TEXT, ts REAL, t REAL,
  text TEXT, window_start REAL, window_end REAL);
CREATE TABLE IF NOT EXISTS commands(
  id INTEGER PRIMARY KEY, session_id TEXT, ts REAL, t REAL, name TEXT, args TEXT, status TEXT,
  latency_ms REAL, result TEXT, experiment_id TEXT);
"""


class Store:
    def __init__(self, data_dir: Path, session_id: str, mode: str = "", device: str = "") -> None:
        self.data_dir = Path(data_dir)
        self.session_id = session_id
        self.session_dir = self.data_dir / "sessions" / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / "budslab.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?)",
                            (session_id, time.time(), mode, device, "{}"))
            self.db.commit()
        self._raw = open(self.session_dir / "raw.jsonl", "a", buffering=1, encoding="utf-8")

    def close(self) -> None:
        with self._lock:
            self.db.commit()
            self.db.close()
        self._raw.close()

    # ---- writes -------------------------------------------------------------
    def add_event(self, e: Event) -> None:
        d = e.to_dict()
        self._raw.write(json.dumps(d, separators=(",", ":")) + "\n")
        with self._lock:
            self.db.execute(
                "INSERT INTO events(session_id,seq,ts,t,layer,source,type,side,data,raw_hex,experiment_id)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (e.session_id, e.seq, e.ts, e.t, e.layer, e.source, e.type, e.side, json.dumps(e.data),
                 e.raw_hex, e.experiment_id))
            self.db.commit()

    def add_attempt(self, experiment_id: str, status: str, started: float, ended: float,
                    matched: list, signals: list, manual: bool = False) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO attempts(session_id,experiment_id,status,started,ended,matched,signals,manual)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (self.session_id, experiment_id, status, started, ended, json.dumps(matched),
                 json.dumps(signals), int(manual)))
            self.db.commit()
            return cur.lastrowid

    def update_attempt(self, attempt_id: int, status: str, manual: bool) -> None:
        with self._lock:
            self.db.execute("UPDATE attempts SET status=?, manual=? WHERE id=?", (status, int(manual), attempt_id))
            self.db.commit()

    def add_note(self, text: str, experiment_id: str | None, t: float, w0: float | None = None,
                 w1: float | None = None) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO notes(session_id,experiment_id,ts,t,text,window_start,window_end) VALUES(?,?,?,?,?,?,?)",
                (self.session_id, experiment_id, time.time(), t, text, w0, w1))
            self.db.commit()
            return cur.lastrowid

    def add_command(self, ts: float, t: float, name: str, args: dict, status: str, latency_ms: float | None,
                    result: dict, experiment_id: str | None) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO commands(session_id,ts,t,name,args,status,latency_ms,result,experiment_id)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (self.session_id, ts, t, name, json.dumps(args), status, latency_ms, json.dumps(result),
                 experiment_id))
            self.db.commit()

    # ---- reads --------------------------------------------------------------
    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def events(self, *, session: str | None = "current", types: list[str] | None = None,
               layer: str | None = None, since_seq: int = 0, limit: int = 2000,
               msg_id: int | None = None, direction: str | None = None) -> list[dict[str, Any]]:
        where, args = ["seq > ?"], [since_seq]
        if session == "current":
            where.append("session_id = ?"); args.append(self.session_id)
        elif session:
            where.append("session_id = ?"); args.append(session)
        if types:
            where.append(f"type IN ({','.join('?' * len(types))})"); args += types
        if layer:
            where.append("layer = ?"); args.append(layer)
        rows = self.q(f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?", tuple(args + [limit]))
        rows.reverse()
        out = []
        for r in rows:
            r["data"] = json.loads(r["data"] or "{}")
            if msg_id is not None and r["data"].get("msg_id") != msg_id:
                continue
            if direction and r["data"].get("dir") != direction:
                continue
            out.append(r)
        return out
