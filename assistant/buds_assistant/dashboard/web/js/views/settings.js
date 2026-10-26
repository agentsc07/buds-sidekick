import { html, useState, useEffect } from "../../vendor/htm-preact-standalone.module.js";
import { useStore, toast } from "../store.js";
import { api } from "../api.js";
import { Button, Segmented, Toggle, Dialog, Icon, when } from "../components/ui.js";

const LEVELS = [{ value: "quiet", label: "Quiet" }, { value: "balanced", label: "Helpful" }, { value: "proactive", label: "Proactive" }];
const LEVEL_HELP = { quiet: "I only note your promises and answer questions I'm sure about.", balanced: "I also remind you, tell you who is speaking, and check your calendar when a time comes up.",
  proactive: "Everything in Helpful, with shorter pauses, and I'll brief you when a name comes up." };
const CATS = [["capture", "Note my promises and add them to my to-dos"], ["calendar", "Tell me if I'm free when a time comes up"], ["meeting", "Warn me before meetings"], ["reminder", "Speak my reminders"], ["question", "Answer questions from memory and my calendar"], ["identity", "Tell me who is speaking"], ["commitment", "Remind me of promises"], ["mention", "Brief me when a name comes up"]];

const Row = ({ label, help, children }) => html`<div class="srow"><div><b>${label}</b>${help && html`<p class="small muted">${help}</p>`}</div><div>${children}</div></div>`;

// SettingRow : one of the six rows. Opens in place, so Settings never becomes a long form.
function SettingRow({ icon, title, summary, children, open, onOpen }) {
  return html`<section class="glass" style="padding:0"><button class="sbig" aria-expanded=${open} onClick=${onOpen} style="border:0;background:transparent;box-shadow:none">
    <${Icon} name=${icon} /><span class="t"><b>${title}</b><span>${summary}</span></span><${Icon} name=${open ? "close" : "plus"} /></button>
    ${open && html`<div class="stack" style="padding:0 var(--s5) var(--s5)">${children}</div>`}</section>`;
}

function Assistant() {
  const [a, setA] = useState(null);
  useEffect(() => { api.get("/api/v2/autopilot").then(setA); }, []);
  if (!a) return null;
  const save = async (patch) => { try { setA(await api.put("/api/v2/autopilot", patch)); toast("Saved"); } catch (e) { toast(e.message); } };
  return html`<${Segmented} label="How proactive" value=${a.sensitivity} options=${LEVELS} onChange=${(v) => save({ sensitivity: v })} />
    <p class="small muted">${LEVEL_HELP[a.sensitivity]}</p>`;
}

function VoiceMic({ cfg, save }) {
  const [me, count] = useStore((s) => [s.people.find((p) => p.name === s.ui.self_name), s.people.length]);
  return html`<${Row} label="Where I listen" help="Automatic uses the buds when they're in your ears and the Mac when they're out.">
      <${Segmented} label="Placement" value=${cfg.placement} options=${[{ value: "auto", label: "Automatic" }, { value: "ear", label: "Buds" }, { value: "remote", label: "Mac" }]} onChange=${(v) => save({ placement: v })} /></${Row}>
    <${Row} label="Your voice" help=${me ? "Check how well I recognise you, or record more." : "I don't know your voice yet."}><a class="btn quiet sm" href=${me ? "#/people/" + me.id : "#/setup"}>${me ? "Open my voice" : "Set it up"}</a></${Row}>`;
}

function Connection() {
  const [ui, conn] = useStore((s) => [s.ui, s.connection]);
  const b = ui.buds.battery;
  const ok = (x) => x === "ready" ? "Ready" : x === "loading" ? "Loading…" : "Off";
  return html`<${Row} label="Buds">${b ? `Connected, ${Math.min(b.left, b.right)}% battery` : "Not connected"}</${Row}>
    <${Row} label="Language model">${ok(ui.models.chat)}</${Row}><${Row} label="Translator">${ok(ui.models.translate)}</${Row}>
    <${Row} label="This page">${conn === "live" ? "Up to date" : "Reconnecting…"}</${Row}>
    <p class="small muted">Having trouble? The setup check walks through each part.</p><div><a class="btn quiet sm" href="#/setup">Open the setup check</a></div>`;
}

