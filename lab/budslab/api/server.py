"""FastAPI app: REST for catalog/results/commands/export, WebSocket for the live feed."""
from __future__ import annotations

import asyncio
import functools
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ..core import report
from ..core.experiments import load_catalog
from ..core.lab import Config, Lab
from ..protocol.commands import CommandError

WEB = Path(__file__).resolve().parent.parent / "web"
ROOT = Path(__file__).resolve().parents[2]


def create_app(cfg: Config) -> FastAPI:
    lab: Lab | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal lab
        lab = Lab(cfg)
        app.state.lab = lab
        await lab.start()
        yield
        await lab.stop()

    app = FastAPI(title="Buds FE Capability Lab", lifespan=lifespan)

    def L() -> Lab:
        assert lab is not None
        return lab

    def wrap(fn):
        @functools.wraps(fn)
        async def inner(*a, **k):
            try:
                return await fn(*a, **k)
            except (CommandError, ValueError) as exc:
                raise HTTPException(400, str(exc))
        return inner

    # ---- status / events -----------------------------------------------------------
    @app.get("/api/status")
    async def status() -> dict:
        return L().status()

    @app.get("/api/events")
    async def events(type: str | None = None, layer: str | None = None, since_seq: int = 0,
                     limit: int = Query(2000, le=20000), msg_id: int | None = None, direction: str | None = None,
                     session: str = "current") -> list:
        return L().store.events(session=session, types=type.split(",") if type else None, layer=layer,
                                since_seq=since_seq, limit=limit, msg_id=msg_id, direction=direction)

    @app.get("/api/unknown")
    async def unknown(all_sessions: bool = False) -> list:
        return report.unknown_table(L().store, True, None if all_sessions else L().session_id)

    @app.get("/api/msgfreq")
    async def msgfreq() -> list:
        return report.msg_frequency(L().store, L().session_id)

    @app.get("/api/sdp")
    async def sdp() -> dict:
        p = L().store.session_dir / "sdp.json"
        return json.loads(p.read_text()) if p.exists() else {"records": [], "note": "no SDP dump yet"}

    @app.post("/api/discovery/ble")
    async def ble(seconds: float = 10.0) -> dict:
        from ..transport.ble import ble_scan
        res = await ble_scan(min(max(seconds, 3), 30))
        (L().store.session_dir / "ble_scan.json").write_text(json.dumps(res, indent=2))
        L().discovery["ble"] = res
        return res

    # ---- catalog / runner ------------------------------------------------------------
    @app.get("/api/catalog")
    async def catalog() -> list:
        return [e.public() for e in L().catalog]

    @app.post("/api/catalog/reload")
    async def reload_catalog() -> dict:
        new = load_catalog(cfg.catalog)
        L().catalog = new
        L().runner.catalog = {e.id: e for e in new}
        L().runner.order = [e.id for e in new]
        return {"count": len(new)}

    @app.get("/api/runner")
    async def runner_state() -> dict:
        return L().runner.public_state()

    @app.get("/api/results")
    async def results(all_sessions: bool = False) -> list:
        sql = "SELECT * FROM attempts" + ("" if all_sessions else " WHERE session_id=?") + " ORDER BY id"
        rows = L().store.q(sql, () if all_sessions else (L().session_id,))
        for r in rows:
            r["matched"], r["signals"] = json.loads(r["matched"] or "[]"), json.loads(r["signals"] or "[]")
        return rows

    @app.post("/api/run/start")
    @wrap
    async def run_start(body: dict = Body(default={})) -> dict:
        await L().runner.start_run(ids=body.get("ids"), category=body.get("category"))
        return {"ok": True}

    @app.post("/api/run/{action}")
    @wrap
    async def run_action(action: str, body: dict = Body(default={})) -> dict:
        r = L().runner
        if action == "skip":
            await r.skip()
        elif action == "retry":
            await r.retry()
        elif action == "verify":
            await r.mark_verified()
        elif action == "confirm":
            await r.confirm(body.get("text"))
        elif action == "extend":
            r.extend_pause(5) if r.state == "pause" else r.extend_time(10)
        elif action == "abort":
            await r.abort()
        elif action == "rerun":
            await r.rerun(body["id"])
        else:
            raise HTTPException(404, "unknown action")
        return {"ok": True}

    @app.post("/api/notes")
    async def add_note(body: dict = Body(...)) -> dict:
        text = (body.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "empty note")
        exp = body.get("experiment_id") or (L().runner.current.id if L().runner.current else None)
        t = time.time() - L().hub.t0
        nid = L().store.add_note(text, exp, t)
        from ..core.events import Event
        L().hub.emit(Event("S", "user", "note", data={"text": text, "note_id": nid, "experiment": exp}))
        return {"id": nid}

    @app.get("/api/notes")
    async def notes(all_sessions: bool = False) -> list:
        sql = "SELECT * FROM notes" + ("" if all_sessions else " WHERE session_id=?") + " ORDER BY id"
        return L().store.q(sql, () if all_sessions else (L().session_id,))

    # ---- commands --------------------------------------------------------------------
    @app.get("/api/commands")
    async def commands() -> dict:
        c = L().commands
        return {"enabled": c.enabled, "commands": c.catalog(), "find_my_active": c.find_my_active}

    @app.post("/api/commands/enable")
    async def cmd_enable(body: dict = Body(...)) -> dict:
        L().commands.set_enabled(bool(body.get("enabled")))
        return {"enabled": L().commands.enabled}

    @app.post("/api/commands/send")
    @wrap
    async def cmd_send(body: dict = Body(...)) -> dict:
        return await L().commands.send(body.get("name", ""), body.get("args") or {}, confirm=bool(body.get("confirm")))

    @app.get("/api/commands/history")
    async def cmd_history() -> list:
        return L().store.q("SELECT * FROM commands WHERE session_id=? ORDER BY id", (L().session_id,))

    # ---- report ----------------------------------------------------------------------
    def _include_sim() -> bool:
        return L().mode != "hardware"

    @app.get("/api/report")
    async def get_report(simulated: bool | None = None) -> dict:
        inc = _include_sim() if simulated is None else simulated
        m = report.capability_matrix(L().store, L().catalog, inc)
        m["markdown"] = report.to_markdown(m)
        return m

    @app.post("/api/export")
    async def export(simulated: bool | None = None) -> dict:
        inc = _include_sim() if simulated is None else simulated
        paths = report.write_exports(L().store, L().catalog, cfg.data_dir / "exports", ROOT / "docs" / "protocol-findings.md", inc)
        sess = L().store.session_dir
        for name in ("capabilities.json", "capabilities.md"):
            (sess / name).write_text((cfg.data_dir / "exports" / name).read_text())
        return paths

    @app.get("/api/export/{name}")
    async def download(name: str):
        if name not in ("capabilities.json", "capabilities.md"):
            raise HTTPException(404)
        inc = _include_sim()
        m = report.capability_matrix(L().store, L().catalog, inc)
        if name.endswith(".json"):
            return JSONResponse(m, headers={"Content-Disposition": f"attachment; filename={name}"})
        return PlainTextResponse(report.to_markdown(m), headers={"Content-Disposition": f"attachment; filename={name}"})

    # ---- microphone ------------------------------------------------------------------
    @app.get("/api/mic/devices")
    async def mic_devices() -> dict:
        from .. import audio
        try:
            return {"devices": audio.list_inputs(), "error": None}
        except RuntimeError as exc:
            return {"devices": [], "error": str(exc)}

    @app.post("/api/mic/record")
    @wrap
    async def mic_record(body: dict = Body(...)) -> dict:
        from .. import audio
        from ..core.events import Event
        secs = min(max(float(body.get("seconds", 5)), 1), 60)
        loop = asyncio.get_running_loop()
        try:
            res = await loop.run_in_executor(None, lambda: audio.record(
                secs, L().store.session_dir / "audio", body.get("label", "rec"), body.get("device")))
        except (LookupError, RuntimeError) as exc:
            raise ValueError(str(exc))
        L().hub.emit(Event("A", "mic", "audio", data={"event": "recording", **res}))
        return res

    @app.get("/api/mic/file/{name}")
    async def mic_file(name: str):
        p = (L().store.session_dir / "audio" / Path(name).name)
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(p, media_type="audio/wav")

    # ---- websocket -------------------------------------------------------------------
    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()
        lab_ = L()
        q = lab_.hub.subscribe()
        try:
            await sock.send_json({"kind": "hello", "status": lab_.status(), "runner": lab_.runner.public_state()})
            while True:
                msg = await q.get()
                if msg.get("kind") == "status":
                    msg = {"kind": "status", "status": lab_.status()}
                await sock.send_text(json.dumps(msg, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            lab_.hub.unsubscribe(q)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    app.mount("/", StaticFiles(directory=WEB), name="web")
    return app
