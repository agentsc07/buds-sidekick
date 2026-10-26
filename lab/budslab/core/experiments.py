"""Experiment catalog, matching/classification, and the guided runner."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

from ..protocol.commands import CommandError
from .events import RELEVANT_TYPES, Event
from .hub import Hub

log = logging.getLogger("budslab.runner")

VERIFIED, PARTIAL, UNKNOWN_SIGNAL, NOT_OBSERVED, SKIPPED = (
    "VERIFIED", "PARTIAL", "UNKNOWN_SIGNAL", "NOT_OBSERVED", "SKIPPED")


# --------------------------------------------------------------------- catalog
@dataclass
class Experiment:
    id: str
    title: str
    instruction: str
    category: str
    risk: str = "safe"
    timeout_seconds: float = 15
    expected_signals: list = field(default_factory=list)
    forbidden_signals: list = field(default_factory=list)
    command: dict | None = None
    undo: bool = False
    freeform: bool = False

    def public(self) -> dict:
        return dict(self.__dict__)


def load_catalog(path: Path) -> list[Experiment]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    d = doc.get("defaults", {})
    out, seen = [], set()
    for raw in doc.get("experiments", []):
        e = {**d, **raw}
        if e["id"] in seen:
            raise ValueError(f"duplicate experiment id {e['id']}")
        seen.add(e["id"])
        out.append(Experiment(
            id=e["id"], title=e["title"], instruction=e["instruction"], category=e["category"],
            risk=e.get("risk", "safe"), timeout_seconds=float(e.get("timeout_seconds", 15)),
            expected_signals=e.get("expected_signals") or [], forbidden_signals=e.get("forbidden_signals") or [],
            command=e.get("command"), undo=bool(e.get("undo", False)), freeform=bool(e.get("freeform", False))))
    return out


# -------------------------------------------------------------------- matching
def _val_match(actual: Any, want: Any) -> bool:
    return actual in want if isinstance(want, list) else actual == want


def match_event(ev: dict, m: dict) -> bool:
    for k in ("layer", "type", "source"):
        if k in m and not _val_match(ev.get(k), m[k]):
            return False
    if "side" in m and not _val_match(ev.get("side"), m["side"]):
        return False
    data = ev.get("data") or {}
    if "msg_id" in m and not _val_match(data.get("msg_id"), m["msg_id"]):
        return False
    for k, v in (m.get("data") or {}).items():
        if not _val_match(data.get(k), v):
            return False
    return True


def _item_matchers(item: dict) -> list[dict]:
    return item["any_of"] if "any_of" in item else [item]


def _item_hit(item: dict, events: list[dict]) -> list[dict]:
    hits = [e for e in events if any(match_event(e, m) for m in _item_matchers(item))]
    need = item.get("min_count", 1)
    return hits if len(hits) >= need else []


def evaluate(exp: Experiment, events: list[dict], is_background: Callable[[int], bool] = lambda _i: False
             ) -> tuple[str, list[dict], list[dict]]:
    """Classify events seen while an experiment was armed -> (status, matched_events, signals)."""
    considered = [e for e in events if not (e.get("data") or {}).get("initial")
                  and not (e["type"] == "command_result" and (e["data"] or {}).get("undo"))]
    matched: list[dict] = []
    all_hit = True
    for item in exp.expected_signals:
        hits = _item_hit(item, considered)
        if hits:
            matched.append(hits[0])
        else:
            all_hit = False
    unknown_frames = [e for e in considered if e["type"] == "frame" and (e["data"] or {}).get("dir") == "rx"
                      and not (e["data"] or {}).get("known") and not is_background(e["data"].get("msg_id", -1))]
    relevant = [e for e in considered if e["type"] in RELEVANT_TYPES
                and not (e["type"] == "conn" and (e["data"] or {}).get("event") in ("connecting", "error"))]
    forbidden = [e for e in considered if any(match_event(e, m) for m in exp.forbidden_signals)]

    if exp.expected_signals and all_hit and not forbidden:
        status = VERIFIED
    elif matched or forbidden or relevant:
        status = PARTIAL                      # some signal, but not (all of) the expected one
    elif unknown_frames:
        status = UNKNOWN_SIGNAL               # traffic we cannot decode; saved for analysis
    else:
        status = NOT_OBSERVED

    def compact(e: dict) -> dict:
        d = e.get("data") or {}
        return {"seq": e["seq"], "t": e["t"], "layer": e["layer"], "type": e["type"], "side": e.get("side"),
                "msg_id": d.get("msg_id"), "detail": d.get("gesture") or d.get("event") or d.get("key") or d.get("mode")
                or d.get("state") or d.get("name") or d.get("name_of")}

    sig = [compact(e) for e in (matched + [e for e in relevant if e not in matched] + unknown_frames)][:40]
    return status, [compact(e) for e in matched], sig


# ---------------------------------------------------------------------- runner
class Runner:
    PAUSE_DEFAULT = 3.0

    def __init__(self, hub: Hub, catalog: list[Experiment], commands: Any,
                 is_background: Callable[[int], bool], sim_notify: Callable[[Experiment], None] | None = None) -> None:
        self.hub, self.commands = hub, commands
        self.catalog = {e.id: e for e in catalog}
        self.order = [e.id for e in catalog]
        self.is_background = is_background
        self.sim_notify = sim_notify
        self.queue: list[str] = []
        self.state = "idle"            # idle | awaiting_confirm | armed | pause
        self.current: Experiment | None = None
        self.armed_ts = 0.0
        self.deadline = 0.0
        self.pause_until = 0.0
        self.events: list[dict] = []
        self.last_result: dict | None = None
        self.results: dict[str, dict] = {}      # latest per experiment (this session)
        self._task: asyncio.Task | None = None
        self._undo: tuple[str, dict] | None = None
        self._command_sent = False
        self._cmd_task: asyncio.Task | None = None
        self.freeform_text: str | None = None
        self._attempt_ids: dict[str, int] = {}
        hub.active_experiment = lambda: self.current.id if self.current and self.state == "armed" else None
        hub.listeners.append(self._on_event)

    # -- lifecycle --------------------------------------------------------------
    def start(self) -> None:
        self._task = asyncio.create_task(self._tick())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self.state == "armed" and self.current:
            await self._finish(force_status=SKIPPED)

    def public_state(self) -> dict:
        cur = self.current
        return {
            "kind": "runner", "state": self.state, "server_now": time.time(),
            "current": cur.public() if cur else None, "deadline": self.deadline if self.state == "armed" else None,
            "pause_until": self.pause_until if self.state == "pause" else None,
            "queue": list(self.queue), "last_result": self.last_result,
            "results": self.results, "warning": self._warning(cur) if self.state == "awaiting_confirm" else None,
            "commands_enabled": self.commands.enabled, "freeform_text": self.freeform_text,
        }

    def _warning(self, exp: Experiment | None) -> str | None:
        if not exp:
            return None
        if exp.risk == "audible":
            return "This will play a LOUD sound. Remove the buds from your ears, then confirm."
        if exp.command:
            return "This sends a settings command to the buds (undone afterwards where possible)."
        return None

    def _push(self) -> None:
        self.hub.broadcast(self.public_state())

    # -- control API --------------------------------------------------------------
    async def start_run(self, ids: list[str] | None = None, category: str | None = None) -> None:
        if ids:
            q = [i for i in ids if i in self.catalog]
        else:
            q = [i for i in self.order if category in (None, "all", self.catalog[i].category)]
        if not q:
            raise ValueError("no experiments selected")
        if self.state == "armed" and self.current:
            await self._finish(force_status=SKIPPED)
        self.queue = q
        await self._next()

    async def _next(self) -> None:
        if not self.queue:
            self.current, self.state = None, "idle"
            self.hub.emit(Event("S", "runner", "system", data={"event": "run_complete"}))
            self._push()
            return
        await self._arm(self.catalog[self.queue.pop(0)])

    async def _arm(self, exp: Experiment) -> None:
        self.current, self.events, self._undo, self._command_sent = exp, [], None, False
        self._cmd_task = None
        self.freeform_text = None
        if exp.command or exp.risk == "audible" or exp.freeform:
            self.state = "awaiting_confirm"
            self._push()
            return
        await self._begin(exp)

    async def confirm(self, text: str | None = None) -> None:
        if self.state != "awaiting_confirm" or not self.current:
            raise ValueError("nothing to confirm")
        exp = self.current
        if exp.freeform:
            self.freeform_text = (text or "").strip() or "(no description)"
            self.hub.store.add_note(self.freeform_text, exp.id, time.time() - self.hub.t0)
        if exp.command and not self.commands.enabled:
            raise CommandError("enable command sending in the Commands view first")
        await self._begin(exp)

    async def _begin(self, exp: Experiment) -> None:
        self.armed_ts = time.time()
        self.deadline = self.armed_ts + exp.timeout_seconds
        self.state = "armed"
        self.hub.emit(Event("S", "runner", "system", data={"event": "experiment_armed", "id": exp.id,
                                                            "title": exp.title}, ts=self.armed_ts))
        self._push()
        if self.sim_notify:
            self.sim_notify(exp)
        if exp.command:
            self._undo = self.commands.undo_for(exp.command["name"], exp.command.get("args", {}))
            self._cmd_task = asyncio.create_task(self._send_command(exp))

    async def _send_command(self, exp: Experiment) -> None:
        self._command_sent = True      # set before awaiting: the ack/state event may finish the run first
        try:
            await self.commands.send(exp.command["name"], exp.command.get("args", {}), confirm=True,
                                     experiment_id=exp.id)
        except CommandError as exc:
            self._command_sent = False
            self.hub.emit(Event("S", "runner", "system", data={"event": "command_error", "error": str(exc)}))
            self.hub.broadcast({"kind": "toast", "level": "error", "text": str(exc)})

    async def skip(self) -> None:
        if self.state == "pause":
            await self._next()
        elif self.current and self.state in ("armed", "awaiting_confirm"):
            if self.state == "awaiting_confirm":
                self._record(self.current, SKIPPED, [], [], manual=False)
                self.state = "pause"
                self.pause_until = time.time() + 0.3
                self._push()
            else:
                await self._finish(force_status=SKIPPED)

    async def retry(self) -> None:
        exp = self.current or (self.catalog.get(self.last_result["id"]) if self.last_result else None)
        if not exp:
            raise ValueError("nothing to retry")
        if self.state == "armed":
            await self._finish(force_status=SKIPPED, advance=False)
        await self._arm(exp)

    async def rerun(self, exp_id: str) -> None:
        if exp_id not in self.catalog:
            raise ValueError("unknown experiment")
        await self.start_run(ids=[exp_id])

    async def mark_verified(self) -> None:
        if self.state == "armed" and self.current:
            await self._finish(force_status=VERIFIED, manual=True)
        elif self.last_result and self.last_result["id"] in self._attempt_ids:
            exp_id = self.last_result["id"]
            self.hub.store.update_attempt(self._attempt_ids[exp_id], VERIFIED, True)
            self.last_result["status"] = VERIFIED
            self.last_result["manual"] = True
            self.results[exp_id] = self.last_result
            self._push()
        else:
            raise ValueError("no experiment to mark")

    def extend_pause(self, seconds: float = 5.0) -> None:
        if self.state == "pause":
            self.pause_until += seconds
            self._push()

    def extend_time(self, seconds: float = 10.0) -> None:
        if self.state == "armed":
            self.deadline += seconds
            self._push()

    async def abort(self) -> None:
        self.queue = []
        if self.state == "armed":
            await self._finish(force_status=SKIPPED, advance=False)
        self.current, self.state = None, "idle"
        self._push()

    # -- event flow --------------------------------------------------------------
    def _on_event(self, ev: Event) -> None:
        if self.state != "armed":
            return
        d = ev.to_dict()
        self.events.append(d)
        exp = self.current
        flash = d["type"] in RELEVANT_TYPES or (
            d["type"] == "frame" and d["data"].get("dir") == "rx" and not d["data"].get("known")
            and not self.is_background(d["data"].get("msg_id", -1)))
        if flash:
            self.hub.broadcast({"kind": "signal", "experiment": exp.id if exp else None, "event": d})
        if exp and exp.expected_signals and not exp.forbidden_signals and not exp.freeform:
            status, _matched, _ = evaluate(exp, self.events, self.is_background)
            if status == VERIFIED:
                asyncio.get_running_loop().create_task(self._finish())

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            now = time.time()
            try:
                if self.state == "armed" and now >= self.deadline:
                    await self._finish()
                elif self.state == "pause" and now >= self.pause_until:
                    await self._next()
            except Exception:
                log.exception("runner tick failed")

    async def _finish(self, force_status: str | None = None, manual: bool = False, advance: bool = True) -> None:
        if self.state != "armed" or not self.current:
            return
        self.state = "pause"          # guards re-entry
        exp = self.current
        if self._cmd_task and not self._cmd_task.done():
            try:                       # let the in-flight command settle so its result and any undo stay ordered
                await asyncio.wait_for(asyncio.shield(self._cmd_task), 5)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass
        status, matched, signals = evaluate(exp, self.events, self.is_background)
        if force_status:
            status = force_status
        self._record(exp, status, matched, signals, manual)
        if self._command_sent and exp.undo and self._undo and self.commands.enabled:
            try:
                await self.commands.send(self._undo[0], self._undo[1], confirm=True, undo=True)
            except CommandError as exc:
                self.hub.broadcast({"kind": "toast", "level": "error", "text": f"undo failed: {exc}"})
        elif exp.command and self._command_sent and exp.command["name"] == "find_my_start":
            try:
                await self.commands.send("find_my_stop", {}, confirm=True, undo=True)
            except CommandError:
                pass
        self.pause_until = time.time() + (self.PAUSE_DEFAULT if advance and self.queue else 0.3)
        if not advance:
            self.state = "idle"
        self._push()

    def _record(self, exp: Experiment, status: str, matched: list, signals: list, manual: bool) -> None:
        aid = self.hub.store.add_attempt(exp.id, status, self.armed_ts or time.time(), time.time(),
                                         matched, signals, manual)
        self._attempt_ids[exp.id] = aid
        res = {"id": exp.id, "status": status, "manual": manual, "matched": matched, "signals": signals,
               "ended": time.time(), "freeform_text": self.freeform_text}
        self.last_result = self.results[exp.id] = res
        self.hub.emit(Event("S", "runner", "system", data={"event": "experiment_result", "id": exp.id,
                                                            "status": status, "manual": manual}))
        self.hub.broadcast({"kind": "result", "result": res})
