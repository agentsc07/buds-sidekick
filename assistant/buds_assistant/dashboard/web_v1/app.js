/* Buds Sidekick dashboard. Plain JS; talks to the local FastAPI backend only. */
"use strict";
const $ = (id) => document.getElementById(id);
const S = { state: null, people: [], live: [], clusters: [] };
const api = async (p, o = {}) => {
  const r = await fetch(p, { headers: { "Content-Type": "application/json" }, ...o, body: o.body ? JSON.stringify(o.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
};
const post = (p, body = {}) => api(p, { method: "POST", body });
const safe = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message); } };
function toast(m, ms = 3500) { const t = $("toast"); t.textContent = m; t.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), ms); }
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else if (v !== false && v != null) e.setAttribute(k, v); }
  for (const k of kids.flat()) e.append(k instanceof Node ? k : document.createTextNode(k ?? ""));
  return e;
}
const fmtT = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const fmtD = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "–");
const colorOf = (name) => { const p = S.people.find((x) => x.name === name); return p ? p.color : null; };

// ---------------------------------------------------------------- navigation
document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
function show(v) {
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".view").forEach((s) => s.classList.toggle("active", s.id === "view-" + v));
  ({ people: loadPeople, conversations: loadConvs, memory: loadMemory, settings: loadSettings, privacy: loadPrivacy })[v]?.();
}

// ---------------------------------------------------------------- state
async function refresh() {
  S.state = await api("/api/state");
  const s = S.state;
  $("pill-mode").textContent = s.mode; $("pill-mode").className = "pill " + (s.mode === "private" ? "bad" : s.mode === "autopilot" ? "warn" : s.mode === "standby" ? "" : "ok");
  $("pill-place").textContent = s.placement === "remote" ? "remote (buds out)" : "in ear";
  $("pill-link").textContent = s.simulate ? "simulated buds" : s.link ? "buds linked" : "no buds"; $("pill-link").className = "pill " + (s.simulate ? "warn" : s.link ? "ok" : "bad");
  $("pill-llm").textContent = s.llm ? "language model ready" : "language model offline"; $("pill-llm").className = "pill " + (s.llm ? "ok" : "bad");
  const b = s.battery; $("pill-bat").textContent = b ? `L ${b.left}% R ${b.right}% case ${b.case}%` : "battery –";
  document.querySelectorAll("#mode-btns button").forEach((x) => x.classList.toggle("active", x.dataset.mode === s.mode));
  $("place-sel").value = s.config.placement;
  $("sim-wear").hidden = !s.simulate; $("sim-demo").hidden = !s.simulate;
  $("route-line").textContent = `Capture: ${s.placement === "remote" ? "Mac microphone" : "buds microphone"} · Audio out: ${s.route === "remote" ? "Mac speakers" : "buds / default output"}`;
  const cap = s.config.ring_seconds; $("ring-bar").style.width = Math.min(100, (s.ring_seconds / cap) * 100) + "%"; $("ring-text").textContent = `replay buffer ${s.ring_seconds}s of ${cap}s (RAM only)`;
  $("mode-help").textContent = { standby: "Mic closed. Gestures and typed questions work.", listen: "Listening: transcribing, identifying speakers, replay ready.", autopilot: "Listen + whispered hints (rate limited).", interpreter: "Translating live (Mac mic by default).", private: "Mic closed, buffer wiped, nothing stored." }[s.mode];
  $("live-info").textContent = s.conversation_id ? `conversation #${s.conversation_id}` : "";
  S.clusters = s.clusters || [];
  renderGestures();
}
function renderGestures() {
  const s = S.state, prof = s.profiles[s.placement] || [];
  $("gesture-profile").textContent = `(${s.placement} profile)`;
  const tb = document.querySelector("#tbl-gestures tbody"); tb.replaceChildren(...prof.map((g) => h("tr", {}, h("td", {}, g.gesture.replace("hold", g.mode === "toggle" ? "hold (toggle)" : "hold")), h("td", {}, g.action.replace(/_/g, " ")))));
  const pad = $("gpad"); if (pad.dataset.built) return; pad.dataset.built = 1;
  for (const side of ["L", "R"]) {
    pad.append(h("b", {}, side === "L" ? "Left bud" : "Right bud"));
    for (const g of ["single", "double", "triple", "hold"]) pad.append(h("button", { onclick: safe(() => post("/api/gesture", { token: g === "hold" ? `${side}:hold_start` : `${side}:${g}` })) }, g));
  }
}

