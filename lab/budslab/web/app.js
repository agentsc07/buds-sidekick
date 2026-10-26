/* Buds FE Capability Lab: dashboard. Plain JS, Chart.js vendored locally (works offline). */
"use strict";

// ---------------------------------------------------------------- state
const S = {
  status: null, runner: null, catalog: [], results: {}, allAttempts: [],
  events: [],            // everything except raw frames
  frames: [],            // raw frames (rx/tx)
  lastSeq: 0, offset: 0, // offset = server clock - client clock (s)
  cmdList: [], view: "live", charts: {},
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtT = (t) => (t ?? 0).toFixed(1);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
};
const post = (p, body = {}) => api(p, { method: "POST", body });
function toast(msg, ms = 3500) { const t = $("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), ms); }
const safe = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message); } };
const now = () => Date.now() / 1000 + S.offset;

// ---------------------------------------------------------------- sound / flash
let actx = null;
function beep(freq = 880, dur = 0.12, type = "sine") {
  if (!$("sound-on").checked) return;
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator(), g = actx.createGain();
    o.type = type; o.frequency.value = freq; g.gain.value = 0.08;
    o.connect(g); g.connect(actx.destination); o.start(); o.stop(actx.currentTime + dur);
  } catch (_) { /* audio blocked until first click */ }
}
function flash() { const c = $("actioncard"); c.classList.remove("flash"); void c.offsetWidth; c.classList.add("flash"); }

// ---------------------------------------------------------------- navigation
document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
function showView(v) {
  S.view = v;
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".view").forEach((s) => s.classList.toggle("active", s.id === "view-" + v));
  if (v === "metrics") drawMetrics();
  if (v === "guided") renderExperiments();
  if (v === "protocol") refreshProtocol();
  if (v === "commands") renderCommands();
  if (v === "mic") loadMicDevices();
  if (v === "report") refreshReport();
}

// ---------------------------------------------------------------- data intake
function ingest(ev) {
  if (ev.seq <= S.lastSeq) return;
  S.lastSeq = ev.seq;
  if (ev.type === "frame") { S.frames.push(ev); if (S.frames.length > 6000) S.frames.splice(0, 1000); }
  else S.events.push(ev);
  if (ev.type !== "frame") feedAdd(ev); else if (!ev.data.known && ev.data.dir === "rx" && $("feed-unknown").checked) feedAdd(ev);
  if (ev.type === "battery") updateDevice(ev);
  if (["wear", "anc", "touch", "case"].includes(ev.type)) updateDevice(ev);
  if (S.view === "protocol" && ev.type === "frame") scheduleFrames();
  if (S.view === "commands" && ev.type === "command_result") renderCmdLog();
}

async function loadHistory() {
  const [ev, fr] = await Promise.all([
    api("/api/events?limit=20000&type=battery,touch,wear,case,anc,audio,media_key,conn,status,command_result,note,system,unknown"),
    api("/api/events?limit=5000&type=frame"),
  ]);
  S.events = []; S.frames = []; S.lastSeq = 0;
  [...ev, ...fr].sort((a, b) => a.seq - b.seq).forEach(ingest);
}

function connectWS() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  ws.onopen = () => { $("pill-link").title = "dashboard connected"; };
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.kind === "hello") { setStatus(d.status); setRunner(d.runner); }
    else if (d.kind === "status") setStatus(d.status);
    else if (d.kind === "runner") setRunner(d);
    else if (d.kind === "event") ingest(d.event);
    else if (d.kind === "signal") onSignal(d);
    else if (d.kind === "result") onResult(d.result);
    else if (d.kind === "toast") toast(d.text, 6000);
  };
  ws.onclose = () => { $("pill-link").textContent = "dashboard offline"; $("pill-link").className = "pill bad"; setTimeout(async () => { try { await loadHistory(); } catch (_) {} connectWS(); }, 1500); };
}

