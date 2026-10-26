"""Capability matrix, unknown-message table and protocol findings, all derived from the store."""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .store import Store

STATUS_LABEL = {"VERIFIED": "Verified", "PARTIAL": "Partial", "UNKNOWN_SIGNAL": "Unknown signal",
                "NOT_OBSERVED": "Not observed", "SKIPPED": "Skipped"}
GENERATED_MARK = "<!-- AUTO-GENERATED BELOW: regenerated on every export; edit above this line only -->"


def _sessions(store: Store, include_simulated: bool) -> list[str]:
    rows = store.q("SELECT id, mode FROM sessions")
    return [r["id"] for r in rows if include_simulated or r["mode"] == "hardware"]


def _in(ids: list[str]) -> tuple[str, tuple]:
    return f"({','.join('?' * len(ids))})", tuple(ids)


def unknown_table(store: Store, include_simulated: bool = True, session: str | None = None) -> list[dict]:
    """Undecoded rx message IDs: count, first/last seen, examples, and which experiment was armed."""
    ids = [session] if session else _sessions(store, include_simulated)
    if not ids:
        return []
    ph, args = _in(ids)
    rows = store.q(f"SELECT ts, data, raw_hex, experiment_id, session_id FROM events WHERE type='frame' "
                   f"AND session_id IN {ph} ORDER BY ts", args)
    agg: dict[int, dict] = {}
    for r in rows:
        d = json.loads(r["data"])
        if d.get("dir") != "rx" or d.get("known"):
            continue
        a = agg.setdefault(d.get("msg_id", -1), {"msg_id": d.get("msg_id", -1), "name": d.get("name", "junk"),
                                                 "count": 0, "first_seen": r["ts"], "last_seen": r["ts"],
                                                 "examples": [], "actions": Counter()})
        a["count"] += 1
        a["last_seen"] = r["ts"]
        if len(a["examples"]) < 3 and d.get("payload_hex", "") not in a["examples"]:
            a["examples"].append(d.get("payload_hex", r["raw_hex"]))
        a["actions"][r["experiment_id"] or "(idle)"] += 1
    out = []
    for a in sorted(agg.values(), key=lambda x: -x["count"]):
        a["actions"] = dict(a["actions"].most_common())
        out.append(a)
    return out


def msg_frequency(store: Store, session: str) -> list[dict]:
    rows = store.q("SELECT data FROM events WHERE type='frame' AND session_id=?", (session,))
    c: Counter = Counter()
    names: dict = {}
    for r in rows:
        d = json.loads(r["data"])
        key = (d.get("dir"), d.get("msg_id"))
        c[key] += 1
        names[key] = d.get("name", "?")
    return [{"dir": k[0], "msg_id": k[1], "name": names[k], "count": n} for k, n in c.most_common()]


def _layer_of(signals: list[dict]) -> str:
    ls = sorted({s["layer"] for s in signals if s.get("layer") in ("A", "B", "C")})
    return "+".join(ls) if ls else "-"


def _describe(sig: dict) -> str:
    s = sig["type"] + (f":{sig['detail']}" if sig.get("detail") else "")
    if sig.get("msg_id") not in (None, -1):
        s += f" (msg {sig['msg_id']})"
    return s


