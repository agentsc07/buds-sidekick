// Live conversation parts: who is here, transcript with Sidekick's margin notes, what was noticed, quick actions.
import { html, useState, useEffect, useRef } from "../../vendor/htm-preact-standalone.module.js";
import { state, set, useStore, colorFor, toast } from "../store.js";
import { api } from "../api.js";
import { Icon, Button, Avatar, when, Dialog } from "./ui.js";

export function useTick(ms = 1000) {
  const [, f] = useState(0);
  useEffect(() => { const i = setInterval(() => f((x) => x + 1), ms); return () => clearInterval(i); }, []);
}

// WhosHere : one avatar per voice heard in the last few minutes; pulses while that voice is talking; grey "?" when not sure.
export function WhosHere() {
  const segs = useStore((s) => s.segments);
  useTick();
  const nowS = Date.now() / 1000;
  const voices = new Map();
  for (const e of segs) if (nowS - e.t1 < 300) voices.set(e.speaker, e);
  if (!voices.size) return html`<p class="muted">No one has spoken yet. Voices show up here as they talk.</p>`;
  return html`<div class="here">${[...voices.values()].map((e) => {
    const unsure = e.person_id == null;
    return html`<div class="here-one" key=${e.speaker}>
      <${Avatar} name=${e.speaker} color=${unsure ? undefined : colorFor(e.speaker)} size=${40} unsure=${unsure} talking=${nowS - e.t1 < 4} />
      <span>${unsure ? "Not sure who" : e.speaker}<small class="muted num">${unsure ? e.speaker : `${Math.round((e.conf || 0) * 100)}% sure`}</small></span></div>`;
  })}</div>`;
}

const TRIGGER = { identity: "Who", question: "Answer", capture: "Noted", commitment: "Reminder", mention: "Name" };

// Note { d } : Sidekick in the margin. said = spoken whisper (rate it), noted = a promise it wrote down (undo), held_back = why it stayed quiet.
export function Note({ d }) {
  const [done, setDone] = useState(null);
  const rate = async (useful) => { setDone(useful ? "up" : "down"); try { await api.post(`/api/v2/hints/${d.hint_id}/feedback`, { useful }); } catch (e) { toast(e.message); } };
  const undo = async () => { try { await api.post(`/api/v2/commitments/${d.fact_id}/undo`); setDone("undone"); toast("Removed from your promises"); } catch (e) { toast(e.message); } };
  if (d.outcome === "held_back") return null;
  return html`<div class=${`whisper ${d.outcome}`}><${Icon} name="autopilot" /><span class="wt">${d.text}</span>
    ${d.outcome === "noted"
      ? (done === "undone" ? html`<span class="small muted">Removed</span>` : d.fact_id && html`<button class="linkbtn" onClick=${undo}>Undo</button>`)
      : html`<button class="iconbtn sm" aria-label="Useful" aria-pressed=${done === "up"} onClick=${() => rate(true)}><${Icon} name="up" /></button>
             <button class="iconbtn sm" aria-label="Not useful" aria-pressed=${done === "down"} onClick=${() => rate(false)}><${Icon} name="down" /></button>`}</div>`;
}

// Conversation : a compact log. One line per utterance (time, name, text); Sidekick's whispers sit under the line they answer, quieter.
const hhmm = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
export function Conversation({ limit = 60 }) {
  const [segs, decisions] = useStore((s) => [s.segments, s.decisions]);
  const ref = useRef();
  const rows = segs.slice(-limit).map((e) => ({ e, notes: [] }));
  for (const d of decisions) {
    if (!rows.length || d.outcome === "held_back") continue;                       // silences are in the Developer view, not in the log
    let best = rows[0];
    for (const r of rows) if (Math.abs(r.e.t1 - d.ts) < Math.abs(best.e.t1 - d.ts)) best = r;
    best.notes.push(d);
  }
  useEffect(() => { const el = ref.current; if (el && el.parentElement) el.parentElement.scrollTop = el.parentElement.scrollHeight; }, [segs.length, decisions.length]);
  if (!rows.length) return html`<p class="muted empty4">The conversation appears here as people talk.</p>`;
  return html`<div class="log" ref=${ref}>${rows.map(({ e, notes }) => html`<div class="entry" key=${e.t0}>
    <div class=${`tline ${e.person_id == null ? "unsure" : ""}`}><span class="tt num">${hhmm(e.t1)}</span>
      <span class="tn" style=${e.person_id == null ? "" : `color:${colorFor(e.speaker)}`} title=${e.why || ""}>${e.no_id ? (e.lang === "te" ? "Telugu" : "Translated") : e.person_id == null ? (e.speaker === "Unsure" ? "?" : e.speaker) : e.speaker}</span>
      <span class="tx">${e.text}${e.experimental && html` <span class="pill warn">Experimental</span>`}</span></div>
    ${notes.map((d, i) => html`<${Note} d=${d} key=${i} />`)}</div>`)}</div>`;
}

// Noticed : promises Sidekick wrote down and moments you marked, in this conversation.
export function Noticed() {
  const [decisions, marks] = useStore((s) => [s.decisions, s.marks]);
  const noted = decisions.filter((d) => d.outcome === "noted");
  return html`<div class="stack" style="gap:8px"><h3>Noticed so far</h3>
    ${!noted.length && !marks ? html`<p class="muted small">Promises you make and moments you mark collect here.</p>` : null}
    ${noted.map((d) => html`<p class="voice">${d.text}</p>`)}
    ${marks ? html`<p class="small"><${Icon} name="mark" /> ${marks} marked ${marks === 1 ? "moment" : "moments"}</p>` : null}</div>`;
}

// ActionBar : the five things you reach for mid-conversation.
export function ActionBar() {
  const run = (fn) => async () => { try { await fn(); } catch (e) { toast(e.message); } };
  return html`<div class="actions-bar">
    <${Button} variant="quiet" icon="rewind" onClick=${run(() => api.post("/api/replay"))}>Replay</${Button}>
    <${Button} variant="quiet" icon="mark" onClick=${run(() => api.post("/api/mark"))}>Mark</${Button}>
    <${Button} variant="quiet" icon="catchup" onClick=${run(() => api.post("/api/action", { action: "catch_up" }))}>Catch me up</${Button}>
    <${Button} variant="quiet" icon="lock" onClick=${run(() => api.post("/api/v2/mode", { mode: "private" }))}>Go private</${Button}>
  </div>`;
}
