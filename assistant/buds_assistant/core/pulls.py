"""Background downloads for first-run setup: Ollama models (with progress) and the voice model.

One thread per item; `snapshot()` is what the dashboard polls. States: idle | running | done | failed.
"""
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path


class Downloads:
    def __init__(self, host: str = "http://127.0.0.1:11434") -> None:
        self.host = host.rstrip("/")
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._items.items()}

    def busy(self) -> bool:
        return any(v["state"] == "running" for v in self.snapshot().values())

    def _set(self, key: str, **kw) -> None:
        with self._lock:
            self._items.setdefault(key, {"state": "idle", "pct": 0, "status": ""}).update(kw)

    def _start(self, key: str, fn, *args) -> None:
        with self._lock:
            if self._items.get(key, {}).get("state") == "running":
                return
        self._set(key, state="running", pct=0, status="Starting…", error="")
        threading.Thread(target=fn, args=(key, *args), daemon=True).start()

    def pull_model(self, name: str) -> None:
        self._start(name, self._pull, name)

    def fetch_file(self, key: str, url: str, dest: Path) -> None:
        self._start(key, self._fetch, url, dest)

    def _pull(self, key: str, name: str) -> None:
        try:
            req = urllib.request.Request(self.host + "/api/pull", json.dumps({"model": name, "stream": True}).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                for line in r:
                    d = json.loads(line)
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    total, done = d.get("total"), d.get("completed")
                    self._set(key, status=d.get("status", ""), **({"pct": round(100 * done / total)} if total and done is not None else {}))
            self._set(key, state="done", pct=100, status="Ready")
        except Exception as exc:
            self._set(key, state="failed", error=str(exc)[:200], status="Failed")

    def _fetch(self, key: str, url: str, dest: Path) -> None:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
                total, got = int(r.headers.get("Content-Length") or 0), 0
                while chunk := r.read(1 << 16):
                    f.write(chunk); got += len(chunk)
                    if total:
                        self._set(key, pct=round(100 * got / total), status="Downloading")
            part.rename(dest)
            self._set(key, state="done", pct=100, status="Ready")
        except Exception as exc:
            self._set(key, state="failed", error=str(exc)[:200], status="Failed")