// ---------------------------------------------------------------- status / device
function setStatus(st) {
  S.status = st; S.offset = st.server_now - Date.now() / 1000;
  const l = $("pill-link"), link = st.link;
  l.textContent = link === "connected" ? "buds connected" : link;
  l.className = "pill " + (link === "connected" ? "ok" : link === "error" ? "bad" : "warn");
  l.title = st.link_info?.error || JSON.stringify(st.link_info || {});
  $("pill-mode").textContent = st.mode === "hardware" ? "hardware" : st.mode.toUpperCase() + " (not real data)";
  const c = $("pill-cmd"); c.textContent = st.commands_enabled ? "commands ENABLED" : "read-only"; c.className = "pill " + (st.commands_enabled ? "bad" : "");
  $("hdr-progress").textContent = `${st.experiments_verified}/${st.experiments_total} verified`;
  $("cmd-enable").checked = !!st.commands_enabled;
  const la = Object.entries(st.layer_a || {}).map(([k, v]) => `${k}: ${v}`).join("  ·  ");
  $("layer-a-status").textContent = la ? "Layer A sources — " + la : "";
  const d = st.device_state || {};
  if (d.battery_l !== undefined) updateDevice({ type: "battery", data: { left: d.battery_l, right: d.battery_r, case: d.battery_case } });
  setWear("L", d.placement_l); setWear("R", d.placement_r);
  if (d.noise_mode) $("d-anc").textContent = d.noise_mode;
  if (d.touch_locked !== undefined) $("d-lock").textContent = d.touch_locked ? "locked" : "unlocked";
  const pr = st.experiments_total ? st.experiments_verified / st.experiments_total * 100 : 0;
  $("c-prog").style.width = pr + "%"; $("c-prog-t").textContent = `${st.experiments_verified} / ${st.experiments_total}`;
  $("c-rx").textContent = st.counters.frames_rx; $("c-tx").textContent = st.counters.frames_tx; $("c-events").textContent = st.counters.events;
}
const PLACE = { 0: "disconnected", 1: "in ear", 2: "out", 3: "in case", 4: "case?" };
function setWear(side, p) {
  if (p === undefined) return;
  const e = $(side === "L" ? "w-l" : "w-r"); e.textContent = `${side} ${PLACE[p] ?? p}`;
  e.className = "chip " + (p === 1 ? "in" : p === 3 ? "case" : "");
}
function updateDevice(ev) {
  const d = ev.data;
  if (ev.type === "battery") {
    for (const [k, id] of [["left", "l"], ["right", "r"], ["case", "c"]]) {
      if (d[k] === undefined) continue; $("bat-" + id).style.width = d[k] + "%"; $("bat-" + id + "-t").textContent = d[k] + "%";
    }
  } else if (ev.type === "wear") setWear(ev.side, d.placement);
  else if (ev.type === "anc") $("d-anc").textContent = d.mode;
  else if (ev.type === "touch" && d.event === "touchpad_lock") $("d-lock").textContent = d.locked ? "locked" : "unlocked";
}

// ---------------------------------------------------------------- signal feed
function describe(ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case "media_key": return `media key: ${d.key}${d.repeat ? " (repeat)" : ""}`;
    case "wear": return `${ev.side} → ${d.state}`;
    case "case": return `${d.event}${ev.side ? " " + ev.side : ""}${d.target ? " (" + d.target + ")" : ""}`;
    case "anc": return `noise control → ${d.mode}`;
    case "touch": return d.gesture ? `${ev.side} bud: ${d.gesture.replace("_", " ")}` : d.event === "touchpad_lock" ? `touchpad ${d.locked ? "locked" : "unlocked"}` : JSON.stringify(d);
    case "battery": return `L ${d.left}%  R ${d.right}%  case ${d.case}%`;
    case "command_result": return `${d.name} ${JSON.stringify(d.args)} → ${d.status}${d.latency_ms != null ? " " + d.latency_ms + " ms" : ""}`;
    case "frame": return `UNDECODED id ${d.msg_id} ${d.name}  ${d.payload_hex || ""}`;
    case "conn": return `${ev.source}: ${d.event}${d.error ? " – " + d.error : ""}`;
    case "audio": return d.event === "recording" ? `recorded ${d.file}: SNR ${d.snr_db} dB` : `${d.event} ${d.output_default ? "out✓" : ""} ${d.input_default ? "in✓" : ""} ${d.output_rate ?? ""}`;
    case "note": return "note: " + d.text;
    case "system": return `${d.event}${d.id ? " " + d.id : ""}${d.status ? " → " + d.status : ""}${d.message ? " " + d.message : ""}`;
    default: return JSON.stringify(d);
  }
}
function feedAdd(ev) {
  if (ev.type === "battery" && !$("feed-battery").checked) return;
  if (ev.type === "system" && !$("feed-system").checked) return;
  if (ev.data?.initial && ev.type !== "conn") { /* still show, tagged */ }
  const f = $("feed"), r = document.createElement("div"); r.className = "row";
  r.innerHTML = `<span>${fmtT(ev.t)}</span><span class="badge ${esc(ev.layer)}">${esc(ev.layer)}</span><span>${esc(ev.type === "frame" ? "unknown" : ev.type)}</span><span>${esc(ev.side || "")}</span><span>${esc(describe(ev))}${ev.data?.initial ? " <i class='muted'>(initial state)</i>" : ""}</span>`;
  const atBottom = f.scrollHeight - f.scrollTop - f.clientHeight < 40;
  f.appendChild(r); while (f.children.length > 400) f.removeChild(f.firstChild);
  if (atBottom) f.scrollTop = f.scrollHeight;
}