// ---------------------------------------------------------------- live feed
function utt(e) {
  const name = e.speaker, col = colorOf(name) || e.color;
  const chip = e.person_id ? h("span", { class: "chip click", style: `background:${col || "#2f6fed"}`, title: "Not them? click to correct", onclick: () => correctModal(e) }, name)
    : h("span", { class: "chip unk click", title: "Unknown voice: click to name", onclick: () => nameModal(e.cluster) }, name + " ?");
  return h("div", { class: "utt flash", "data-seg": e.seg_id ?? "", "data-t0": e.t0 }, h("span", { class: "small muted" }, fmtT(e.t0)), chip,
    h("span", {}, e.text, e.lang !== "en" ? h("span", { class: "badge" }, e.lang) : "", e.experimental ? h("span", { class: "badge" }, "experimental") : ""));
}
function addEvent(ev) {
  const d = ev.data;
  switch (ev.type) {
    case "segment": { const t = $("transcript"), near = t.scrollHeight - t.scrollTop - t.clientHeight < 60; t.append(utt(d)); if (near) t.scrollTop = t.scrollHeight; break; }
    case "hint": $("hints").prepend(h("div", { class: "hint", "data-id": d.id }, h("b", {}, d.trigger + ": "), d.text, " ",
      h("button", { onclick: safe(() => post(`/api/hints/${d.id}/feedback`, { useful: true })) }, "👍"), " ", h("button", { onclick: safe(() => post(`/api/hints/${d.id}/feedback`, { useful: false })) }, "👎"))); break;
    case "reply": $("replies").prepend(h("div", {}, h("div", { class: "small muted" }, (d.query ? "“" + d.query + "”  " : "") + `${d.intent}${d.latency != null ? " · " + d.latency + "s" : ""}${d.lang === "te" ? " · Telugu" : ""}`), d.text)); break;
    case "translation": { const rows = [...$("transcript").children].reverse(); const row = rows.find((r) => r.dataset.t0 == d.t0) || rows[0]; if (row && d.ok) row.lastChild.append(h("div", { class: "small", style: "color:var(--accent)" }, "→ " + d.translated)); else if (!d.ok) toast("Translation failed: " + d.error); break; }
    case "heard": if (d.text) toast("Heard: " + d.text); break;
    case "listening": toast(d.dictation ? "Dictating… toggle again to finish" : "Listening…", 2500); break;
    case "mode": case "conversation_started": case "capture": case "battery": case "cluster_named": case "enrolled": case "forgotten": refresh().catch(() => {}); if (ev.type === "conversation_started") $("transcript").replaceChildren(); break;
    case "bookmark": toast("Marked " + (d.speaker || "")); break;
    case "error": toast("Error: " + (d.error || d.where)); break;
    case "audio_out": if (d.kind === "dropped") toast("(dropped: " + d.reason + ")"); break;
  }
}
function connectWS() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.kind === "hello") d.events.forEach(addEvent); else addEvent(d); };
  ws.onclose = () => setTimeout(connectWS, 1500);
}

// ---------------------------------------------------------------- controls
document.querySelectorAll("#mode-btns button").forEach((b) => (b.onclick = safe(async () => { await post("/api/mode", { mode: b.dataset.mode }); refresh(); })));
$("place-sel").onchange = safe(async (e) => { await post("/api/placement", { placement: e.target.value }); refresh(); });
const wear = safe(async () => { await post("/api/wear", { left: $("wear-l").checked, right: $("wear-r").checked }); refresh(); });
$("wear-l").onchange = wear; $("wear-r").onchange = wear;
$("b-replay").onclick = safe(() => post("/api/replay")); $("b-replay-fast").onclick = safe(() => post("/api/replay", { speed: 1.25 }));
$("b-mark").onclick = safe(() => post("/api/mark")); $("b-stop").onclick = safe(() => post("/api/action", { action: "stop" }));
$("b-who").onclick = safe(() => post("/api/ask", { text: "who is talking" })); $("b-catch").onclick = safe(() => post("/api/ask", { text: "catch me up" }));
$("ask-go").onclick = safe(async () => { const t = $("ask-text").value.trim(); if (!t) return; $("ask-text").value = ""; await post("/api/ask", { text: t }); });
$("ask-text").onkeydown = (e) => { if (e.key === "Enter") $("ask-go").click(); };
$("b-demo").onclick = safe(async () => { toast("Rendering demo conversation…"); const r = await post("/api/simulate/conversation", { realtime: true }); toast(`Playing ${r.utterances} utterances (${r.seconds}s)`); });

