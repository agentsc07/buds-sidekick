import { html, render, useState, useEffect } from "../vendor/htm-preact-standalone.module.js";
import { DEMO, useStore, connect, set } from "./store.js";
import { useRoute, go } from "./router.js";
import { Icon, ModeChip, Toasts, Dialog, Button } from "./components/ui.js";
import { Home } from "./views/home.js";
import { api } from "./api.js";

const NAV = [["home", "Home", "home"], ["me", "Day", "calendar"], ["people", "People", "people"], ["controls", "Controls", "touch"], ["settings", "Settings", "settings"]];
const VIEWS = { home: Home };
export const registerView = (name, comp) => { VIEWS[name] = comp; };

function Buds() {
  const [buds, practice] = useStore((s) => [s.ui.buds, !!s.ui.practice]);
  const b = buds.battery;
  const wear = (side) => ({ in_ear: "in ear", out: "out", in_case: "in case" }[buds.wear[side]] || "not connected");
  return html`<div class="row" style="gap:6px">
    ${b ? html`<span class="pill num" title="Battery: left, right, case"><${Icon} name="battery" />${b.left}% ${b.right}% ${b.case}%</span>
               <span class="pill">Left ${wear("L")}, right ${wear("R")}</span>`
        : practice ? html`<span class="pill" title="No earbuds needed: you drive it from this page">Practice mode</span>`
        : html`<span class="pill warn"><${Icon} name="alert" />Buds not connected</span>`}
  </div>`;
}

function Banner() {
  const [conn, banner, models, noMe, voiceReady, busy] = useStore((s) => [s.connection, s.ui.banner, s.ui.models, s.connection === "live" && s.people.length >= 0 && s.peopleLoaded && !s.people.some((p) => p.name === s.ui.self_name), s.ui.voice_ready, s.ui.busy]);
  const mode = useStore((s) => s.ui.mode);
  const off = models.chat === "unloaded" && mode !== "interpreter" && models.translate === "unloaded";   // Interpreter pauses it on purpose
  const [down, setDown] = useState(false);
  useEffect(() => { if (!off) { setDown(false); return; } const t = setTimeout(() => setDown(true), 8000); return () => clearTimeout(t); }, [off]);   // it comes back by itself within seconds
  const items = [];
  if (noMe) items.push(["warn", "I don't know your voice yet, so I can't tell you apart from other people. Set it up in Setup, step 4."]);
  else if (voiceReady === false) items.push(["warn", "I've improved how I recognise voices, so I need to hear yours again. It takes 20 seconds."]);
  if (conn === "reconnecting") items.push(["warn", "Reconnecting to Sidekick. This page updates again as soon as it is back."]);
  if (banner) items.push(["warn", banner]);
  if (busy) items.push(["warn", "Your Mac is very busy right now, so I'm slower than usual. Closing other heavy apps will help."]);
  if (conn === "live" && down && !DEMO) items.push(["bad", "The language model is not running, so only quick commands work."]);
  if (DEMO && off) items.push(["bad", "The language model is not running, so only quick commands work."]);
  return items.slice(0, 1).map(([k, m]) => html`<div class=${`banner ${k}`} role="alert"><${Icon} name="alert" /><span>${m}</span>
    ${(m.includes("language model") || m.includes("your voice") || m.includes("hear yours")) && html`<span class="spacer"></span><a href="?step=3#/setup" class="small">${m.includes("language model") ? "Check setup" : "Record my voice"}</a>`}</div>`);
}

function Shortcuts({ open, onClose }) {
  return html`<${Dialog} open=${open} title="Keyboard shortcuts" onClose=${onClose} actions=${html`<${Button} onClick=${onClose}>Close</${Button}>`}>
    <div class="stack small">${[["g h", "Home"], ["g d", "Day"], ["g p", "People"], ["g c", "Controls"], ["g s", "Settings"], ["?", "This list"]].map(([k, v]) =>
      html`<div class="row"><span style="width:60px">${k.split(" ").map((x) => html`<kbd>${x}</kbd> `)}</span>${v}</div>`)}</div></${Dialog}>`;
}

function App() {
  const route = useRoute();
  const [mode, level] = useStore((s) => [s.ui.mode, s.ui.memory_level]);
  const [help, setHelp] = useState(false);
  useEffect(() => {
    let g = 0;
    const key = (e) => {
      if (/input|textarea|select/i.test(e.target.tagName) || e.metaKey || e.ctrlKey) return;
      if (e.key === "?") return setHelp(true);
      if (e.key === "g") { g = Date.now(); return; }
      if (Date.now() - g < 1000) { const t = { h: "home", d: "me", p: "people", c: "controls", s: "settings" }[e.key]; if (t) go(t); g = 0; }
    };
    addEventListener("keydown", key); return () => removeEventListener("keydown", key);
  }, []);
  const View = VIEWS[route.name] || Home;
  return html`<div class="app">
    <nav class="rail" aria-label="Main"><span class="brand">Sidekick</span>
      ${NAV.map(([id, label, icon]) => html`<a href=${"#/" + id} aria-current=${(route.name === id || (id === "home" && !VIEWS[route.name])) ? "page" : undefined}><${Icon} name=${icon} />${label}</a>`)}
    </nav>
    <div class="main">
      <header class="topbar"><${ModeChip} mode=${mode} />
        ${mode !== "standby" && mode !== "private" && html`<span class="pill">${{ live: "Not saving", remember: "Remembering", recording: "Recording" }[level]}</span>`}
        <span class="spacer"></span><${Buds} /></header>
      <${Banner} />
      <main class="view" id="view"><${View} id=${route.id} /></main>
    </div>
    <${Toasts} /><${Shortcuts} open=${help} onClose=${() => setHelp(false)} />
  </div>`;
}

function applyTheme() {          // ?theme=light|dark overrides, else the saved choice, else the system setting
  let t = new URLSearchParams(location.search).get("theme");
  try { t = t || localStorage.getItem("theme"); } catch (e) { /* private window */ }
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
}

(async () => {
  applyTheme();
  if (DEMO) { const { initDemo } = await import("./fixtures.js"); initDemo(); }
  await import("./views/register.js");
  render(html`<${App} />`, document.getElementById("root"));
  connect();
  if (!DEMO) api.get("/api/v2/setup/status").then((st) => { if ((!st.done || !st.has_me || st.me_ready === false) && !location.hash.startsWith("#/setup")) go("setup"); }).catch(() => {});
})();