// ---------------------------------------------------------------- signals detected (simple summary)
function seenLabel(e) {
  const d = e.data || {};
  switch (e.type) {
    case "touch": return d.gesture ? ["Touch: " + d.gesture.replace("_", " "), e.side, d.code != null ? "code " + d.code : ""] : ["Touchpad lock " + (d.locked ? "on" : "off"), "", ""];
    case "wear": return ["Wear: " + d.state, e.side, ""];
    case "case": return ["Case: " + (d.event || "").replace(/_/g, " "), e.side || d.target || "", ""];
    case "anc": return ["Noise control: " + d.mode, "", ""];
    case "media_key": return ["Media key: " + d.key, "", ""];
    case "audio": return ["Audio: " + d.event, "", ""];
    default: return null;
  }
}
function renderSeen() {
  if (S.view !== "live") return;
  const rows = {};
  for (const e of S.events) {
    if (e.data?.initial) continue;
    const l = seenLabel(e); if (!l) continue;
    const k = l.join("|"), r = (rows[k] ||= { l, n: 0, t: 0 }); r.n++; r.t = e.t;
  }
  const list = Object.values(rows).sort((a, b) => b.t - a.t);
  document.querySelector("#tbl-seen tbody").innerHTML = list.map((r) => `<tr><td>${esc(r.l[0])}</td><td>${esc(r.l[1])}</td><td>${r.n}</td><td>${fmtT(r.t)}</td><td class="muted">${esc(r.l[2])}</td></tr>`).join("") ||
    '<tr><td colspan="5" class="muted">nothing yet: tap a bud, take one out, open the case…</td></tr>';
  const ids = new Map(); S.frames.filter((f) => f.data.dir === "rx" && !f.data.known).forEach((f) => ids.set(f.data.msg_id, (ids.get(f.data.msg_id) || 0) + 1));
  $("seen-unk").textContent = ids.size ? `Also seen: ${ids.size} kinds of undecoded telemetry messages (ids ${[...ids.keys()].sort((a, b) => a - b).join(", ")}). See Protocol (advanced).` : "";
}
setInterval(renderSeen, 800);

// ---------------------------------------------------------------- runner / action card
function setRunner(r) {
  S.runner = r; S.results = r.results || S.results;
  const st = r.state, cur = r.current;
  $("act-state").textContent = st === "awaiting_confirm" ? "needs confirmation" : st === "pause" ? "next up" : st;
  $("act-state").className = "pill " + (st === "armed" ? "ok" : st === "awaiting_confirm" ? "bad" : "");
  if (cur && st !== "idle") {
    $("act-title").textContent = cur.title; $("act-instr").textContent = cur.instruction;
  } else if (!cur || st === "idle") {
    $("act-title").textContent = "No experiment running";
    $("act-instr").innerHTML = r.last_result ? `Last: <b>${esc(r.last_result.id)}</b> → <span class="st ${r.last_result.status}">${r.last_result.status}</span>. Start another run.` : "Choose a category and press <b>Start guided run</b>.";
  }
  const w = $("act-warn"); w.hidden = !r.warning; w.textContent = r.warning || "";
  $("act-freeform").hidden = !(cur && cur.freeform && st === "awaiting_confirm");
  $("btn-confirm").hidden = st !== "awaiting_confirm";
  $("btn-confirm").textContent = cur?.risk === "audible" ? "I removed the buds — go" : cur?.freeform ? "Start window" : "Confirm & go";
  $("btn-extend").textContent = st === "pause" ? "+5 s pause" : "+ time";
  if (st === "armed") { const s = $("act-signal"); s.className = "signal muted"; s.textContent = "Waiting for signal…"; }
  $("btn-start").disabled = st === "armed" || st === "awaiting_confirm";
  if (S.view === "guided") renderExperiments();
}
function tickCountdown() {
  const r = S.runner, bar = $("cd-bar"), txt = $("cd-text");
  if (!r) return;
  if (r.state === "armed" && r.deadline) {
    const total = r.current.timeout_seconds, left = Math.max(0, r.deadline - now());
    bar.style.width = (left / total * 100) + "%"; txt.textContent = left.toFixed(1) + " s";
  } else if (r.state === "pause" && r.pause_until) {
    const left = Math.max(0, r.pause_until - now()); bar.style.width = "0"; txt.textContent = r.queue.length ? `next in ${left.toFixed(1)} s` : "done";
  } else { bar.style.width = "0"; txt.textContent = r.state === "awaiting_confirm" ? "waiting for you" : ""; }
}
setInterval(tickCountdown, 200);

function onSignal(d) {
  const ev = d.event; ingestMaybe(ev);
  const s = $("act-signal"); s.className = "signal hit"; s.textContent = `${fmtT(ev.t)} s · ${ev.type === "frame" ? "undecoded id " + ev.data.msg_id : ev.type} · ${describe(ev)}`;
  flash(); beep(880);
}
function ingestMaybe(ev) { /* events also arrive via the "event" message; nothing to add */ }
function onResult(res) {
  S.results[res.id] = res; beep(res.status === "VERIFIED" ? 1320 : 330, 0.2, res.status === "VERIFIED" ? "sine" : "triangle");
  const s = $("act-signal"); s.className = "signal " + (res.status === "VERIFIED" ? "hit" : "muted");
  s.innerHTML = `Result: <span class="st ${res.status}">${res.status}</span> ${res.matched.length ? "— " + esc(res.matched.map((m) => m.type + (m.detail ? ":" + m.detail : "")).join(", ")) : ""}`;
  if (S.view === "guided") renderExperiments();
}

$("btn-start").onclick = safe(async () => { beep(440, 0.05); const c = $("run-cat").value; await post("/api/run/start", c === "all" ? {} : { category: c }); });
$("btn-confirm").onclick = safe(() => post("/api/run/confirm", { text: $("freeform-text").value }));
$("btn-skip").onclick = safe(() => post("/api/run/skip"));
$("btn-retry").onclick = safe(() => post("/api/run/retry"));
$("btn-verify").onclick = safe(() => post("/api/run/verify"));
$("btn-extend").onclick = safe(() => post("/api/run/extend"));
$("btn-abort").onclick = safe(() => post("/api/run/abort"));
$("btn-note").onclick = safe(async () => { const t = $("note-text").value.trim(); if (!t) return; await post("/api/notes", { text: t }); $("note-text").value = ""; toast("note saved"); });