function modal(title, text, fields, okLabel = "OK") {
  return new Promise((res) => {
    $("m-title").textContent = title; $("m-text").textContent = text; $("m-ok").textContent = okLabel; const box = $("m-fields"); box.replaceChildren();
    const inputs = fields.map((f) => { const i = f.options ? h("select", {}, f.options.map((o) => h("option", { value: o.value }, o.label))) : h("input", { placeholder: f.label, value: f.value || "" }); box.append(h("label", { class: "small muted" }, f.label), i); return i; });
    $("modal").hidden = false; inputs[0]?.focus();
    const done = (v) => { $("modal").hidden = true; res(v); };
    $("m-ok").onclick = () => done(inputs.map((i) => i.value)); $("m-cancel").onclick = () => done(null);
  });
}
const nameModal = safe(async (label) => {
  const v = await modal(`Who is ${label}?`, "Enrol this voice. You need their agreement; the note is kept in the audit log.", [{ label: "Name" }, { label: "Consent note", value: "verbal consent" }], "Save");
  if (v && v[0]) { await post(`/api/clusters/${encodeURIComponent(label)}/name`, { name: v[0], consent: v[1] }); toast("Saved " + v[0]); }
});
const correctModal = safe(async (e) => {
  if (e.seg_id == null) return toast("This line is not stored, nothing to correct.");
  await loadPeople();
  const v = await modal("Not " + e.speaker + "?", "Pick who it really was. The voice model learns from the correction.", [{ label: "Actually", options: S.people.map((p) => ({ value: p.id, label: p.name })) }], "Correct");
  if (v) { await post(`/api/segments/${e.seg_id}/correct`, { person_id: Number(v[0]) }); toast("Corrected"); }
});

// ---------------------------------------------------------------- people
async function loadPeople() {
  S.people = await api("/api/people");
  const tb = document.querySelector("#tbl-people tbody");
  tb.replaceChildren(...S.people.map((p) => h("tr", {}, h("td", {}, h("span", { class: "dot", style: `background:${p.color}` })), h("td", {}, p.name), h("td", {}, p.samples), h("td", {}, p.segments), h("td", {}, fmtD(p.last_seen)),
    h("td", {}, h("select", { onchange: safe((e) => post(`/api/people/${p.id}/policy`, { policy: e.target.value, retention_days: p.retention_days })) }, ["transcript", "audio", "none"].map((o) => h("option", { value: o, selected: o === p.policy }, o)))),
    h("td", {}, h("input", { type: "number", value: p.retention_days, style: "width:70px", onchange: safe((e) => post(`/api/people/${p.id}/policy`, { policy: p.policy, retention_days: Number(e.target.value) })) })),
    h("td", {}, h("button", { class: "danger", onclick: safe(async () => { if (confirm(`Forget ${p.name}? This deletes their voiceprint, transcripts, audio and facts. It cannot be undone.`)) { const c = await post(`/api/people/${p.id}/forget`); toast("Deleted: " + Object.entries(c).map(([k, v]) => `${v} ${k}`).join(", ")); loadPeople(); } }) }, "Forget")))));
}
$("en-go").onclick = safe(async () => { const m = $("en-msg"); m.textContent = "Recording… speak now"; try { const r = await post("/api/people/enroll", { name: $("en-name").value, consent: $("en-consent").value, seconds: Number($("en-secs").value) }); m.textContent = `Enrolled ${r.name} (${r.seconds}s). Record again to add samples.` + (r.similar.length ? ` WARNING: sounds similar to ${r.similar.map((x) => x.name + " (" + x.score + ")").join(", ")}; they may be confused. Add more samples or raise the speaker threshold.` : ""); loadPeople(); } catch (e) { m.textContent = e.message; } });
$("en-demo").onclick = safe(async () => { await post("/api/people/demo"); toast("Demo voices added"); loadPeople(); });

// ---------------------------------------------------------------- conversations
let curConv = null;
async function loadConvs() {
  const cs = await api("/api/conversations");
  $("conv-list").replaceChildren(...cs.map((c) => h("div", { onclick: safe(() => openConv(c.id)), style: "cursor:pointer" }, h("b", {}, `#${c.id} ${c.mode}`), h("div", { class: "small muted" }, `${fmtD(c.start)} · ${c.segments} lines · ${c.placement}`))));
}
const openConv = safe(async (id) => {
  curConv = id; const d = await api("/api/conversations/" + id);
  S.people = await api("/api/people");
  $("conv-detail").replaceChildren(...d.segments.map((s) => h("div", { class: "utt" }, h("span", { class: "small muted" }, fmtT(s.t0)), h("span", { class: "chip", style: `background:${s.color || "#8a8f98"}` }, s.speaker || s.cluster || "?"), h("span", {}, s.text))),
    ...d.bookmarks.map((b) => h("div", { class: "small muted" }, "★ bookmark " + fmtT(b.ts) + (b.note ? " " + b.note : ""))));
});
$("conv-extract").onclick = safe(async () => { if (!curConv) return; const r = await post(`/api/conversations/${curConv}/extract`); toast(`${r.facts} facts extracted`); });

