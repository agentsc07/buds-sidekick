// One reactive store. The backend owns the truth: `ui` is the last pushed snapshot; lists are appended from pushed events.
import { useState, useEffect } from "../vendor/htm-preact-standalone.module.js";

export const DEMO = new URLSearchParams(location.search).has("demo");
export const state = {
  ui: { mode: "standby", memory_level: "remember", placement: "ear", route: "ear", conversation_id: null, ring_seconds: 0,
        buds: { battery: null, wear: { L: null, R: null } }, models: { chat: "unloaded", embed: "unloaded", translate: "unloaded" },
        autopilot: { enabled: false, sensitivity: "balanced", feed: [] }, banner: null },
  connection: "connecting", lastSeq: 0, peopleLoaded: false, translations: [], segments: [], decisions: [], replies: [], marks: 0, people: [], toasts: [], tokens: [], health: null,
};
const listeners = new Set();
export function set(patch) { Object.assign(state, patch); listeners.forEach((f) => f()); }
export function useStore(sel) {
  const [v, setV] = useState(() => sel(state));
  useEffect(() => { const f = () => setV(sel(state)); listeners.add(f); f(); return () => listeners.delete(f); }, []);
  return v;
}

let toastId = 0;
export function toast(msg, undo) {
  const id = ++toastId;
  set({ toasts: [...state.toasts, { id, msg, undo }] });
  setTimeout(() => dismissToast(id), 6000);
}
export const dismissToast = (id) => set({ toasts: state.toasts.filter((t) => t.id !== id) });

const PALETTE = ["#2f6fed", "#e0762b", "#1a9c57", "#9b59d0", "#c2385a", "#0e9aa7", "#8a6d00", "#5b6b8a"];
export function colorFor(name) {
  const p = state.people.find((x) => x.name === name);
  if (p?.color) return p.color;
  let h = 0; for (const c of name || "?") h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

// Apply one pushed event. Events carry a sequence number, so a replay after a reconnect (the socket's hello repeats recent history)
// never duplicates anything; a lower number means the server restarted, so start from scratch.
export function apply(ev) {
  const d = ev.data || {};
  if (ev.seq != null) {
    if (ev.seq <= state.lastSeq) return;
    set({ lastSeq: ev.seq });
  }
  switch (ev.type) {
    case "ui_state": return set({ ui: ev.data });
    case "conversation_started": return set({ segments: [], decisions: [], replies: [], translations: [], marks: 0 });      // a new conversation starts clean
    case "segment": return state.segments.some((e) => e.t0 === d.t0 && e.speaker === d.speaker) ? undefined
      : set({ segments: [...state.segments, { ...d, ts: d.t1 }].slice(-300) });
    case "segment_relabel": return set({ segments: state.segments.map((e) => (e.speaker === d.cluster ? { ...e, speaker: d.name, person_id: d.person_id } : e)) });
    case "autopilot_decision": {
      const i = d.hint_id ? state.decisions.findIndex((x) => x.hint_id === d.hint_id) : -1;       // a later verdict replaces the earlier row
      const row = { ...d, ts: ev.ts };
      return set({ decisions: i >= 0 ? state.decisions.map((x, n) => (n === i ? { ...x, ...row, ts: x.ts } : x)) : [...state.decisions, row].slice(-200) });
    }
    case "translation": return set({ translations: [...state.translations, { ...d, ts: ev.ts }].slice(-60) });
    case "translation_skipped": return set({ translations: [...state.translations, { ...d, ts: ev.ts, skipped: true }].slice(-60) });
    case "reply": return set({ replies: [...state.replies, { ...d, ts: ev.ts }].slice(-50) });
    case "token": return set({ tokens: [...state.tokens, { token: d.token, ts: ev.ts }].slice(-20) });
    case "bookmark": set({ marks: state.marks + 1 }); return Date.now() / 1000 - ev.ts < 5 ? toast("Marked this moment") : undefined;
    case "renamed": set({ segments: state.segments.map((e) => (e.speaker === d.old ? { ...e, speaker: d.name } : e)) }); return loadPeople();
    case "enrolled": case "cluster_named": case "forgotten": return loadPeople();
  }
}

import { api } from "./api.js";
export async function loadPeople() { try { set({ people: await api.get("/api/people"), peopleLoaded: true }); } catch (e) { /* offline */ } }

export function ingestHello(events) {
  if (events.length && Math.max(...events.map((e) => e.seq || 0)) < state.lastSeq) {          // the server restarted: its numbering began again
    set({ lastSeq: 0, segments: [], decisions: [], replies: [], translations: [], marks: 0 });
  }
  events.forEach(apply);
}

export async function connect() {
  if (DEMO) return;
  let delay = 500;
  const open = () => {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => { delay = 500; set({ connection: "live" }); };
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.kind === "hello") { ingestHello(msg.events); return; }
      apply(msg);
    };
    ws.onclose = () => { set({ connection: "reconnecting" }); setTimeout(open, delay); delay = Math.min(delay * 2, 5000); };
  };
  open();
  try {
    const seg = await api.get("/api/live");                    // the current conversation; the socket's history fills in the rest
    const have = new Set(state.segments.map((e) => `${e.t0}|${e.speaker}`));
    set({ segments: [...seg.filter((e) => !have.has(`${e.t0}|${e.speaker}`)).map((e) => ({ ...e, ts: e.t1 })), ...state.segments].sort((a, b) => a.t0 - b.t0) });
  } catch (e) { /* the socket will fill it */ }
  loadPeople();
}