// ---------------------------------------------------------------- experiments view
async function loadAttempts() { S.allAttempts = await api("/api/results?all_sessions=true"); }
async function renderExperiments() {
  await loadAttempts().catch(() => {});
  const by = {}; S.catalog.forEach((e) => (by[e.category] ||= []).push(e));
  const stats = {}; S.allAttempts.forEach((a) => { const s = (stats[a.experiment_id] ||= { n: 0, v: 0 }); if (a.status !== "SKIPPED") s.n++; if (a.status === "VERIFIED") s.v++; });
  const box = $("exp-list"); box.innerHTML = "";
  for (const [cat, list] of Object.entries(by)) {
    const h = document.createElement("div"); h.className = "exp-cat";
    h.innerHTML = `${esc(cat)} <button data-cat="${esc(cat)}">Run all ${esc(cat)}</button>`; box.appendChild(h);
    h.querySelector("button").onclick = safe(() => post("/api/run/start", { category: cat }));
    for (const e of list) {
      const r = S.results[e.id], s = stats[e.id];
      const row = document.createElement("div"); row.className = "exp-row";
      row.innerHTML = `<div><b>${esc(e.title)}</b><br><span class="risk ${esc(e.risk)}">${esc(e.risk)}</span> <span class="muted small">${esc(e.id)} · ${e.timeout_seconds}s</span></div>
        <div class="small">${esc(e.instruction)}<div class="muted">expects: ${esc(e.expected_signals.length ? e.expected_signals.map((x) => (x.any_of ? "any of " + x.any_of.map(brief).join(" | ") : brief(x))).join(" + ") : "nothing (observation)")}</div>
          <div><input class="note-in" placeholder="note…" data-id="${esc(e.id)}" style="width:60%"> <button class="note-btn" data-id="${esc(e.id)}">Add note</button></div></div>
        <div>${r ? `<span class="st ${r.status}">${r.status}${r.manual ? " (manual)" : ""}</span>` : '<span class="st SKIPPED">not run</span>'}<div class="muted small">${s ? `${s.v} of ${s.n} attempts (all sessions)` : ""}</div></div>
        <div><button data-run="${esc(e.id)}">Run</button></div>`;
      box.appendChild(row);
    }
  }
  box.querySelectorAll("[data-run]").forEach((b) => (b.onclick = safe(() => post("/api/run/rerun", { id: b.dataset.run }))));
  box.querySelectorAll(".note-btn").forEach((b) => (b.onclick = safe(async () => {
    const i = box.querySelector(`.note-in[data-id="${b.dataset.id}"]`); if (!i.value.trim()) return;
    await post("/api/notes", { text: i.value, experiment_id: b.dataset.id }); i.value = ""; toast("note saved");
  })));
}
const brief = (m) => [m.layer && "L" + m.layer, m.type, m.side, m.data && Object.values(m.data).join("/")].filter(Boolean).join(" ");
$("btn-reload").onclick = safe(async () => { const r = await post("/api/catalog/reload"); S.catalog = await api("/api/catalog"); fillCats(); renderExperiments(); toast(`catalog reloaded (${r.count})`); });
function fillCats() {
  const cats = ["all", ...new Set(S.catalog.map((e) => e.category))], sel = $("run-cat"), cur = sel.value;
  sel.innerHTML = cats.map((c) => `<option value="${esc(c)}">${c === "all" ? "all experiments" : esc(c)}</option>`).join(""); if (cats.includes(cur)) sel.value = cur;
}

