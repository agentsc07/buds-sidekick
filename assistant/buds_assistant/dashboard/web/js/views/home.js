import { html, useState, useEffect, useRef } from "../../vendor/htm-preact-standalone.module.js";
import { state, set, useStore, toast } from "../store.js";
import { api } from "../api.js";
import { Icon, Button, Toggle, Segmented, when } from "../components/ui.js";
import { InterpreterPanel, TranslateBox } from "../components/interpreter.js";
import { Conversation, useTick } from "../components/live.js";
import { Orb } from "../components/orb.js";

const LEVELS = [{ value: "off", label: "Off" }, { value: "quiet", label: "Quiet" }, { value: "balanced", label: "Helpful" }, { value: "proactive", label: "Proactive" }];
const LEVEL_HELP = { off: "I only answer when you ask.", quiet: "Your promises, and questions I can answer from your day.", balanced: "Also useful things I'm fairly sure of.", proactive: "I'll chip in whenever I can help, like looking things up." };

function hero(ui, segs, decisions) {
  const people = new Set(segs.filter((e) => Date.now() / 1000 - e.t1 < 300 && e.person_id != null).map((e) => e.speaker)).size;
  const last = [...decisions].reverse().find((d) => d.outcome !== "held_back");
  if (ui.pending_mode === "interpreter") return ["Getting ready", "Loading the translator. The first time takes about a minute."];
  switch (ui.mode) {
    case "listen": return ["Listening", people ? `${people} ${people === 1 ? "person" : "people"} here` : "Say \"Sidekick\" and ask me anything"];
    case "autopilot": return ["Listening, Autopilot on", last ? `Last whisper ${when(last.ts)}` : "I'll chip in when I can help"];
    case "interpreter": return ["Translating", ui.models.translate === "ready" && ui.models.telugu === "ready" ? "Telugu and English, in your ear" : "Getting ready"];
    case "private": return ["Private", "The mic is closed and nothing is saved"];
    default: return ["Mic off", "Turn on Listening, or just ask me something"];
  }
}

// Switches: Listening (the mic), Autopilot (how much I chip in), Translate (live translation). Private is an action, not a mode (see docs/app-map.md).
function Switches() {
  const [mode, pending, level] = useStore((s) => [s.ui.mode, s.ui.pending_mode, s.ui.autopilot.sensitivity]);
  const live = useStore((s) => !!s.ui.live_translation);
  const busy = !!pending;
  const translating = mode === "interpreter" || pending === "interpreter";
  const listening = mode === "listen" || mode === "autopilot" || mode === "interpreter";      // the mic is on while translating too
  const apLevel = mode === "autopilot" ? level : "off";
  const choose = async (next) => {
    if (busy) return;                                           // a switch that is still working ignores further clicks
    const prev = state.ui;
    if (next !== "interpreter") set({ ui: { ...prev, mode: next } });       // optimistic, except Translate: it shows "Getting ready" from the backend
    try { await api.post("/api/v2/mode", { mode: next }); } catch (e) { set({ ui: prev }); toast(e.message); }
  };
  const setLevel = async (v) => {
    if (busy) return;
    try {
      if (v === "off") return choose("listen");
      await api.put("/api/v2/autopilot", { sensitivity: v });
      set({ ui: { ...state.ui, autopilot: { ...state.ui.autopilot, sensitivity: v } } });
      if (mode !== "autopilot") await choose("autopilot");
    } catch (e) { toast(e.message); }
  };
  return html`<div class="switches">
    <div class="srow2"><div><b>Listening</b><p class="small muted">${translating ? "Mic on for translating, nothing is saved" : !listening ? "Mic off" : mode === "private" ? "Mic closed" : "Mic on, saving the conversation"}</p></div>
      <${Toggle} checked=${listening} label="Listening" onChange=${(on) => choose(on ? "listen" : "standby")} /></div>
    ${live && html`<div class="srow2"><div><b>Translate</b><p class="small muted">${pending === "interpreter" ? "Getting ready…" : "Telugu and English, live"}</p></div>
      <${Toggle} checked=${translating} label="Translate" onChange=${(on) => choose(on ? "interpreter" : "listen")} /></div>`}
    <div class="autopilot ${translating ? "dim" : ""}"><div class="row"><b>Autopilot</b><span class="spacer"></span></div>
      <${Segmented} label="Autopilot" value=${apLevel} options=${LEVELS} onChange=${setLevel} />
      <p class="small muted">${translating ? "Paused while translating." : LEVEL_HELP[apLevel]}</p></div></div>`;
}

