"""Model residency (spec 9.2): the everyday models stay loaded, the big translation model loads only for Interpreter.

On a 16 GB Mac, letting Ollama swap models turns a 1 s answer into a 10-25 s stall, so we say which model each mode
needs, warm it on entry, unload it on exit, and expose readiness to the UI."""
from __future__ import annotations

from buds_assistant.intelligence.llm import LLMError

NEEDS_TRANSLATE = ("interpreter",)


class ModelManager:
    def __init__(self, llm, cfg, events) -> None:
        self.llm, self.cfg, self.events = llm, cfg, events
        self._state = {"chat": "unloaded", "embed": "unloaded", "translate": "unloaded", "telugu": "unloaded"}
        self.hooks: dict = {}                              # {"enter": fn, "leave": fn}: Telugu speech recognition, owned by Sidekick

    @property
    def one_model(self) -> bool:
        """The chat and translation models are the same: nothing to swap, Translate is ready as soon as the model is."""
        return self.cfg.translate_model == self.cfg.chat_model

    def state(self) -> dict[str, str]:
        return dict(self._state)

    def _set(self, **kw: str) -> None:
        self._state.update(kw)
        self.events.publish("model_state", **self._state)

    def start(self) -> None:
        """Blocking (run in a thread): load the chat and embedding models now, not on the first question."""
        self._set(chat="loading", embed="loading")
        try:
            self.llm.chat([{"role": "user", "content": "ok"}], max_tokens=1)
            self._set(chat="ready")
            self.llm.embed(["warm up"])
            self._set(embed="ready")
            if self.one_model:
                self._set(translate="ready")
        except LLMError as exc:
            self._set(chat="unloaded", embed="unloaded")
            self.events.publish("error", where="models", error=repr(exc))

    def ensure(self) -> None:
        """Blocking (run in a thread): if Ollama was down or slow at start, load the everyday models once it is up.
        Not while Interpreter has them unloaded on purpose."""
        if self._state["chat"] in ("ready", "loading") or (not self.one_model and self._state["translate"] != "unloaded"):
            return
        if self.llm.available():
            self.start()

    def enter(self, mode: str) -> None:
        if mode not in NEEDS_TRANSLATE:
            return
        if self.one_model:
            self._speech_enter()
            return
        model = self.cfg.translate_model
        self.llm.unload(self.cfg.chat_model, self.cfg.embed_model)      # translation + Telugu speech + the chat models do not fit in 16 GB together
        self._set(chat="unloaded", embed="unloaded", translate="loading")
        try:
            self.llm.pinned.add(model)
            self.llm.chat([{"role": "user", "content": "ok"}], model=model, max_tokens=1, keep_alive="30m")
            self._set(translate="ready")
            if self.hooks.get("enter"):
                self._set(telugu="loading")
                try:
                    self.hooks["enter"]()
                    self._set(telugu="ready")
                except Exception as exc:  # noqa: BLE001
                    self._set(telugu="unloaded")
                    self.events.publish("error", where="models", error=f"Telugu speech recognition failed to load: {exc!r}")
        except LLMError as exc:
            self.llm.pinned.discard(model)
            self._set(translate="unloaded")
            self.events.publish("error", where="models", error=f"translation model unavailable: {exc!r}")

    def mark_speech_ready(self) -> None:
        """The Telugu recogniser and translator were warmed at start: Translate is ready before it is clicked."""
        if self.one_model:
            self._set(translate="ready", telugu="ready")

    def _speech_enter(self) -> None:
        if not self.hooks.get("enter"):
            self._set(telugu="ready")
            return
        if self._state["telugu"] != "ready":
            self._set(telugu="loading")
        try:
            self.hooks["enter"]()
            self._set(telugu="ready")
        except Exception as exc:  # noqa: BLE001
            self._set(telugu="unloaded")
            self.events.publish("error", where="models", error=f"Telugu speech recognition failed to load: {exc!r}")

    def leave(self, mode: str) -> None:
        if mode not in NEEDS_TRANSLATE:
            return
        if self.one_model:
            if self.hooks.get("leave"):
                try:
                    self.hooks["leave"]()
                except Exception:  # noqa: BLE001
                    pass
            self._set(translate="ready", telugu="ready")                # everything stays resident: the next click is instant
            return
        model = self.cfg.translate_model
        self.llm.pinned.discard(model)
        try:
            self.llm.chat([{"role": "user", "content": "ok"}], model=model, max_tokens=1, keep_alive="0")
        except LLMError:
            pass
        if self.hooks.get("leave"):
            try:
                self.hooks["leave"]()
            except Exception:  # noqa: BLE001
                pass
        self._set(translate="unloaded", telugu="unloaded")
        self.start()                                                      # the everyday models come back (this runs off the event loop)