def capability_matrix(store: Store, catalog: list, include_simulated: bool = False) -> dict[str, Any]:
    ids = _sessions(store, include_simulated)
    rows: list[dict] = []
    attempts: dict[str, list[dict]] = defaultdict(list)
    notes: dict[str, list[str]] = defaultdict(list)
    if ids:
        ph, args = _in(ids)
        for a in store.q(f"SELECT * FROM attempts WHERE session_id IN {ph} ORDER BY id", args):
            attempts[a["experiment_id"]].append(a)
        for n in store.q(f"SELECT experiment_id, text FROM notes WHERE session_id IN {ph}", args):
            notes[n["experiment_id"] or "(general)"].append(n["text"])
    for e in catalog:
        att = [a for a in attempts.get(e.id, []) if a["status"] != "SKIPPED"]
        ver = [a for a in att if a["status"] == "VERIFIED"]
        best = ("VERIFIED" if ver else next((s for s in ("PARTIAL", "UNKNOWN_SIGNAL", "NOT_OBSERVED")
                                            if any(a["status"] == s for a in att)), None))
        seen: list[dict] = []
        for a in (ver or att):
            seen += json.loads(a["signals"] or "[]") if not ver else json.loads(a["matched"] or "[]")
        uniq = list(dict.fromkeys(_describe(s) for s in seen))
        rows.append({
            "id": e.id, "capability": e.title, "category": e.category, "layer": _layer_of(seen) if seen else "-",
            "how_to_trigger": e.instruction, "signal_seen": "; ".join(uniq[:6]) or "-",
            "reliability": f"{len(ver)} of {len(att)} attempts" if att else "not tested",
            "status": STATUS_LABEL.get(best, "Not tested") if best else "Not tested",
            "manual": any(a["manual"] for a in ver), "notes": " | ".join(notes.get(e.id, [])),
        })
    cmd_rows = []
    if ids:
        ph, args = _in(ids)
        by: dict[str, list[dict]] = defaultdict(list)
        for c in store.q(f"SELECT * FROM commands WHERE session_id IN {ph}", args):
            by[c["name"]].append(c)
        for name, cs in sorted(by.items()):
            lat = [c["latency_ms"] for c in cs if c["latency_ms"] is not None]
            st = Counter(c["status"] for c in cs)
            cmd_rows.append({"command": name, "attempts": len(cs), "acked": st["acked"], "rejected": st["rejected"],
                             "no_response": st["no_response"],
                             "latency_ms_median": round(statistics.median(lat), 1) if lat else None,
                             "latency_ms_max": round(max(lat), 1) if lat else None})
    obs = _observations(store, ids)
    return {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "includes_simulated": include_simulated,
            "sessions": ids, "capabilities": rows, "commands": cmd_rows, "observations": obs,
            "unknown_messages": unknown_table(store, include_simulated)}


def _observations(store: Store, ids: list[str]) -> dict:
    if not ids:
        return {}
    ph, args = _in(ids)
    out: dict[str, Any] = {}
    b = store.q(f"SELECT session_id, ts FROM events WHERE type='battery' AND session_id IN {ph} ORDER BY ts", args)
    per: dict[str, list[float]] = defaultdict(list)
    for r in b:
        per[r["session_id"]].append(r["ts"])
    gaps = [y - x for ts in per.values() for x, y in zip(ts, ts[1:]) if y - x < 3600]
    if gaps:
        out["battery_report_interval_s"] = {"median": round(statistics.median(gaps), 1), "min": round(min(gaps), 1),
                                           "max": round(max(gaps), 1), "samples": len(gaps),
                                           "note": "battery is reported with every status message; compare with "
                                                   "'battery-cadence' experiment"}
    cases = [json.loads(r["data"]).get("case") or 0 for r in
             store.q(f"SELECT data FROM events WHERE type='battery' AND session_id IN {ph}", args)]
    if cases:
        out["case_battery_reported"] = any(c > 0 for c in cases)
        out["case_battery_note"] = "0 with buds out of the case is normal; a value >0 means the case level is exposed"
    touch = store.q(f"SELECT side, data FROM events WHERE type IN ('touch','media_key') AND session_id IN {ph}", args)
    if touch:
        out["touch_events_with_side"] = sum(1 for t in touch if t["side"] in ("L", "R"))
        out["touch_events_total"] = len(touch)
    return out


def to_markdown(m: dict) -> str:
    L = ["# Buds FE capability matrix", "", f"Generated {m['generated']}"
         + ("  (**includes simulated sessions; not evidence about real hardware**)" if m["includes_simulated"] else ""),
         f"Sessions: {', '.join(m['sessions']) or 'none'}", "",
         "| Capability | Category | Layer | How to trigger | Signal seen | Reliability | Status | Notes |",
         "|---|---|---|---|---|---|---|---|"]
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")   # noqa: E731
    for r in m["capabilities"]:
        st = r["status"] + (" (manual)" if r["manual"] else "")
        L.append(f"| {esc(r['capability'])} | {r['category']} | {r['layer']} | {esc(r['how_to_trigger'])} | "
                 f"{esc(r['signal_seen'])} | {r['reliability']} | {st} | {esc(r['notes'])} |")
    if m["commands"]:
        L += ["", "## Commands", "", "| Command | Attempts | Acked | Rejected | No response | Median latency ms | Max ms |",
              "|---|---|---|---|---|---|---|"]
        for c in m["commands"]:
            L.append(f"| {c['command']} | {c['attempts']} | {c['acked']} | {c['rejected']} | {c['no_response']} | "
                     f"{c['latency_ms_median']} | {c['latency_ms_max']} |")
    if m["observations"]:
        L += ["", "## Observations", "", "```json", json.dumps(m["observations"], indent=2), "```"]
    if m["unknown_messages"]:
        L += ["", "## Unknown messages (undecoded, listen-only)", "",
              "| ID | Count | First seen | Examples | Active experiment(s) |", "|---|---|---|---|---|"]
        for u in m["unknown_messages"]:
            L.append(f"| {u['msg_id']} ({u['name']}) | {u['count']} | "
                     f"{time.strftime('%H:%M:%S', time.localtime(u['first_seen']))} | "
                     f"{', '.join('`'+e+'`' for e in u['examples'])} | {esc(json.dumps(u['actions']))} |")
    return "\n".join(L) + "\n"


