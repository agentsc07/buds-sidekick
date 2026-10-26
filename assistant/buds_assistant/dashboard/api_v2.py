"""Dashboard v2 API (versioned, plain language). The UI is a product, not a test bench: every message here is meant to be shown as is."""
from __future__ import annotations

import importlib.util
import time
from datetime import datetime
from pathlib import Path

import asyncio
import json
from datetime import datetime

import numpy as np

from fastapi import APIRouter, Body, HTTPException, Query, Response

from buds_assistant.intelligence.autopilot import REASONS, SENS
from buds_assistant.core.config import SPEAKER_MODEL_URL
from buds_assistant.intelligence.llm import LLMError
from .audio_util import wav_to_audio
from buds_assistant.speech.calibrate import evaluate
from buds_assistant.audio.mic_check import measure
from buds_assistant.speech.speaker import chunks
from buds_assistant.core.modes import ACTIONS, DEFAULT_MAP, SLOTS, read_gestures, write_gestures

CATEGORIES = ("capture", "question", "calendar", "meeting", "reminder", "commitment", "mention", "identity")


def make_router(sk) -> APIRouter:
    r = APIRouter(prefix="/api/v2")

    def bad(msg: str, code: int = 400):
        raise HTTPException(code, msg)

    # ---- state & control -------------------------------------------------------------------------------------
    @r.get("/state")
    async def state() -> dict:
        return sk.ui.snapshot()

    @r.post("/mode")
    async def mode(body: dict = Body(...)) -> dict:
        try:
            await sk.modes.set_mode(body.get("mode", ""))
        except ValueError:
            bad("That mode does not exist.")
        return sk.ui.snapshot()

    @r.post("/memory-level")
    async def memory_level(body: dict = Body(...)) -> dict:
        if body.get("level") == "recording":
            bad("Audio recording is not available yet.")      # the state exists, saving audio arrives with voice commands (Phase 4)
        try:
            await sk.modes.set_memory_level(body.get("level", ""))
        except ValueError as exc:
            bad(str(exc) if "needs" in str(exc) else "That memory level does not exist.")
        return sk.ui.snapshot()

    @r.post("/interpreter")
    async def interpreter(body: dict = Body(...)) -> dict:
        if "two_way" in body:
            sk.cfg.interpreter_two_way = bool(body.get("two_way"))
        src, dst = body.get("src", sk.cfg.interpreter_from), body.get("dst", sk.cfg.interpreter_to)
        if src not in ("te", "en") or dst not in ("te", "en"):
            raise HTTPException(400, "Only Telugu and English are supported.")
        if src == dst:                                   # the same language on both sides would translate nothing: flip the one that did not change
            if "src" in body:
                dst = "en" if src == "te" else "te"
            else:
                src = "en" if dst == "te" else "te"
        sk.cfg.interpreter_from, sk.cfg.interpreter_to = src, dst
        sk.store.audit("settings", {"interpreter_from": src, "interpreter_to": dst, "interpreter_two_way": sk.cfg.interpreter_two_way})
        sk.events.publish("mode", **sk.modes.state())
        return {"two_way": sk.cfg.interpreter_two_way, "from": src, "to": dst}

    # ---- autopilot ----------------------------------------------------------------------------------------------
    @r.get("/autopilot")
    async def autopilot() -> dict:
        on = sk.policy.categories()
        return {"sensitivity": sk.cfg.autopilot_sensitivity, "categories": {c: c in on for c in CATEGORIES},
                "enabled": sk.policy.enabled}

    @r.put("/autopilot")
    async def put_autopilot(body: dict = Body(...)) -> dict:
        if body.get("sensitivity") is not None:
            if body["sensitivity"] not in SENS:
                bad("Sensitivity must be quiet, balanced or proactive.")
            sk.cfg.autopilot_sensitivity = body["sensitivity"]
            sk.cfg.autopilot_categories = None
        if body.get("categories") is not None:
            sk.cfg.autopilot_categories = [c for c in CATEGORIES if body["categories"].get(c)]
        sk.store.audit("settings", {"autopilot_sensitivity": sk.cfg.autopilot_sensitivity,
                                    "autopilot_categories": sk.cfg.autopilot_categories})
        sk.events.publish("mode", **sk.modes.state())             # re-push the snapshot (carries the sensitivity)
        return await autopilot()

    @r.get("/autopilot/feed")
    async def feed(n: int = Query(50, le=500)) -> list:
        out = []
        for d in sk.store.decisions(n):
            p = sk.store.person(d["person_id"]) if d["person_id"] else None
            out.append({**d, "person": p["name"] if p else None, "reason_text": REASONS.get(d["reason"], d["reason"])})
        return out

    @r.post("/hints/{hid}/feedback")
    async def hint_feedback(hid: int, body: dict = Body(...)) -> dict:
        row = next((h for h in sk.store.hints(300) if h["id"] == hid), None)
        sk.policy.feedback(hid, bool(body.get("useful")), row["trigger"] if row else None)
        return {"ok": True}

    @r.post("/commitments/{fid}/undo")
    async def undo(fid: int) -> dict:
        sk.store.set_fact_status(fid, "cancelled")
        sk.personal.cancel_for_fact(fid)
        return {"ok": True}

    # ---- my day: calendar, to-dos, reminders ---------------------------------------------------------------------------
    def _when(text: str):
        from buds_assistant.intelligence.timeparse import parse_when
        return parse_when(text or "", datetime.now())

    @r.get("/me")
    async def my_day() -> dict:
        from buds_assistant.intelligence.personal import day_label, hm
        pe, now = sk.personal, datetime.now()
        events = pe.events_between(now.timestamp() - 3600, now.timestamp() + 14 * 86400)
        for e in events:
            e["when_label"] = f"{day_label(e['start'], now)} at {hm(e['start'])}"
        reminders = pe.reminders()
        for x in reminders:
            x["when_label"] = f"{day_label(x['due'], now)} at {hm(x['due'])}"
        return {"events": events, "todos": pe.todos(), "reminders": reminders, "sample": pe.has_sample()}

    @r.post("/me/todos")
    async def add_todo(body: dict = Body(...)) -> dict:
        text = (body.get("text") or "").strip()
        if not text:
            bad("What do you need to do?")
        w = _when(body.get("when") or "")
        return {"ok": True, "id": sk.personal.add_todo(text, w.label if w else None, w.start.timestamp() if w else None)}

    @r.post("/me/todos/{tid}/done")
    async def todo_done(tid: int) -> dict:
        sk.personal.complete_todo(tid)
        return {"ok": True}

    @r.post("/me/todos/{tid}/reopen")
    async def todo_reopen(tid: int) -> dict:
        sk.personal.reopen_todo(tid)
        return {"ok": True}

    @r.post("/me/reminders")
    async def add_reminder(body: dict = Body(...)) -> dict:
        text, w = (body.get("text") or "").strip(), _when(body.get("when") or "")
        if not text:
            bad("What should I remind you about?")
        if not w:
            bad("Tell me when, like 'tomorrow at 9' or 'in 30 minutes'.")
        due = w.start if w.time else w.window()[0].replace(hour=9)
        return {"ok": True, "id": sk.personal.add_reminder(text, due.timestamp())}

    @r.post("/me/reminders/{rid}/done")
    async def reminder_done(rid: int) -> dict:
        sk.personal.complete_reminder(rid)
        return {"ok": True}

    @r.post("/me/events")
    async def add_event(body: dict = Body(...)) -> dict:
        title, w = (body.get("title") or "").strip(), _when(body.get("when") or "")
        if not title:
            bad("What is the event called?")
        if not w:
            bad("Tell me when, like 'Friday at 2 pm'.")
        a, b = w.window()
        return {"ok": True, "id": sk.personal.add_event(title, a.timestamp(), b.timestamp(), body.get("people") or [], body.get("place") or "")}

    @r.delete("/me/events/{eid}")
    async def delete_event(eid: int) -> dict:
        sk.personal.delete_event(eid)
        return {"ok": True}

    @r.post("/me/sample")
    async def sample(body: dict = Body(...)) -> dict:
        if body.get("on"):
            sk.personal.seed_sample(datetime.now(), force=True)
        else:
            sk.personal.clear_sample()
        return {"ok": True, "sample": sk.personal.has_sample()}

    # ---- health -----------------------------------------------------------------------------------------------------
    @r.get("/health")
    async def health() -> dict:
        checks = []

        def add(id_, label, ok, detail, fix=""):
            checks.append({"id": id_, "label": label, "ok": bool(ok), "detail": detail, "fix": "" if ok else fix})
        up = sk.llm.available()
        add("ollama", "Thinking engine (Ollama)", up, "Running." if up else "Not running.",
            "Install Ollama from ollama.com, open it once, then check again.")
        missing = []
        if up:
            try:
                have = sk.llm.list_models()
                for name in dict.fromkeys((sk.cfg.chat_model, sk.cfg.embed_model, sk.cfg.translate_model)):
                    if name not in have and f"{name}:latest" not in have:
                        missing.append(name)
            except LLMError:
                missing = [sk.cfg.chat_model]
        add("models", "Language skills", up and not missing, "Downloaded." if up and not missing else
            ("Still to download: " + ", ".join(missing)) if missing else "Waiting for the thinking engine.",
            "Use Download below." if missing else "Start Ollama first.")
        linked = getattr(sk.link, "transport", None) is not None
        add("buds", "Galaxy Buds", linked or sk.simulate, "Connected." if linked else "Practice mode: no earbuds needed." if sk.simulate
            else "Not connected.", "Turn off Bluetooth on your phone, then connect the buds to this Mac in System Settings.")
        have_voice = Path(sk.cfg.speaker_model).exists()
        add("speaker_model", "Voice recognition", have_voice, "Downloaded." if have_voice else "Still to download (38 MB).", "Use Download below.")
        has_whisper = importlib.util.find_spec("faster_whisper") is not None
        add("whisper", "Speech to text", has_whisper, "Installed." if has_whisper else "Missing.",
            "Reinstall Buds Sidekick (pipx reinstall buds-sidekick).")
        for c in checks:
            c["downloadable"] = c["id"] in ("models", "speaker_model") and not c["ok"] and (c["id"] == "speaker_model" or up)
        return {"checks": checks}

    # ---- first-run downloads ----------------------------------------------------------------------------------------
    @r.post("/setup/download")
    async def download() -> dict:
        d = sk.downloads
        if sk.llm.available():
            have = sk.llm.list_models()
            for name in dict.fromkeys((sk.cfg.chat_model, sk.cfg.embed_model, sk.cfg.translate_model)):
                if name not in have and f"{name}:latest" not in have:
                    d.pull_model(name)
        if not Path(sk.cfg.speaker_model).exists():
            d.fetch_file("voice model", SPEAKER_MODEL_URL, Path(sk.cfg.speaker_model))
        return {"items": d.snapshot()}

    @r.get("/setup/download")
    async def download_progress() -> dict:
        return {"items": sk.downloads.snapshot()}

    # ---- gestures ---------------------------------------------------------------------------------------------------
    def slots() -> list[dict]:
        cur = read_gestures(sk.gestures_path)
        return [{"gesture": g, "action": cur.get(g, DEFAULT_MAP[g]), "label": ACTIONS.get(cur.get(g, DEFAULT_MAP[g]), "")} for g in SLOTS]

    @r.get("/gestures")
    async def gestures() -> dict:
        return {"slots": slots(), "actions": [{"id": k, "label": v} for k, v in ACTIONS.items()], "defaults": DEFAULT_MAP}

    @r.put("/gestures")
    async def put_gestures(body: dict = Body(...)) -> dict:
        items = body.get("slots") or []
        seen = set()
        for it in items:
            if it.get("gesture") not in SLOTS:
                bad(f"Unknown gesture {it.get('gesture')}.")
            if it.get("action") not in ACTIONS:
                bad(f"Unknown action {it.get('action')}.")
            if it["gesture"] in seen:
                bad(f"{it['gesture']} is assigned twice.")
            seen.add(it["gesture"])
        merged = {s["gesture"]: s["action"] for s in slots()}
        merged.update({it["gesture"]: it["action"] for it in items})
        path = Path(sk.gestures_path)
        if path.exists():
            path.with_suffix(path.suffix + ".bak").write_text(path.read_text())
        write_gestures(path, merged)
        sk.modes.reload_profiles(path)
        sk.store.audit("settings", {"gestures": merged})
        return await gestures()

    @r.post("/gestures/reset")
    async def reset_gestures() -> dict:
        write_gestures(Path(sk.gestures_path), DEFAULT_MAP)
        sk.modes.reload_profiles(Path(sk.gestures_path))
        sk.store.audit("settings", {"gestures": "reset"})
        return await gestures()

    @r.post("/gestures/try")
    async def try_gestures(body: dict = Body(...)) -> dict:
        """Try-it mode: gestures are shown on the dashboard but do nothing. Expires after 60 s so a closed tab can't leave the buds dead."""
        sk.try_until = time.time() + 60 if body.get("on") else 0.0
        return {"on": bool(body.get("on")), "seconds": 60 if body.get("on") else 0}

    # ---- unnamed voices -----------------------------------------------------------------------------------------
    def _stored_groups() -> list[dict]:
        """Voices kept from earlier conversations, merged when they are the same voice; ones that match someone I know since are dropped."""
        keep = sk.cfg.keep_unnamed_days
        if keep <= 0:
            return []
        sk.store.expire_unnamed(keep)
        groups: list[dict] = []
        for row in sk.store.unnamed_voices():                                     # newest first
            if row["conv_id"] == sk.pipeline.conv_id or row["centroid"].size == 0:
                continue
            if sk.speaker.dim and row["centroid"].size != sk.speaker.dim:
                continue                                                          # made by a previous voice model
            if sk.speaker.would_match(row["centroid"]) is not None:
                sk.store.delete_unnamed(ids=[row["id"]])
                continue
            c = row["centroid"] / (np.linalg.norm(row["centroid"]) or 1.0)
            for g in groups:
                if float(c @ g["unit"]) >= 0.6:
                    g["ids"].append(row["id"]); g["utterances"] += row["count"]; g["seconds"] = round(g["seconds"] + row["seconds"], 1)
                    g["first_seen"] = min(g["first_seen"], row["first_seen"]); g["cents"].append((row["centroid"], row["count"]))
                    break
            else:
                groups.append({"label": f"stored:{row['id']}", "ids": [row["id"]], "unit": c, "utterances": row["count"], "seconds": round(row["seconds"], 1),
                               "last_text": row["last_text"], "last_seen": row["last_seen"], "first_seen": row["first_seen"], "clip": row["clip"],
                               "cents": [(row["centroid"], row["count"])]})
        return groups

    @r.get("/unnamed")
    async def unnamed() -> list:
        out = {}
        for e in sk.pipeline.window:
            if e.get("person_id") is None and e.get("cluster") and not e.get("dismissed"):
                c = out.setdefault(e["cluster"], {"label": e["cluster"], "utterances": 0, "last_text": "", "seconds": 0.0, "last_seen": e["t1"]})
                c["utterances"] += 1
                c["last_text"] = e["text"]
                c["last_seen"] = e["t1"]
                c["seconds"] = round(c["seconds"] + (e["t1"] - e["t0"]), 1)
        stored = [{k: g[k] for k in ("label", "utterances", "last_text", "seconds", "last_seen")} for g in _stored_groups()]
        return list(out.values()) + stored

    @r.get("/unnamed/{label}/clip")
    async def unnamed_clip(label: str) -> Response:
        """A few seconds of that voice so you can hear who it is."""
        if label.startswith("stored:"):
            g = next((x for x in _stored_groups() if x["label"] == label), None)
            a = None if g is None or g["clip"].size == 0 else g["clip"]
        else:
            a = sk.speaker.clip(label)
        if a is None:
            raise HTTPException(404, "I no longer have a recording of that voice.")
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(a.tobytes())
        return Response(buf.getvalue(), media_type="audio/wav")

    @r.post("/unnamed/{label}/dismiss")
    async def dismiss_unnamed(label: str) -> dict:
        """Not worth naming: forget this voice now."""
        if label.startswith("stored:"):
            g = next((x for x in _stored_groups() if x["label"] == label), None)
            if g is None:
                raise HTTPException(404, "I no longer have that voice.")
            sk.store.delete_unnamed(ids=g["ids"])
        else:
            sk.speaker.drop_cluster(label)
            sk.store.delete_unnamed(conv_id=sk.pipeline.conv_id, label=label)
            for e in sk.pipeline.window:
                if e.get("cluster") == label:
                    e["dismissed"] = True
        return {"ok": True}

    @r.post("/unnamed/{label}/name")
    async def name_unnamed(label: str, body: dict = Body(...)) -> dict:
        person = None
        if body.get("person_id") is not None:                    # "this is an existing person": add the voice to them
            person = sk.store.person(body["person_id"])
            if not person:
                raise HTTPException(404, "That person does not exist.")
            body = {"name": person["name"], "consent": "Already agreed (existing person)"}
        name, consent = (body.get("name") or "").strip(), (body.get("consent") or "").strip()
        if not name or not consent:
            bad("Please give a name and confirm this person agreed to be remembered.")
        if label.startswith("stored:"):
            g = next((x for x in _stored_groups() if x["label"] == label), None)
            if g is None:
                raise HTTPException(404, "I no longer have that voice.")
            existing = sk.store.person_by_name(name)
            pid = existing["id"] if existing else sk.store.add_person(name, consent)
            cent = sum(c * n for c, n in g["cents"])
            sk.store.add_voice_sample(pid, cent / (np.linalg.norm(cent) or 1.0), "cluster")
            for piece in chunks(g["clip"], 3.0, 0.0)[:3] if g["clip"].size >= 16000 * 2 else []:
                sk.store.add_voice_sample(pid, sk.speaker.embed(piece), "cluster")
            sk.speaker.reload()
            sk.store.delete_unnamed(ids=g["ids"])
            sk.events.publish("enrolled", person_id=pid, name=name, seconds=g["seconds"], similar=[])
            return {"person_id": pid}
        try:
            pid = sk.pipeline.name_cluster(label, name, consent)
        except (ValueError, KeyError) as exc:
            bad(str(exc))
        return {"person_id": pid}

    @r.post("/people/{pid}/rename")
    async def rename_person(pid: int, body: dict = Body(...)) -> dict:
        p = sk.store.person(pid)
        if not p:
            raise HTTPException(404, "That person does not exist.")
        name = (body.get("name") or "").strip()
        if not name:
            bad("Please type a name.")
        if p["name"] == sk.cfg.self_name:
            bad("This is you. I find your voice by this entry, so it keeps its name.")
        other = sk.store.person_by_name(name)
        if other and other["id"] != pid:
            bad(f"Someone is already called {other['name']}.")
        if any(x["name"].lower() == name.lower() and x["id"] != pid for x in sk.store.people()):
            bad("Someone is already called that.")
        old = p["name"]
        sk.store.rename_person(pid, name)
        for e in sk.pipeline.window:
            if e.get("person_id") == pid:
                e["speaker"] = name
        sk.events.publish("renamed", person_id=pid, old=old, name=name)
        return {"name": name}

    @r.post("/people/{pid}/make-assistant")
    async def make_assistant(pid: int) -> dict:
        """'This is Sidekick's own voice': stop listing it as a person and forget what it 'said'."""
        if not sk.store.person(pid):
            raise HTTPException(404, "That person does not exist.")
        sk.store.mark_assistant(pid)
        sk.speaker.reload()
        sk.pipeline.window[:] = [e for e in sk.pipeline.window if e.get("person_id") != pid]
        sk.events.publish("forgotten", person_id=pid)
        return {"ok": True}

    # ---- people -----------------------------------------------------------------------------------------------------
    @r.get("/people/{pid}")
    async def person(pid: int) -> dict:
        d = sk.memory.dossier(pid)
        if not d:
            bad("No such person.", 404)
        loops = sk.memory.commitments(pid, "open")
        convs = []
        for s in reversed(sk.store.segments(person_id=pid, limit=400)):
            if s["conv_id"] not in [c["id"] for c in convs]:
                row = sk.store.q("SELECT * FROM conversations WHERE id=?", (s["conv_id"],))
                if row:
                    convs.append({"id": row[0]["id"], "title": row[0]["title"], "start": row[0]["start"]})
            if len(convs) >= 5:
                break
        open_text = "; ".join(f"{c['text']}" + (f" by {c['due']}" if c["due"] else "") for c in loops)
        brief = f"Before you talk to {d['person']['name']}: " + (f"open: {open_text}. " if open_text else "nothing open. ") + \
                (f"Last said: {d['recent'][-1]}" if d["recent"] else "")
        return {"person": d["person"], "facts": d["facts"], "topics": d["topics"], "commitments": loops,
                "recent_conversations": convs, "last_seen": d["last_seen"], "brief": brief.strip(),
                "assistant_like": sk.speaker.assistant_like(pid)}

    @r.post("/people/{pid}/forget-preview")
    async def forget_preview(pid: int) -> dict:
        if not sk.store.person(pid):
            bad("No such person.", 404)
        return sk.store.forget_preview(pid)

    @r.post("/people/{pid}/forget")
    async def forget(pid: int) -> dict:
        if not sk.store.person(pid):
            bad("No such person.", 404)
        return sk.forget_person(pid)

    # ---- library & open loops ---------------------------------------------------------------------------------------
    def card(c: dict) -> dict:
        segs = sk.store.segments(conv_id=c["id"])
        people = sorted({s["speaker"] or s["cluster"] for s in segs if s["speaker"] or s["cluster"]})
        facts = sk.store.q("SELECT text FROM facts WHERE source_segment IN (SELECT id FROM segments WHERE conv_id=?) LIMIT 2", (c["id"],))
        summary = " · ".join(f["text"] for f in facts) or (segs[0]["text"][:100] if segs else "")
        title = c["title"] or "Conversation on " + datetime.fromtimestamp(c["start"]).strftime("%A %-d %B")
        return {"id": c["id"], "title": title, "date": c["start"], "people": people, "summary": summary,
                "marks": len(sk.store.bookmarks(c["id"])), "segments": len(segs)}

    @r.get("/library")
    async def library(q: str | None = None) -> list:
        rows = [c for c in sk.store.conversations(200) if c["segments"] > 0]
        if q:
            ids = {x["conv_id"] for x in sk.store.q("SELECT DISTINCT conv_id FROM segments WHERE text LIKE ?", (f"%{q}%",))}
            rows = [c for c in rows if c["id"] in ids or q.lower() in (c["title"] or "").lower()]
        return [card(c) for c in rows]

    @r.get("/library/{cid}")
    async def library_one(cid: int) -> dict:
        row = sk.store.q("SELECT * FROM conversations WHERE id=?", (cid,))
        if not row:
            bad("No such conversation.", 404)
        row = row[0]; row["segments"] = len(sk.store.segments(conv_id=cid))
        return {"card": card(row), "transcript": [{k: v for k, v in s.items() if k != "embedding"} for s in sk.store.segments(conv_id=cid)],
                "bookmarks": sk.store.bookmarks(cid), "loops": sk.memory.commitments(None, "open")}

    @r.get("/open-loops")
    async def open_loops() -> list:
        return sk.memory.commitments(None, "open")

    @r.post("/open-loops/{fid}/done")
    async def loop_done(fid: int) -> dict:
        sk.store.set_fact_status(fid, "done")
        return {"ok": True}

    @r.post("/open-loops/{fid}/reopen")
    async def loop_reopen(fid: int) -> dict:
        sk.store.set_fact_status(fid, "open")
        return {"ok": True}

    # ---- privacy ------------------------------------------------------------------------------------------------
    def sentence(a: dict) -> str:
        d, k = a["detail"], a["kind"]
        if k == "mode":
            return "Switched to " + {"standby": "Standby", "listen": "Listen", "autopilot": "Autopilot", "interpreter": "Interpreter",
                                     "private": "Private"}.get(d.get("to"), str(d.get("to")))
        if k == "recording_start":
            return "Started recording audio"
        if k == "memory_level":
            return f"Changed what is remembered to {d.get('to')}"
        if k == "forget":
            n = d.get("deleted", {})
            return f"Forgot a person ({n.get('segments', 0)} lines, {n.get('facts', 0)} notes deleted)"
        if k == "settings":
            return "Changed settings"
        if k == "delete_everything":
            return "Deleted everything Sidekick remembered"
        return k.replace("_", " ").capitalize()

    @r.get("/activity")
    async def activity(n: int = Query(100, le=500)) -> list:
        return [{"ts": a["ts"], "text": sentence(a)} for a in sk.store.audit_log(n)]

    @r.post("/delete-everything")
    async def delete_everything(body: dict = Body(...)) -> dict:
        if (body.get("confirm") or "").strip().lower() != "delete everything":
            bad("Type the phrase 'delete everything' to confirm.")
        return {"ok": True, "deleted": await sk.delete_everything()}

    # ---- first-run setup ------------------------------------------------------------------------------------------
    setup_file = Path(sk.cfg.data_dir) / "setup.json"

    @r.get("/setup/status")
    async def setup_status() -> dict:
        done = setup_file.exists() and json.loads(setup_file.read_text()).get("done", False)
        me = sk.store.person_by_name(sk.cfg.self_name)
        return {"done": bool(done), "has_me": me is not None, "me_ready": bool(me and sk.speaker.ready_for(me["id"]))}

    @r.post("/setup/done")
    async def setup_done() -> dict:
        setup_file.write_text(json.dumps({"done": True, "ts": time.time()}))
        return {"ok": True}

    @r.post("/setup/mic-check")
    async def mic_check(body: dict = Body(default={})) -> dict:
        seconds = float(body.get("seconds", 6))
        loop = asyncio.get_running_loop()
        out: dict = {"buds": None, "mac": None, "errors": {}}
        for key, placement in (("buds", "ear"), ("mac", "remote")):
            try:
                out[key] = measure(await loop.run_in_executor(None, sk.record_from, placement, seconds))
            except Exception as exc:  # noqa: BLE001  one mic missing must not hide the other
                out["errors"][key] = str(exc) or exc.__class__.__name__
        b, m = out["buds"], out["mac"]
        if b and m:
            out["recommend"] = "ear" if b["snr_db"] >= m["snr_db"] else "remote"
        else:
            out["recommend"] = "ear" if b else "remote"
        out["advice"] = ("The buds mic heard clearly. Use it when the buds are in your ears." if out["recommend"] == "ear"
                         else "The Mac microphone heard more clearly. Sit near the Mac, or keep the buds out as a remote.")
        if not b:
            out["advice"] = "The buds mic is not available, so Sidekick will use the Mac microphone. " + out["advice"]
        return out

    @r.post("/setup/enroll-self")
    async def enroll_self(body: dict = Body(default={})) -> dict:
        name = sk.cfg.self_name
        existing = sk.store.person_by_name(name)
        if existing and sk.speaker.ready_for(existing["id"]):
            bad("Your voice is already set up. To add more of it, use Record more on your People page.")
        loop = asyncio.get_running_loop()
        if body.get("wav_base64"):
            audio = wav_to_audio(body["wav_base64"])
        else:
            audio = await loop.run_in_executor(None, sk.record_sample, float(body.get("seconds", 20)))
        if audio.size < 16000 * 2:
            bad("I need at least 2 seconds of you speaking. Try again, closer to the microphone.")
        pid = await loop.run_in_executor(None, lambda: sk.speaker.enroll(name, chunks(audio, 4.0, 1.0), "My own voice (set up in the dashboard)",
                                                                        source="enrol:" + ("buds" if sk.modes.placement == "ear" else "laptop")))
        sk.events.publish("enrolled", person_id=pid, name=name, seconds=round(audio.size / 16000, 1), similar=[])
        return {"id": pid, "seconds": round(audio.size / 16000, 1)}

    async def _audio_from(body: dict, default_seconds: float) -> np.ndarray:
        if body.get("wav_base64"):
            audio = wav_to_audio(body["wav_base64"])
        else:
            placement = body.get("placement") or sk.modes.placement
            audio = await asyncio.get_running_loop().run_in_executor(None, sk.record_from, placement, float(body.get("seconds", default_seconds)))
        sk.last_recording = audio                              # so the sheet can play it back ("hear it back"); memory only
        return audio

    def _source(body: dict) -> str:
        if body.get("source") in ("buds", "laptop", "other"):
            return body["source"]
        return "buds" if body.get("placement") == "ear" else "laptop"

    @r.get("/voices/last-clip")
    async def last_clip() -> Response:
        a = getattr(sk, "last_recording", None)
        if a is None or a.size == 0:
            raise HTTPException(404, "There is no recording yet.")
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(a.astype(np.int16).tobytes() if a.dtype == np.int16 else (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
        return Response(buf.getvalue(), media_type="audio/wav")

    @r.post("/voices/new")
    async def voices_new(body: dict = Body(...)) -> dict:
        name, consent = (body.get("name") or "").strip(), (body.get("consent") or "").strip()
        if not name or not consent:
            bad("Please give a name and confirm this person agreed to be remembered.")
        if sk.store.person_by_name(name):
            bad("Someone with that name already exists. Choose the existing person and add this recording to them.")
        audio = await _audio_from(body, 12)
        if audio.size < 16000 * 2:
            bad("I need at least 2 seconds of speech. Try again, closer to the microphone.")
        src = _source(body)
        pid = await asyncio.get_running_loop().run_in_executor(None, lambda: sk.speaker.enroll(name, chunks(audio, 4.0, 1.0), consent, source=f"enrol:{src}"))
        sk.events.publish("enrolled", person_id=pid, name=name, seconds=round(audio.size / 16000, 1), similar=[])
        return {"person_id": pid, "sources": sk.speaker.sources(pid)}

    @r.post("/setup/add-voice-sample")
    async def add_voice_sample(body: dict = Body(default={})) -> dict:
        """More of your voice, from another microphone or room: the buds mic and the Mac mic sound different."""
        me = sk.store.person_by_name(sk.cfg.self_name)
        if not me:
            bad("Set up your voice first.")
        audio = await _audio_from(body, 20)
        if audio.size < 16000 * 2:
            bad("I need at least 2 seconds of you speaking. Try again, closer to the microphone.")
        n = sk.speaker.add_clips(me["id"], chunks(audio, 4.0, 1.0), source="enrol-" + (body.get("placement") or sk.modes.placement))
        sk.store.audit("settings", {"voice_samples_added": n})
        return {"added": n, "total": len(sk.store.voice_samples(me["id"]))}

    @r.post("/voices/add")
    async def voices_add(body: dict = Body(...)) -> dict:
        """Add a recording to a voice that already exists (same person, another microphone): no duplicate person is created."""
        pid = body.get("person_id")
        if not pid or not sk.store.person(pid):
            raise HTTPException(404, "That person does not exist.")
        source = _source(body)
        audio = await _audio_from(body, 20)
        if audio.size < 16000 * 2:
            bad("I need at least 2 seconds of speech. Try again, closer to the microphone.")
        n = await asyncio.get_running_loop().run_in_executor(None, lambda: sk.speaker.add_clips(pid, chunks(audio, 4.0, 1.0), source=f"enrol:{source}"))
        sk.store.audit("settings", {"voice_samples_added": n, "person_id": pid, "source": source})
        return {"added": n, "sources": sk.speaker.sources(pid)}

    @r.get("/voices/{pid}/health")
    async def voices_health(pid: int) -> dict:
        if not sk.store.person(pid):
            raise HTTPException(404, "That person does not exist.")
        return sk.speaker.health(pid)

    @r.post("/voices/{pid}/forget-learning")
    async def voices_forget_learning(pid: int) -> dict:
        """Undo what Sidekick learned about this voice by listening (your recorded samples stay)."""
        if not sk.store.person(pid):
            raise HTTPException(404, "That person does not exist.")
        return {"removed": sk.speaker.forget_adapted(pid)}

    @r.post("/setup/calibrate")
    async def calibrate(body: dict = Body(default={})) -> dict:
        """Say a few new sentences: they are scored against your voiceprint (and against other voices) to place the match threshold."""
        me = sk.store.person_by_name(sk.cfg.self_name)
        if not me:
            bad("Set up your voice first.")
        audio = await _audio_from(body, 15)
        if audio.size < 16000 * 6:
            bad("I need about 10 seconds of you speaking for the check.")
        loop = asyncio.get_running_loop()
        rep = await loop.run_in_executor(None, lambda: evaluate(sk.speaker, me["id"], chunks(audio, 3.0, 0.0), sk.impostor_clips()))
        sk.cfg.speaker_threshold = sk.speaker.threshold = rep["threshold"]
        sk.store.audit("settings", {"speaker_threshold": rep["threshold"], "voice_check": rep["verdict"]})
        return rep

    return r
