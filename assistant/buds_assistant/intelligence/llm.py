"""Local LLM access (Ollama) behind a small interface, plus a deterministic fake for tests."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from typing import Callable

import numpy as np


class LLMError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434", chat_model: str = "qwen3.5:4b-mlx",
                 embed_model: str = "nomic-embed-text", timeout: float = 90.0) -> None:
        self.host, self.chat_model, self.embed_model, self.timeout = host.rstrip("/"), chat_model, embed_model, timeout
        self._avail: tuple[float, bool] = (0.0, False)
        self.pinned: set[str] = set()                    # models kept resident while a mode needs them (e.g. interpreter)

    def _post(self, path: str, body: dict, timeout: float | None = None) -> dict:
        req = urllib.request.Request(self.host + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout or self.timeout))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            self._avail = (time.time(), False)
            raise LLMError(f"ollama unreachable: {exc}") from exc

    def available(self) -> bool:
        if time.time() - self._avail[0] < 5:
            return self._avail[1]
        try:
            urllib.request.urlopen(self.host + "/api/tags", timeout=1.5).read()
            ok = True
        except (urllib.error.URLError, OSError, TimeoutError):
            ok = False
        self._avail = (time.time(), ok)
        return ok

    def chat(self, messages: list[dict], model: str | None = None, max_tokens: int = 160, temperature: float = 0.2,
             json_mode: bool = False, keep_alive: str | None = None, timeout: float | None = None) -> str:
        # The everyday chat model stays resident; big one-off models (translation, deep) unload soon after use.
        # On a 16 GB Mac, keeping several models loaded makes Ollama swap and answers take 10-25 s instead of ~1 s.
        keep = keep_alive or ("30m" if model in (None, self.chat_model) or model in self.pinned else "90s")
        body = {"model": model or self.chat_model, "messages": messages, "stream": False, "think": False,
                "keep_alive": keep, "options": {"temperature": temperature, "num_predict": max_tokens}}
        if json_mode:
            body["format"] = "json"
        out = self._post("/api/chat", body, timeout)["message"]["content"].strip()
        return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()

    def unload(self, *models: str) -> None:
        """Ask Ollama to drop models from memory now (keep_alive 0)."""
        for m in models:
            try:
                if m == self.embed_model:
                    self._post("/api/embed", {"model": m, "input": ["bye"], "keep_alive": 0}, timeout=15)
                else:
                    self._post("/api/chat", {"model": m, "messages": [{"role": "user", "content": "bye"}], "stream": False, "think": False,
                                             "keep_alive": 0, "options": {"num_predict": 1}}, timeout=15)
            except LLMError:
                pass

    def list_models(self) -> list[str]:
        r = json.load(urllib.request.urlopen(self.host + "/api/tags", timeout=3))
        return [m["name"] for m in r.get("models", [])]

    def warm(self) -> None:
        """Load the chat and embedding models now, so the first real question is not a 20 s cold start."""
        try:
            self.chat([{"role": "user", "content": "ok"}], max_tokens=1)
            self.embed(["warm up"])
        except LLMError:
            pass

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        r = self._post("/api/embed", {"model": self.embed_model, "input": texts, "keep_alive": "30m"}, timeout=30)
        return [np.array(v, dtype=np.float32) for v in r["embeddings"]]


class FakeLLM:
    """chat: scripted replies (list, callable(messages) -> str); embed: hashed bag-of-words (deterministic)."""
    def __init__(self, replies: list[str] | Callable[[list[dict], str | None], str] | None = None,
                 up: bool = True) -> None:
        self.replies, self.up, self.calls = replies or [], up, []
        self.chat_model, self.embed_model = "fake", "fake"
        self.pinned: set[str] = set()
        self.unloaded: list[str] = []
        self.installed = ["qwen3.5:4b-mlx", "qwen3.5:9b-mlx", "gemma4:12b-mlx", "nomic-embed-text:latest"]

    def unload(self, *models: str) -> None:
        self.unloaded += list(models)

    def list_models(self) -> list[str]:
        if not self.up:
            raise LLMError("fake llm is down")
        return list(self.installed)

    def available(self) -> bool:
        return self.up

    def warm(self) -> None:
        pass

    def chat(self, messages, model=None, max_tokens=160, temperature=0.2, json_mode=False, keep_alive=None, timeout=None) -> str:
        if not self.up:
            raise LLMError("fake llm is down")
        self.calls.append({"messages": messages, "model": model, "keep_alive": keep_alive})
        if callable(self.replies):
            return self.replies(messages, model)
        return self.replies.pop(0) if self.replies else "OK."

    def embed(self, texts):
        if not self.up:
            raise LLMError("fake llm is down")
        out = []
        for t in texts:
            v = np.zeros(256, dtype=np.float32)
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1.0
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return out