def protocol_findings(store: Store, include_simulated: bool = False) -> str:
    """Per message ID: what we saw, decoded fields, and a confidence level.

    Confirmed = decoded without error from *real hardware* traffic in this project's sessions.
    Likely    = a decoder exists (from the community reference for other models) but never seen on hardware.
    Unknown   = seen, no decoder; or only listed in the ID table.
    """
    ids = _sessions(store, include_simulated)
    lines = [GENERATED_MARK, "", f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')} from sessions: "
             f"{', '.join(ids) or 'none (no hardware sessions yet)'}_", ""]
    if not ids:
        return "\n".join(lines) + "\nNo hardware sessions recorded yet.\n"
    ph, args = _in(ids)
    rows = store.q(f"SELECT ts, data, raw_hex, experiment_id FROM events WHERE type='frame' AND session_id IN {ph} "
                   f"ORDER BY ts", args)
    agg: dict[tuple, dict] = {}
    for r in rows:
        d = json.loads(r["data"])
        if d.get("junk"):
            continue
        k = (d["dir"], d["msg_id"])
        a = agg.setdefault(k, {"name": d["name"], "count": 0, "known": d.get("known"), "ok": True,
                               "sizes": set(), "example": None, "fields": None, "actions": Counter(),
                               "first": r["ts"], "last": r["ts"], "crc_bad": 0})
        a["count"] += 1
        a["last"] = r["ts"]
        a["sizes"].add(len(d.get("payload_hex", "")) // 2)
        a["crc_bad"] += 0 if d.get("crc_ok", True) else 1
        if d.get("error"):
            a["ok"] = False
        if a["example"] is None:
            a["example"] = d.get("payload_hex", "")
        if a["fields"] is None and d.get("fields") and d.get("known"):
            a["fields"] = d["fields"]
        a["actions"][r["experiment_id"] or "(idle)"] += 1
    lines += ["| Dir | ID | Name | Count | Payload sizes | Confidence | Active during | Example payload (hex) |",
              "|---|---|---|---|---|---|---|---|"]
    for (direction, mid), a in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        conf = "Confirmed" if (a["known"] and a["ok"] and direction == "rx" and not a["crc_bad"]) \
            else "Likely" if a["known"] else "Unknown"
        act = ", ".join(f"{k}×{v}" for k, v in a["actions"].most_common(3))
        lines.append(f"| {direction} | {mid} | {a['name']} | {a['count']} | {sorted(a['sizes'])} | {conf} | {act} | "
                     f"`{(a['example'] or '')[:64]}` |")
    lines += ["", "## Decoded field examples", ""]
    for (direction, mid), a in sorted(agg.items()):
        if a["fields"]:
            lines += [f"### {a['name']} ({mid}, {direction})", "", "```json", json.dumps(a["fields"], indent=2), "```", ""]
    return "\n".join(lines) + "\n"


def write_exports(store: Store, catalog: list, out_dir: Path, docs_path: Path, include_simulated: bool) -> dict:
    m = capability_matrix(store, catalog, include_simulated)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "capabilities.json").write_text(json.dumps(m, indent=2, default=str))
    (out_dir / "capabilities.md").write_text(to_markdown(m))
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    head = ""
    if docs_path.exists():
        head = docs_path.read_text().split(GENERATED_MARK)[0]
    if not head.strip():
        head = "# Protocol findings (Galaxy Buds FE, SM-R400)\n\nHand-written notes go here; everything below the marker is regenerated.\n\n"
    docs_path.write_text(head.rstrip() + "\n\n" + protocol_findings(store, include_simulated))
    return {"json": str(out_dir / "capabilities.json"), "md": str(out_dir / "capabilities.md"),
            "findings": str(docs_path)}