// ---------------------------------------------------------------- memory
async function loadMemory() {
  S.people = await api("/api/people");
  for (const id of ["mem-person", "dos-person"]) { const sel = $(id), cur = sel.value; sel.replaceChildren(...(id === "mem-person" ? [h("option", { value: "" }, "anyone")] : []), ...S.people.map((p) => h("option", { value: p.id }, p.name))); sel.value = cur; }
  const cs = await api("/api/commitments");
  $("commits").replaceChildren(...(cs.length ? cs.map((c) => h("div", {}, h("b", {}, (c.person || "?") + ": "), c.text, c.due ? ` (by ${c.due})` : "", " ", h("button", { onclick: safe(async () => { await post(`/api/facts/${c.id}/status`, { status: "done" }); loadMemory(); }) }, "done"))) : [h("div", { class: "muted" }, "none yet. Commitments are extracted when a conversation ends.")]));
}
$("mem-go").onclick = safe(async () => {
  const q = $("mem-q").value.trim(); if (!q) return; const pid = $("mem-person").value;
  const r = await api(`/api/memory/search?q=${encodeURIComponent(q)}${pid ? "&person_id=" + pid : ""}`);
  $("mem-results").replaceChildren(...(r.length ? r.map((x) => h("div", {}, h("span", { class: "chip", style: `background:${x.color || "#8a8f98"}` }, x.speaker), " ", x.text, h("span", { class: "small muted" }, `  ${fmtD(x.t)} · match ${x.score}`))) : [h("div", { class: "muted" }, "nothing found")]));
});
$("dos-go").onclick = safe(async () => {
  const id = $("dos-person").value; if (!id) return; const d = await api(`/api/people/${id}/dossier`);
  $("dossier").replaceChildren(h("div", {}, h("b", {}, d.person.name), ` · ${d.segments} things said · last seen ${fmtD(d.last_seen)}`), h("div", {}, "Topics: " + (d.topics.join(", ") || "–")),
    h("div", {}, "Facts: ", d.facts.length ? d.facts.map((f) => f.kind + ": " + f.text).join("; ") : "–"), h("div", { class: "muted" }, "Recent: " + d.recent.join(" / ")));
});

// ---------------------------------------------------------------- translate
document.querySelectorAll(".tr-go").forEach((b) => (b.onclick = safe(async () => {
  const r = await post("/api/translate", { text: $("tr-in").value, dst: b.dataset.dst, speak: $("tr-speak").checked });
  $("tr-out").value = r.ok ? r.text : ""; $("tr-meta").textContent = r.ok ? `(${r.src} → ${r.dst})` : "failed: " + r.error; if (!r.ok) toast(r.error);
})));
$("tr-last").onclick = safe(async () => { const l = await api("/api/live"); const e = [...l].reverse().find((x) => !x.is_self); if (e) $("tr-in").value = e.text; else toast("Nothing heard yet"); });

// ---------------------------------------------------------------- settings / privacy
async function loadSettings() {
  const s = await api("/api/settings"), f = $("settings-form"); f.replaceChildren();
  for (const [k, v] of Object.entries(s)) {
    const inp = typeof v === "boolean" ? h("select", { "data-k": k }, h("option", { value: "true", selected: v }, "on"), h("option", { value: "false", selected: !v }, "off")) : k === "placement" ? h("select", { "data-k": k }, ["auto", "ear", "remote"].map((o) => h("option", { value: o, selected: o === v }, o))) : h("input", { "data-k": k, value: v, type: typeof v === "number" ? "number" : "text", step: "any" });
    f.append(h("div", {}, h("label", {}, k.replace(/_/g, " ")), inp));
  }
}
$("set-save").onclick = safe(async () => {
  const body = {}; document.querySelectorAll("#settings-form [data-k]").forEach((i) => { const v = i.value; body[i.dataset.k] = v === "true" ? true : v === "false" ? false : i.type === "number" ? Number(v) : v; });
  await post("/api/settings", body); $("set-msg").textContent = "saved"; refresh();
});
async function loadPrivacy() {
  const a = await api("/api/audit"), hs = await api("/api/hints");
  document.querySelector("#tbl-audit tbody").replaceChildren(...a.map((x) => h("tr", {}, h("td", {}, fmtD(x.ts)), h("td", {}, x.kind), h("td", { class: "small" }, JSON.stringify(x.detail)))));
  document.querySelector("#tbl-hints tbody").replaceChildren(...hs.map((x) => h("tr", {}, h("td", {}, fmtD(x.ts)), h("td", {}, x.trigger), h("td", {}, x.text), h("td", {}, x.feedback === 1 ? "👍" : x.feedback === -1 ? "👎" : ""))));
}

(async function boot() { try { await loadPeople(); await refresh(); } catch (e) { toast("failed to load: " + e.message); } connectWS(); setInterval(() => refresh().catch(() => {}), 4000); })();