function Privacy() {
  const [log, setLog] = useState([]);
  const [dlg, setDlg] = useState(false);
  const [typed, setTyped] = useState("");
  const [keep, setKeep] = useState(null);
  useEffect(() => { api.get("/api/v2/activity").then(setLog).catch(() => {}); api.get("/api/settings").then((c) => setKeep(c.keep_unnamed_days)).catch(() => {}); }, []);
  const saveKeep = async (v) => { try { const c = await api.post("/api/settings", { keep_unnamed_days: v }); setKeep(c.keep_unnamed_days); toast(v ? "Saved" : "Forgot those voices"); } catch (e) { toast(e.message); } };
  const exportLog = () => { const url = URL.createObjectURL(new Blob([JSON.stringify(log, null, 2)], { type: "application/json" })); const a = document.createElement("a"); a.href = url; a.download = "sidekick-activity.json"; a.click(); URL.revokeObjectURL(url); };
  const wipe = async () => { try { await api.post("/api/v2/delete-everything", { confirm: typed }); setDlg(false); setTyped(""); toast("Everything was deleted"); setLog(await api.get("/api/v2/activity")); } catch (e) { toast(e.message); } };
  return html`<p class="small muted">Everything stays on this Mac. Voices you haven't named are never saved.</p>
    ${keep !== null && html`<${Row} label="Keep voices I couldn't name" help="So I can ask you who they were. A short clip and voiceprint, no transcript of Telugu. Off forgets them now."><${Segmented} label="Keep unnamed voices" value=${String(keep)} onChange=${(v) => saveKeep(+v)} options=${[{ value: "0", label: "Off" }, { value: "7", label: "7 days" }, { value: "30", label: "30 days" }]} /></${Row}>`}
    <div class="stack" style="gap:4px"><h3>Activity</h3>${!log.length ? html`<p class="muted small">Nothing yet.</p>` : log.slice(0, 8).map((a) => html`<p class="small"><span class="muted">${when(a.ts)}</span>  ${a.text}</p>`)}</div>
    <div class="row wrap"><${Button} variant="quiet" onClick=${exportLog}>Export activity</${Button}><${Button} variant="danger" onClick=${() => setDlg(true)}>Delete everything</${Button}></div>
    <${Dialog} open=${dlg} title="Delete everything?" onClose=${() => setDlg(false)}
      actions=${html`<${Button} variant="quiet" onClick=${() => setDlg(false)}>Keep my data</${Button}><${Button} variant="danger" disabled=${typed.trim().toLowerCase() !== "delete everything"} onClick=${wipe}>Delete everything</${Button}>`}>
      <p>This removes every saved person, voice, conversation, note and recording. It cannot be undone.</p>
      <div class="field"><label for="de">Type <b>delete everything</b> to confirm</label><input id="de" type="text" value=${typed} onInput=${(e) => setTyped(e.target.value)} /></div></${Dialog}>`;
}

function Appearance() {
  const [t, setT] = useState(document.documentElement.dataset.theme || "system");
  const pick = (v) => { setT(v); try { v === "system" ? localStorage.removeItem("theme") : localStorage.setItem("theme", v); } catch (e) { /* ignore */ }
    v === "system" ? delete document.documentElement.dataset.theme : (document.documentElement.dataset.theme = v); };
  return html`<${Segmented} label="Theme" value=${t} onChange=${pick} options=${[{ value: "system", label: "Match my Mac" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />`;
}

function Advanced({ cfg, save }) {
  const [a, setA] = useState(null);
  useEffect(() => { api.get("/api/v2/autopilot").then(setA); }, []);
  const num = (k, label) => html`<${Row} label=${label}><input type="number" step="any" value=${cfg[k]} onChange=${(e) => e.target.value !== "" && save({ [k]: +e.target.value })} aria-label=${label} /></${Row}>`;
  const saveCat = async (patch) => { try { setA(await api.put("/api/v2/autopilot", patch)); toast("Saved"); } catch (e) { toast(e.message); } };
  return html`${a && CATS.map(([k, label]) => html`<${Row} label=${label}><${Toggle} checked=${a.categories[k]} label=${label} color="var(--a1)" onChange=${(v) => saveCat({ categories: { ...a.categories, [k]: v } })} /></${Row}>`)}
    <${Row} label="Understand Telugu speech" help="Always on while Interpreter is on."><${Toggle} checked=${cfg.telugu_stt} label="Understand Telugu speech" onChange=${(v) => save({ telugu_stt: v })} /></${Row}>
    ${num("speaker_threshold", "Voice match threshold (0 to 1)")}${num("hint_min_gap", "Seconds between whispers")}${num("hints_per_hour", "Whispers per hour")}${num("hint_max_words", "Longest whisper, in words")}
    <${Row} label=${`Replay length: ${cfg.ring_seconds} seconds`}><input type="range" min="5" max="60" value=${cfg.ring_seconds} aria-label="Replay length in seconds" onChange=${(e) => save({ ring_seconds: +e.target.value })} /></${Row}>
    <${Row} label="Everyday model"><code>${cfg.chat_model}</code></${Row}><${Row} label="Translation model"><code>${cfg.translate_model}</code></${Row}>
    <${Row} label="Developer view" help="Decision table, model state and analysis tools."><a class="btn quiet sm" href="#/dev">Open</a></${Row}>`;
}

export function Settings() {
  const [cfg, setCfg] = useState(null);
  const [open, setOpen] = useState(() => (location.hash.split("/")[2] || null));
  const [level, setLevel] = useState("");
  useEffect(() => { api.get("/api/settings").then(setCfg); api.get("/api/v2/autopilot").then((a) => setLevel(a.sensitivity)).catch(() => {}); }, []);
  const save = async (patch) => { try { setCfg(await api.post("/api/settings", patch)); toast("Saved"); } catch (e) { toast(e.message); } };
  if (!cfg) return html`<p class="muted">Loading…</p>`;
  const rows = [
    ["voice", "ear", "Voice and microphones", "Where I listen and how well I know you", html`<${VoiceMic} cfg=${cfg} save=${save} />`],
    ["assistant", "autopilot", "Assistant", `How proactive I am: ${LEVELS.find((l) => l.value === level)?.label || "…"}`, html`<${Assistant} />`],
    ["privacy", "lock", "Privacy", "What I remember, and deleting it", html`<${Privacy} />`],
    ["appearance", "settings", "Appearance", "Night, day or match your Mac", html`<${Appearance} />`],
    ["connection", "battery", "Connection", "Buds, language model, translator", html`<${Connection} />`],
    ["advanced", "search", "Advanced", "Thresholds, models, developer view", html`<${Advanced} cfg=${cfg} save=${save} />`],
  ];
  return html`<div class="srows"><h2>Settings</h2>${rows.map(([id, icon, title, summary, body]) =>
    html`<${SettingRow} key=${id} icon=${icon} title=${title} summary=${summary} open=${open === id} onOpen=${() => setOpen(open === id ? null : id)}>${body}</${SettingRow}>`)}</div>`;
}