// ---------------------------------------------------------------- protocol view
let frameTimer = null;
function scheduleFrames() { if (frameTimer) return; frameTimer = setTimeout(() => { frameTimer = null; renderFrames(); }, 400); }
["f-dir", "f-layer", "f-id", "f-text", "f-unknown"].forEach((id) => $(id).addEventListener("input", renderFrames));
function renderFrames() {
  const dir = $("f-dir").value, layer = $("f-layer").value, id = $("f-id").value.trim(), txt = $("f-text").value.toLowerCase(), unk = $("f-unknown").checked;
  let rows = S.frames.filter((f) => (!dir || f.data.dir === dir) && (!layer || f.layer === layer) && (id === "" || String(f.data.msg_id) === id)
    && (!unk || !f.data.known) && (!txt || (f.raw_hex || "").includes(txt) || (f.data.name || "").toLowerCase().includes(txt)));
  $("f-count").textContent = `${rows.length} of ${S.frames.length} frames`;
  rows = rows.slice(-300).reverse();
  const tb = document.querySelector("#tbl-frames tbody");
  tb.innerHTML = rows.map((f) => `<tr><td>${fmtT(f.t)}</td><td>${esc(f.data.dir)}</td><td><span class="badge ${esc(f.layer)}">${esc(f.layer)}</span></td><td>${esc(f.data.msg_id)}</td>
    <td>${esc(f.data.name || (f.data.junk ? "junk: " + f.data.reason : ""))}${f.data.known ? "" : ' <i class="muted">undecoded</i>'}</td><td>${esc(f.data.size)}</td><td>${f.data.crc_ok === false ? "BAD" : "ok"}</td>
    <td class="hex">${esc(f.data.payload_hex ?? f.raw_hex ?? "")}</td><td>${f.data.fields ? `<button data-seq="${f.seq}">fields</button>` : ""}</td></tr>`).join("");
  tb.querySelectorAll("[data-seq]").forEach((b) => (b.onclick = () => { const f = S.frames.find((x) => x.seq == b.dataset.seq); $("discovery-out").textContent = JSON.stringify(f.data.fields, null, 2); $("discovery-out").scrollIntoView({ behavior: "smooth" }); }));
}
async function refreshProtocol() {
  renderFrames();
  const u = await api("/api/unknown");
  document.querySelector("#tbl-unknown tbody").innerHTML = u.map((r) => `<tr><td>${r.msg_id} <span class="muted">${esc(r.name)}</span></td><td>${r.count}</td>
    <td>${new Date(r.first_seen * 1000).toLocaleTimeString()}<br>${new Date(r.last_seen * 1000).toLocaleTimeString()}</td><td class="hex">${r.examples.map(esc).join("<br>")}</td>
    <td>${Object.entries(r.actions).map(([k, v]) => `${esc(k)} ×${v}`).join("<br>")}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">none yet</td></tr>';
  const f = await api("/api/msgfreq"); const top = f.slice(0, 16);
  chart("freq", { type: "bar", data: { labels: top.map((x) => `${x.dir} ${x.msg_id}`), datasets: [{ label: "count", data: top.map((x) => x.count), backgroundColor: css("--c1") }] },
    options: { ...baseOpts(), plugins: { legend: { display: false } } } });
}
$("btn-sdp").onclick = safe(async () => { $("discovery-out").textContent = JSON.stringify(await api("/api/sdp"), null, 2); });
$("btn-ble").onclick = safe(async () => { $("discovery-out").textContent = "scanning 10 s…"; $("discovery-out").textContent = JSON.stringify(await post("/api/discovery/ble?seconds=10"), null, 2); });

// ---------------------------------------------------------------- commands view
async function renderCommands() {
  const c = await api("/api/commands"); S.cmdList = c.commands; $("cmd-enable").checked = c.enabled;
  const box = $("cmd-cards"); box.innerHTML = "";
  for (const cmd of c.commands) {
    const el = document.createElement("div"); el.className = "card cmdcard";
    let fields = "";
    for (const [k, v] of Object.entries(cmd.args)) {
      if (Array.isArray(v)) fields += `<label>${esc(k)}</label><select data-arg="${esc(k)}">${v.map((o) => `<option>${esc(o)}</option>`).join("")}</select>`;
      else if (v === "bool") fields += `<label><input type="checkbox" data-arg="${esc(k)}" data-bool="1"> ${esc(k)}</label>`;
      else fields += `<label>${esc(k)} (${esc(v)})</label><input data-arg="${esc(k)}" value="1">`;
    }
    el.innerHTML = `<b>${esc(cmd.name)}</b> <span class="risk ${esc(cmd.risk)}">${esc(cmd.risk)}</span> <span class="muted small">msg ${cmd.msg_id}</span><div class="small muted">${esc(cmd.description)}</div>${fields}<div class="btnrow"><button class="${cmd.confirm ? "danger" : ""}">Send</button></div>`;
    el.querySelector("button").onclick = safe(async () => {
      const args = {};
      el.querySelectorAll("[data-arg]").forEach((i) => { args[i.dataset.arg] = i.dataset.bool ? i.checked : (i.tagName === "SELECT" ? (isNaN(i.value) ? i.value : Number(i.value)) : i.value); });
      if (cmd.confirm) { if (!(await modal(cmd.name, cmd.confirm))) return; }
      const r = await post("/api/commands/send", { name: cmd.name, args, confirm: !!cmd.confirm });
      toast(`${cmd.name}: ${r.status}${r.latency_ms != null ? " (" + r.latency_ms + " ms)" : ""}`);
    });
    box.appendChild(el);
  }
  renderCmdLog();
}
function renderCmdLog() {
  const rows = S.events.filter((e) => e.type === "command_result").slice(-100).reverse();
  document.querySelector("#tbl-cmd tbody").innerHTML = rows.map((e) => `<tr><td>${fmtT(e.t)}</td><td>${esc(e.data.name)}${e.data.undo ? " (undo)" : ""}</td><td class="hex">${esc(JSON.stringify(e.data.args))}</td>
    <td><span class="st ${e.data.status === "acked" ? "VERIFIED" : e.data.status === "rejected" ? "NOT_OBSERVED" : "PARTIAL"}">${esc(e.data.status)}</span></td><td>${e.data.latency_ms ?? "–"}</td></tr>`).join("");
}
$("cmd-enable").onchange = safe(async (e) => { await post("/api/commands/enable", { enabled: e.target.checked }); });
function modal(title, text) {
  return new Promise((res) => {
    $("modal-title").textContent = title; $("modal-text").textContent = text; $("modal").hidden = false;
    const done = (v) => { $("modal").hidden = true; res(v); };
    $("modal-ok").onclick = () => done(true); $("modal-cancel").onclick = () => done(false);
  });
}

// ---------------------------------------------------------------- mic view
const MIC = { rows: [] };
async function loadMicDevices() {
  const r = await api("/api/mic/devices"), sel = $("mic-dev"), cur = sel.value;
  sel.innerHTML = r.devices.map((d) => `<option value="${d.index}">${esc(d.name)} (${d.rate} Hz)${d.is_buds ? "  ← buds" : ""}</option>`).join("");
  const buds = r.devices.find((d) => d.is_buds);
  sel.value = cur && r.devices.some((d) => String(d.index) === cur) ? cur : String((buds || r.devices.find((d) => d.is_default) || r.devices[0] || {}).index);
  $("mic-msg").textContent = r.error || (buds ? "" : "Buds not listed as an input yet; using another mic would not measure the buds.");
}
async function micRecord(label, secs) {
  const r = await post("/api/mic/record", { seconds: secs, label, device: Number($("mic-dev").value) });
  MIC.rows.unshift(r); renderMic(); return r;
}
function renderMic() {
  document.querySelector("#tbl-mic tbody").innerHTML = MIC.rows.map((r) => `<tr><td>${esc(r.label)}</td><td>${esc(r.device)}</td><td>${r.sample_rate}</td><td>${r.bandwidth_hz ?? "–"} Hz</td>
    <td>${r.speech_rms_dbfs ?? "–"} dBFS</td><td>${r.noise_floor_dbfs} dBFS</td><td>${r.snr_db ?? "–"} dB</td><td>${r.peak_dbfs} dBFS</td><td>${esc(r.verdict)}</td>
    <td><audio controls preload="none" src="/api/mic/file/${encodeURIComponent(r.file)}" style="height:28px"></audio></td></tr>`).join("");
}
$("mic-refresh").onclick = safe(loadMicDevices);
$("mic-rec").onclick = safe(async () => {
  const secs = Number($("mic-secs").value) || 5; $("mic-prompt").textContent = `Recording ${secs} s… speak now`;
  try { await micRecord($("mic-label").value || "rec", secs); } finally { $("mic-prompt").textContent = ""; }
});
$("mic-level").onclick = safe(async () => {
  const steps = [["silence", "Stay quiet (room noise baseline)"], ["whisper", 'Whisper: "what is on my calendar today"'], ["normal", 'Normal voice: "what is on my calendar today"'], ["loud", 'Loud voice: "what is on my calendar today"']];
  try {
    for (const [label, text] of steps) {
      for (let i = 3; i > 0; i--) { $("mic-prompt").textContent = `${text}, starting in ${i}…`; await new Promise((r) => setTimeout(r, 1000)); }
      $("mic-prompt").textContent = `NOW: ${text} (5 s)`; beep(880, 0.1);
      await micRecord("level-" + label, 5);
    }
    $("mic-prompt").textContent = "Level test done. Compare SNR across whisper / normal / loud below.";
  } catch (e) { $("mic-prompt").textContent = ""; throw e; }
});

// ---------------------------------------------------------------- report view
async function refreshReport() {
  const sim = $("rep-sim").checked ? "true" : "false";
  const m = await api("/api/report?simulated=" + (S.status?.mode !== "hardware" ? "true" : sim));
  $("rep-obs").innerHTML = (m.includes_simulated ? '<div class="warn">This matrix includes SIMULATED sessions; it is not evidence about the real buds.</div>' : "") +
    Object.entries(m.observations || {}).map(([k, v]) => `<div><b>${esc(k)}</b>: ${esc(typeof v === "object" ? JSON.stringify(v) : v)}</div>`).join("");
  document.querySelector("#tbl-report tbody").innerHTML = m.capabilities.map((r) => `<tr><td>${esc(r.capability)}</td><td>${esc(r.category)}</td><td>${esc(r.layer)}</td><td>${esc(r.how_to_trigger)}</td><td class="hex">${esc(r.signal_seen)}</td><td>${esc(r.reliability)}</td><td><span class="st ${esc(r.status)}">${esc(r.status)}${r.manual ? " (manual)" : ""}</span></td><td>${esc(r.notes)}</td></tr>`).join("");
  document.querySelector("#tbl-report-cmd tbody").innerHTML = m.commands.map((c) => `<tr><td>${esc(c.command)}</td><td>${c.attempts}</td><td>${c.acked}</td><td>${c.rejected}</td><td>${c.no_response}</td><td>${c.latency_ms_median ?? "–"}</td><td>${c.latency_ms_max ?? "–"}</td></tr>`).join("") || '<tr><td colspan="7" class="muted">no commands sent</td></tr>';
}
$("btn-rep-refresh").onclick = safe(refreshReport);
$("rep-sim").onchange = safe(refreshReport);
$("btn-export").onclick = safe(async () => { const p = await post("/api/export" + ($("rep-sim").checked ? "?simulated=true" : "")); $("export-out").textContent = `Wrote ${p.json}, ${p.md} and ${p.findings}`; toast("exported"); });

// ---------------------------------------------------------------- charts
const CAT = { touch: 0, wear: 1, case: 2, anc: 3, audio: 4, battery: 5, unknown: 6 };
const LANES = ["touch", "wear", "case", "anc", "audio", "battery", "unknown"];
function baseOpts() {
  const grid = css("--line"), tick = css("--muted");
  return { responsive: true, maintainAspectRatio: false, animation: false, color: tick,
    scales: { x: { type: "linear", ticks: { color: tick }, grid: { color: grid }, title: { display: true, text: "seconds since session start", color: tick } },
      y: { ticks: { color: tick }, grid: { color: grid } } }, plugins: { legend: { labels: { color: tick } } } };
}
function chart(key, cfg) {
  const ex = S.charts[key];
  if (ex) { ex.data = cfg.data; ex.options = cfg.options; ex.update("none"); return ex; }
  S.charts[key] = new Chart($("ch-" + key), { ...cfg, plugins: cfg.plugins || [] }); return S.charts[key];
}
const markerPlugin = { id: "markers", afterDatasetsDraw(c) {
  const { ctx, chartArea: a, scales: { x } } = c; if (!a) return;
  ctx.save(); ctx.font = "10px sans-serif";
  for (const m of c.options.markers || []) {
    const px = x.getPixelForValue(m.t); if (px < a.left || px > a.right) continue;
    ctx.strokeStyle = m.color; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
    ctx.fillStyle = m.color; ctx.fillText(m.label, px + 2, a.top + 10 + (m.row % 3) * 11);
  } ctx.restore(); } };

function drawMetrics() {
  if (S.view !== "metrics") return;
  const ev = S.events, T = Math.max(10, ...(ev.length ? [ev[ev.length - 1].t] : [0]), ...(S.frames.length ? [S.frames[S.frames.length - 1].t] : [0]));
  // counters
  $("c-ids").textContent = new Set(S.frames.filter((f) => f.data.dir === "rx" && f.data.msg_id >= 0).map((f) => f.data.msg_id)).size;
  if (S.status) { $("c-events").textContent = S.status.counters.events; $("c-rx").textContent = S.status.counters.frames_rx; $("c-tx").textContent = S.status.counters.frames_tx; }
  // battery
  const bat = ev.filter((e) => e.type === "battery"), pts = (k) => bat.map((e) => ({ x: e.t, y: e.data[k] }));
  const marks = ev.filter((e) => (e.type === "wear" || e.type === "case") && !e.data.initial).map((e, i) => ({ t: e.t, row: i,
    color: e.type === "wear" ? css("--c2") : css("--c4"), label: e.type === "wear" ? `${e.side} ${e.data.state}` : (e.data.event || "").replace("_", " ") }));
  const bo = baseOpts(); bo.markers = marks; bo.scales.y.min = 0; bo.scales.y.max = 100; bo.scales.y.title = { display: true, text: "%", color: css("--muted") };
  chart("battery", { type: "line", plugins: [markerPlugin], data: { datasets: [
    { label: "Left", data: pts("left"), borderColor: css("--c1"), pointRadius: 0, tension: 0, parsing: false },
    { label: "Right", data: pts("right"), borderColor: css("--c2"), pointRadius: 0, parsing: false },
    { label: "Case", data: pts("case"), borderColor: css("--c3"), pointRadius: 0, parsing: false }] }, options: bo });
  // swimlane
  const lane = (e) => e.type === "media_key" ? "touch" : e.type === "command_result" ? null : CAT[e.type] !== undefined ? e.type : null;
  const swim = ev.map((e) => [lane(e), e]).filter(([l]) => l);
  const unk = S.frames.filter((f) => !f.data.known && f.data.dir === "rx").map((f) => ({ x: f.t, y: CAT.unknown, e: f }));
  const colors = [css("--c1"), css("--c2"), css("--c3"), css("--c4"), css("--c5"), css("--c7"), css("--c6")];
  const so = baseOpts(); so.scales.y = { min: -0.5, max: LANES.length - 0.5, reverse: true, ticks: { stepSize: 1, callback: (v) => LANES[v] ?? "", color: css("--muted") }, grid: { color: css("--line") } };
  so.plugins.tooltip = { callbacks: { label: (c) => `${fmtT(c.raw.x)} s  ${c.raw.label || ""}` } }; so.plugins.legend = { display: false };
  chart("swim", { type: "scatter", data: { datasets: LANES.map((l, i) => ({ label: l, backgroundColor: colors[i], borderColor: colors[i], pointStyle: "rectRot", pointRadius: l === "battery" ? 2 : 5,
    data: l === "unknown" ? unk.map((u) => ({ x: u.x, y: u.y, label: "id " + u.e.data.msg_id })) : swim.filter(([x]) => x === l).map(([, e]) => ({ x: e.t, y: CAT[l], label: describe(e) })) })) }, options: so });
  // wear strip
  drawWear(T);
  // touch counters
  drawTouchCounts();
  // message rate
  const bins = Math.min(120, Math.ceil(T)), start = Math.max(0, T - bins), rx = new Array(bins + 1).fill(0), tx = new Array(bins + 1).fill(0);
  S.frames.forEach((f) => { const i = Math.floor(f.t - start); if (i >= 0 && i <= bins) (f.data.dir === "tx" ? tx : rx)[i]++; });
  const ro = baseOpts(); ro.scales.x.min = start; ro.scales.x.max = start + bins;
  chart("rate", { type: "line", data: { datasets: [{ label: "rx/s", data: rx.map((y, i) => ({ x: start + i, y })), borderColor: css("--c1"), stepped: true, pointRadius: 0, parsing: false },
    { label: "tx/s", data: tx.map((y, i) => ({ x: start + i, y })), borderColor: css("--c2"), stepped: true, pointRadius: 0, parsing: false }] }, options: ro });
  // by id (5 s bins)
  const b5 = 5, nb = Math.ceil(T / b5) + 1, byId = {}; S.frames.filter((f) => f.data.dir === "rx").forEach((f) => { const i = Math.floor(f.t / b5); (byId[f.data.msg_id] ||= new Array(nb).fill(0))[i]++; });
  const ids = Object.entries(byId).sort((a, b) => b[1].reduce((x, y) => x + y, 0) - a[1].reduce((x, y) => x + y, 0)).slice(0, 8);
  const io = baseOpts(); io.scales.x = { stacked: true, ticks: { color: css("--muted"), callback: (v, i) => i * b5 }, grid: { color: css("--line") }, title: { display: true, text: "seconds", color: css("--muted") } }; io.scales.y.stacked = true;
  chart("ids", { type: "bar", data: { labels: Array.from({ length: nb }, (_, i) => i), datasets: ids.map(([id, arr], i) => ({ label: "id " + id, data: arr, backgroundColor: colors[i % colors.length] })) }, options: io });
  // latency
  const lat = ev.filter((e) => e.type === "command_result" && e.data.latency_ms != null), names = [...new Set(lat.map((e) => e.data.name))];
  const lo = baseOpts(); lo.scales.y.title = { display: true, text: "ms", color: css("--muted") };
  chart("lat", { type: "scatter", data: { datasets: names.map((n, i) => ({ label: n, backgroundColor: colors[i % colors.length], data: lat.filter((e) => e.data.name === n).map((e) => ({ x: e.t, y: e.data.latency_ms })) })) }, options: lo });
  const vals = lat.map((e) => e.data.latency_ms), max = Math.max(50, ...vals), step = Math.ceil(max / 10 / 10) * 10 || 10, hb = new Array(11).fill(0);
  vals.forEach((v) => hb[Math.min(10, Math.floor(v / step))]++);
  const ho = baseOpts(); ho.scales.x = { ticks: { color: css("--muted") }, grid: { color: css("--line") }, title: { display: true, text: "ms", color: css("--muted") } }; ho.plugins.legend = { display: false };
  chart("lat-h", { type: "bar", data: { labels: hb.map((_, i) => `${i * step}–${(i + 1) * step}`), datasets: [{ data: hb, backgroundColor: css("--c3") }] }, options: ho });
}
function drawWear(T) {
  const cv = $("ch-wear"), dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = 90;
  cv.width = w * dpr; cv.height = h * dpr; const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
  const col = { 1: css("--ok"), 2: css("--line"), 3: css("--info"), 0: css("--bad") };
  ["L", "R"].forEach((side, row) => {
    const evs = S.events.filter((e) => e.type === "wear" && e.side === side), y = 12 + row * 34;
    ctx.fillStyle = css("--muted"); ctx.font = "11px sans-serif"; ctx.fillText(side, 0, y + 16);
    let prev = null;
    const seg = (a, b, p) => { ctx.fillStyle = col[p] ?? css("--line"); ctx.fillRect(16 + a / T * (w - 20), y, Math.max(1, (b - a) / T * (w - 20)), 24); };
    evs.forEach((e) => { if (prev) seg(prev.t, e.t, prev.data.placement); prev = e; });
    if (prev) seg(prev.t, T, prev.data.placement);
  });
}
function drawTouchCounts() {
  const counts = {};
  S.events.filter((e) => e.type === "media_key" || (e.type === "touch" && e.data.event !== "touchpad_lock")).forEach((e) => {
    const k = e.type === "media_key" ? "media:" + e.data.key : "touch:" + (e.data.gesture || e.data.event || "?"); const s = e.side || "?"; ((counts[k] ||= {})[s] = (counts[k][s] || 0) + 1);
  });
  const rows = Object.entries(counts); const max = Math.max(1, ...rows.flatMap(([, v]) => Object.values(v)));
  $("touch-counts").innerHTML = rows.length ? `<table><thead><tr><th>gesture / key</th><th>L</th><th>R</th><th>side unknown</th></tr></thead><tbody>${rows.map(([k, v]) => `<tr><td>${esc(k)}</td>${["L", "R", "?"].map((s) => `<td style="background:color-mix(in srgb,var(--accent) ${((v[s] || 0) / max) * 60}%,transparent)">${v[s] || 0}</td>`).join("")}</tr>`).join("")}</tbody></table>
    <div class="muted small">AVRCP media keys carry no left/right information.</div>` : '<span class="muted">no touch events yet</span>';
}
setInterval(drawMetrics, 1000);

// ---------------------------------------------------------------- boot
(async function boot() {
  try {
    S.catalog = await api("/api/catalog"); fillCats();
    setStatus(await api("/api/status")); setRunner(await api("/api/runner"));
    await loadHistory();
  } catch (e) { toast("failed to load: " + e.message); }
  connectWS();
})();
