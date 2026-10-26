"""Dashboard API: REST for control and data, WebSocket for the live event stream."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import time
import wave
from pathlib import Path

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from buds_assistant.audio.capture import FileSource, resample
from buds_assistant.speech.translate import detect_lang
from .api_v2 import make_router
from .audio_util import wav_to_audio

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
RANGES = {"speaker_threshold": (0.3, 0.95, "Voice match threshold"), "self_min_confidence": (0.5, 1.0, "Confidence that it is you"),
          "hint_min_gap": (0, 600, "Seconds between whispers"), "hints_per_hour": (0, 120, "Whispers per hour"),
          "hint_max_words": (3, 40, "Longest whisper"), "hint_ttl": (1, 30, "Whisper shelf life"),
          "audio_retention_days": (0, 3650, "Audio retention days"), "keep_unnamed_days": (0, 90, "Days to keep unnamed voices")}


def _host_ok(host_header: str) -> bool:
    h = (host_header or "").strip().lower()
    h = h[: h.rfind("]") + 1] if h.startswith("[") else h.split(":")[0]          # strip the port
    return h in LOCAL_HOSTS


def _origin_ok(origin: str | None) -> bool:
    if not origin:                                    # not a browser cross-site request (curl, the page's own GETs)
        return True
    from urllib.parse import urlparse
    return _host_ok(urlparse(origin).netloc)


WEB = Path(__file__).resolve().parent / "web"
WEB_V1 = Path(__file__).resolve().parent / "web_v1"       # the original analysis dashboard, kept as the Developer view
SETTINGS = {"ring_seconds": float, "speaker_threshold": float, "hint_min_gap": float, "hints_per_hour": int,
            "hint_max_words": int, "hint_ttl": float, "placement": str, "self_name": str, "store_unknown": bool,
            "self_min_confidence": float, "voice_en": str, "voice_te": str, "audio_retention_days": int, "telugu_stt": bool, "interpreter": bool,
            "chat_model": str, "translate_model": str, "keep_unnamed_days": int}


_wav_to_audio = wav_to_audio


def create_app(sk) -> FastAPI:
    app = FastAPI(title="Buds Sidekick")
    app.include_router(make_router(sk))

    @app.middleware("http")
    async def local_only(request, call_next):
        """Only this Mac's own pages may talk to Sidekick: refuse foreign Origins (cross-site forms/fetches) and foreign Host names (DNS rebinding)."""
        if not _host_ok(request.headers.get("host", "")) or not _origin_ok(request.headers.get("origin")):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Sidekick only answers pages opened from this Mac."}, status_code=403)
        return await call_next(request)

    def bad(msg: str, code: int = 400):
        raise HTTPException(code, msg)

    # ---------------------------------------------------------------- state
    @app.get("/api/state")
    async def state() -> dict:
        profile = {n: [{"name": b.name, "gesture": " then ".join(b.pattern), "mode": b.mode, "action": b.action}
                       for b in r.bindings] for n, r in sk.modes.recognizers.items()}
        return {**sk.status(), "config": sk.cfg.public(), "profiles": profile, "t0": sk.events.t0,
                "server_now": time.time()}

    @app.get("/api/events")
    async def events(n: int = Query(200, le=800), types: str | None = None) -> list:
        return sk.events.recent(n, set(types.split(",")) if types else None)

    @app.get("/api/live")
    async def live() -> list:
        return [{k: v for k, v in e.items() if k != "embedding"} for e in sk.pipeline.window[-200:] if not e.get("assistant")]

    # ---------------------------------------------------------------- control
    @app.post("/api/mode")
    async def mode(body: dict = Body(...)) -> dict:
        try:
            await sk.modes.set_mode(body.get("mode", ""))
        except ValueError:
            bad("unknown mode")
        return sk.modes.state()

    @app.post("/api/placement")
    async def placement(body: dict = Body(...)) -> dict:
        p = body.get("placement")
        if p not in ("auto", "ear", "remote"):
            bad("placement must be auto|ear|remote")
        sk.cfg.placement = p
        if p != "auto":
            await sk.modes.set_placement(p)
        return sk.modes.state()

    @app.post("/api/wear")
    async def wear(body: dict = Body(...)) -> dict:
        """Simulate wear state (L/R in_ear true/false) when no buds are connected."""
        await sk.modes.on_wear("L", 1 if body.get("left", True) else 2)
        await sk.modes.on_wear("R", 1 if body.get("right", True) else 2)
        return sk.modes.state()

    @app.post("/api/gesture")
    async def gesture(body: dict = Body(...)) -> dict:
        tok = body.get("token", "")
        if ":" not in tok:
            bad("token like L:double")
        await sk.gesture(tok)
        return {"ok": True}

    @app.post("/api/action")
    async def action(body: dict = Body(...)) -> dict:
        await sk.modes.dispatch(body.get("action", ""), **(body.get("args") or {}))
        return sk.modes.state()

    @app.post("/api/ask")
    async def ask(body: dict = Body(...)) -> dict:
        text = (body.get("text") or "").strip()
        if not text:
            bad("empty question")
        r = await sk.answer(text)
        return {"text": r.text, "lang": r.lang, "intent": r.intent, "sources": r.sources, "action": r.action}

    @app.post("/api/replay")
    async def replay(body: dict = Body(default={})) -> dict:
        await sk.modes.dispatch("replay", speed=float(body.get("speed", 1.0)))
        return {"ok": True, "buffered_seconds": round(sk.ring.seconds, 1)}

    @app.post("/api/mark")
    async def mark(body: dict = Body(default={})) -> dict:
        await sk.modes.dispatch("mark", note=body.get("note", ""))
        return {"ok": True}

    # ---------------------------------------------------------------- people & identity
    @app.get("/api/people")
    async def people() -> list:
        out = []
        for p in sk.store.people():
            if p.get("kind") == "assistant":
                continue                                          # the assistant's own voice is not someone you talked to
            segs = sk.store.segments(person_id=p["id"], limit=1)
            p["last_seen"] = segs[-1]["t1"] if segs else None
            p["segments"] = sk.store.q("SELECT COUNT(*) c FROM segments WHERE speaker_id=?", (p["id"],))[0]["c"]
            out.append(p)
        return out

    @app.post("/api/people/enroll")
    async def enroll(body: dict = Body(...)) -> dict:
        name, consent = (body.get("name") or "").strip(), (body.get("consent") or "").strip()
        if not name or not consent:
            bad("name and a consent note are required")
        loop = asyncio.get_running_loop()
        if body.get("wav_base64"):
            audio = _wav_to_audio(body["wav_base64"])
        else:
            audio = await loop.run_in_executor(None, sk.record_sample, float(body.get("seconds", 12)))
        if audio.size < 16000 * 2:
            bad("sample too short (need at least 2 seconds of speech)")
        pid = await loop.run_in_executor(None, lambda: sk.speaker.enroll(name, [audio], consent))
        similar = sk.speaker.similar_voices(pid, sk.cfg.similar_voice_warning)
        sk.events.publish("enrolled", person_id=pid, name=name, seconds=round(audio.size / 16000, 1), similar=similar)
        return {"id": pid, "name": name, "seconds": round(audio.size / 16000, 1), "similar": similar}

    @app.post("/api/people/demo")
    async def demo_people() -> dict:
        if not sk.simulate:
            bad("Demo voices only load in simulator mode, so they never answer for real people.")
        from buds_assistant.audio.demo import enrol_demo_voices
        await asyncio.get_running_loop().run_in_executor(None, enrol_demo_voices, sk.speaker)
        return {"ok": True}

    @app.post("/api/people/{pid}/forget")
    async def forget(pid: int) -> dict:
        if not sk.store.person(pid):
            bad("no such person", 404)
        return sk.forget_person(pid)

    @app.post("/api/people/{pid}/policy")
    async def policy(pid: int, body: dict = Body(...)) -> dict:
        try:
            sk.store.set_policy(pid, body.get("policy", ""), int(body.get("retention_days", 0)))
        except ValueError as exc:
            bad(str(exc))
        return {"ok": True}

    @app.post("/api/people/{pid}/rename")
    async def rename(pid: int, body: dict = Body(...)) -> dict:
        sk.store.rename_person(pid, body.get("name", "").strip())
        return {"ok": True}

    @app.post("/api/clusters/{label}/name")
    async def name_cluster(label: str, body: dict = Body(...)) -> dict:
        try:
            pid = sk.pipeline.name_cluster(label, body.get("name", "").strip(), body.get("consent", ""))
        except (ValueError, KeyError) as exc:
            bad(str(exc))
        return {"person_id": pid}

    @app.post("/api/segments/{sid}/correct")
    async def correct(sid: int, body: dict = Body(...)) -> dict:
        sk.pipeline.correct(sid, int(body["person_id"]))
        return {"ok": True}

    # ---------------------------------------------------------------- memory
    @app.get("/api/conversations")
    async def conversations() -> list:
        return sk.store.conversations()

    @app.get("/api/conversations/{cid}")
    async def conversation(cid: int) -> dict:
        return {"segments": sk.store.segments(conv_id=cid), "bookmarks": sk.store.bookmarks(cid)}

    @app.post("/api/conversations/{cid}/extract")
    async def extract(cid: int) -> dict:
        ids = await asyncio.get_running_loop().run_in_executor(None, sk.memory.extract_facts, cid)
        return {"facts": len(ids)}

    @app.get("/api/memory/search")
    async def search(q: str, person_id: int | None = None) -> list:
        hits = await asyncio.get_running_loop().run_in_executor(None, lambda: sk.memory.retrieve(q, person_id, 10))
        return [{"id": h.segment["id"], "speaker": h.segment["speaker"], "text": h.segment["text"], "t": h.segment["t1"],
                 "score": round(h.score, 2), "color": h.segment["color"]} for h in hits]

    @app.get("/api/people/{pid}/dossier")
    async def dossier(pid: int) -> dict:
        return sk.memory.dossier(pid) or bad("no such person", 404)

    @app.get("/api/commitments")
    async def commitments(status: str = "open") -> list:
        return sk.memory.commitments(None, status)

    @app.post("/api/facts/{fid}/status")
    async def fact_status(fid: int, body: dict = Body(...)) -> dict:
        sk.store.set_fact_status(fid, body.get("status", "done"))
        return {"ok": True}

    # ---------------------------------------------------------------- translation
    @app.post("/api/translate")
    async def translate(body: dict = Body(...)) -> dict:
        text = body.get("text", "")
        src = body.get("src", "auto")
        dst = body.get("dst") or None
        r = await asyncio.get_running_loop().run_in_executor(None, lambda: sk.translator.translate(text, src, dst))
        if r.ok and body.get("speak"):
            asyncio.create_task(sk.output.say(r.text, r.dst, "answer"))
        return {"ok": r.ok, "text": r.text, "src": r.src, "dst": r.dst, "error": r.error}

    # ---------------------------------------------------------------- hints, audit, settings
    @app.get("/api/hints")
    async def hints() -> list:
        return sk.store.hints()

    @app.post("/api/hints/{hid}/feedback")
    async def hint_feedback(hid: int, body: dict = Body(...)) -> dict:
        row = next((h for h in sk.store.hints(200) if h["id"] == hid), None)
        sk.policy.feedback(hid, bool(body.get("useful")), row["trigger"] if row else None)
        return {"ok": True, "rate_factor": sk.policy.rate_factor}

    @app.get("/api/audit")
    async def audit() -> list:
        return sk.store.audit_log()

    @app.get("/api/settings")
    async def get_settings() -> dict:
        return {k: getattr(sk.cfg, k) for k in SETTINGS}

    @app.post("/api/settings")
    async def set_settings(body: dict = Body(...)) -> dict:
        parsed = {}
        for k, v in body.items():
            if k not in SETTINGS:
                bad(f"unknown setting {k}")
            try:
                val = SETTINGS[k](v) if SETTINGS[k] is not bool else bool(v)
            except (TypeError, ValueError):
                bad(f"bad value for {k}")
            if k in RANGES and not (RANGES[k][0] <= val <= RANGES[k][1]):
                bad(f"{RANGES[k][2]} must be between {RANGES[k][0]} and {RANGES[k][1]}.")
            parsed[k] = val
        for k, val in parsed.items():                         # nothing is applied unless every value is valid
            setattr(sk.cfg, k, val)
        sk.cfg.ring_seconds = min(max(sk.cfg.ring_seconds, 5.0), 60.0)
        sk.ring.resize(sk.cfg.ring_seconds)
        sk.speaker.threshold = sk.cfg.speaker_threshold
        if "telugu_stt" in body and bool(body["telugu_stt"]) != hasattr(sk.transcriber, "english"):
            await asyncio.get_running_loop().run_in_executor(None, sk.set_telugu, bool(body["telugu_stt"]))
        sk.translator.model = sk.cfg.translate_model
        if "keep_unnamed_days" in parsed:
            sk.store.expire_unnamed(sk.cfg.keep_unnamed_days) if sk.cfg.keep_unnamed_days else sk.store.delete_unnamed()
        sk.store.audit("settings", body)
        return {k: getattr(sk.cfg, k) for k in SETTINGS}

    # ---------------------------------------------------------------- simulation (no buds, no humans)
    @app.post("/api/simulate/conversation")
    async def simulate(body: dict = Body(default={})) -> dict:
        from buds_assistant.audio.demo import demo_audio
        lang = body.get("language", "en")
        audio, script = await asyncio.get_running_loop().run_in_executor(None, lambda: demo_audio(language=lang))
        if not sk.modes.capturing:
            await sk.modes.set_mode("listen")
        sk.pipeline.set_source(FileSource(audio=audio, realtime=bool(body.get("realtime", True)), speed=float(body.get("speed", 1.0))))
        return {"seconds": round(audio.size / 16000, 1), "utterances": len(script)}

    # ---------------------------------------------------------------- websocket + static
    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        if not _host_ok(sock.headers.get("host", "")) or not _origin_ok(sock.headers.get("origin")):
            await sock.close(code=1008)                       # a web page from elsewhere must not read live transcripts
            return
        await sock.accept()
        q = sk.events.queue()
        try:
            await sock.send_text(json.dumps({"kind": "hello", "events": sk.events.recent(150)}, default=str))
            await sock.send_text(json.dumps({"type": "ui_state", "data": sk.ui.snapshot()}, default=str))
            while True:
                ev = await q.get()
                await sock.send_text(json.dumps(ev, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sk.events.drop(q)

    app.mount("/dev", StaticFiles(directory=WEB_V1, html=True), name="dev")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    app.mount("/", StaticFiles(directory=WEB), name="web")
    return app