function Actions() {
  const [mode, level] = useStore((s) => [s.ui.mode, s.ui.memory_level]);
  const run = (fn) => async () => { try { await fn(); } catch (e) { toast(e.message); } };
  const setLevel = async (l) => { try { await api.post("/api/v2/memory-level", { level: l }); } catch (e) { toast(e.message); } };
  const live = mode === "listen" || mode === "autopilot";
  return html`<div class="actions4">
    ${live && html`<label class="srow2 compact"><span>Save this conversation</span><${Toggle} checked=${level !== "live"} label="Save this conversation" onChange=${(on) => setLevel(on ? "remember" : "live")} /></label>`}
    <div class="btnrow">
      <${Button} variant="quiet" size="sm" icon="rewind" onClick=${run(() => api.post("/api/replay"))}>Replay</${Button}>
      <${Button} variant="quiet" size="sm" icon="mark" onClick=${run(() => api.post("/api/mark"))}>Mark</${Button}>
      <${Button} variant="quiet" size="sm" icon="catchup" onClick=${run(() => api.post("/api/action", { action: "catch_up" }))}>Catch up</${Button}>
      <${Button} variant=${mode === "private" ? "" : "quiet"} size="sm" icon="lock" onClick=${run(() => api.post("/api/v2/mode", { mode: mode === "private" ? "standby" : "private" }))}>${mode === "private" ? "End private" : "Go private"}</${Button}></div></div>`;
}

function AskBar() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const replies = useStore((s) => s.replies);
  const last = replies[replies.length - 1];
  const send = async (q) => {
    if (!q.trim()) return;
    setBusy(true);
    try { await api.post("/api/ask", { text: q }); setText(""); } catch (err) { toast(err.message); }
    setBusy(false);
  };
  return html`<div class="askdock">
    ${last && html`<p class="answer4"><${Icon} name="ask" /><span>${last.text || "Done."}</span></p>`}
    <form onSubmit=${(e) => { e.preventDefault(); send(text); }}>
      <input type="text" aria-label="Ask Sidekick" placeholder="Ask me anything…" value=${text} onInput=${(e) => setText(e.target.value)} />
      <button type="button" class="iconbtn" aria-label="Speak your question" title="Speak your question" onClick=${() => api.post("/api/action", { action: "ask" }).then(() => toast("I'm listening. Go ahead."))}><${Icon} name="mic" /></button>
      <${Button} type="submit" icon="ask" disabled=${busy || !text.trim()}>Ask</${Button}></form></div>`;
}

export function Home() {
  const [ui, segs, decisions] = useStore((s) => [s.ui, s.segments, s.decisions]);
  useTick(5000);
  const [big, small] = hero(ui, segs, decisions);
  const translating = ui.mode === "interpreter" || ui.pending_mode === "interpreter";
  return html`<div class="home4">
    <aside class="panel4"><div class="status4" aria-live="polite"><${Orb} /><div><h1>${big}</h1><p class="muted">${small}</p></div></div>
      <${Switches} /><${Actions} /></aside>
    <section class="main4"><div class="convhead"><h2>${translating ? "Translation" : "Conversation"}</h2></div>
      <div class="scroll4">${translating ? html`<${InterpreterPanel} />` : html`<${Conversation} />`}</div>
      ${!translating && html`<${TranslateBox} />`}
      <${AskBar} /></section>
  </div>`;
}
