import { html, useState, useEffect } from "../../vendor/htm-preact-standalone.module.js";
import { useStore, toast } from "../store.js";
import { api } from "../api.js";
import { useTryMode } from "../hooks.js";
import { Button, Toggle, Dialog, Icon } from "../components/ui.js";

const SIDES = [["L", "Left bud", "Talk to me"], ["R", "Right bud", "Control the session"]];
const KINDS = [["single", "Single tap", 1], ["double", "Double tap", 2], ["triple", "Triple tap", 3], ["hold", "Touch and hold", 0]];
const SAYINGS = [["What's on my calendar tomorrow?", "Your agenda"], ["Am I free Friday at 3?", "Checks your calendar"], ["Add buy milk to my to-do list", "Saves it"],
  ["Remind me to call mum tomorrow at 9", "Sets a reminder"], ["Who is talking?", "Names the voice"], ["Translate to Telugu: good morning", "Speaks the translation"], ["Catch me up", "Summarises the last minute"]];
const MOMENTS = [["Any tap while I'm speaking", "Stops me"], ["A tap just after a whisper", "Tell me more"], ["A double tap after a whisper", "Not useful"], ["A double tap after 'I've added…'", "Undo"]];
const SOUNDS = [["mode_on", "Something turned on"], ["mode_off", "Something turned off"], ["accepted", "I heard your tap"], ["command", "Running a command"], ["whisper", "A hint is coming"],
  ["noted", "I saved something"], ["reminder", "A reminder"], ["error", "Something went wrong"]];

const BudArt = ({ left }) => html`<svg class="budart" viewBox="0 0 54 54" aria-hidden="true" style=${left ? "" : "transform:scaleX(-1)"}><defs><linearGradient id="bg" x1="0" x2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#ff8a4c"/></linearGradient></defs>
  <path d="M30 6c9 0 15 7 15 16 0 8-5 12-9 17-3 4-3 9-8 9-6 0-9-5-9-11V18C19 11 23 6 30 6z"/><circle class="pad" cx="32" cy="22" r="6"/></svg>`;

function Dots({ n }) { return n ? html`<span class="dots">${Array.from({ length: n }, () => html`<i></i>`)}</span>` : html`<span class="dots"><i style="width:22px;border-radius:4px"></i></span>`; }

export function Controls() {
  const [g, setG] = useState(null);
  const [pick, setPick] = useState(null);                      // the slot being edited, e.g. "L:single"
  const [tryIt, setTryIt] = useState(false);
  const tokens = useStore((s) => s.tokens);
  const load = () => api.get("/api/v2/gestures").then(setG);
  useEffect(() => { load(); }, []);
  useTryMode(tryIt);
  if (!g) return html`<p class="muted">Loading…</p>`;
  const cur = Object.fromEntries(g.slots.map((s) => [s.gesture, s.action]));
  const label = (id) => g.actions.find((a) => a.id === id)?.label || id;
  const last = tokens[tokens.length - 1];
  const lastG = tryIt && last && Date.now() / 1000 - last.ts < 4 ? last.token.replace(/_(start|end)$/, "") : null;
  const choose = async (action) => {
    try { await api.put("/api/v2/gestures", { slots: [{ gesture: pick, action }] }); setPick(null); await load(); toast("Saved"); } catch (e) { toast(e.message); }
  };
  const reset = async () => { await api.post("/api/v2/gestures/reset"); await load(); toast("Back to the defaults"); };
  const ask = (q) => api.post("/api/ask", { text: q }).then(() => toast("Asked. Listen for my answer.")).catch((e) => toast(e.message));
  return html`<div class="controls">
    <div class="row wrap"><h2>Controls</h2><span class="spacer"></span><span class="small muted">Try them without doing anything</span>
      <${Toggle} checked=${tryIt} label="Try gestures without doing anything" onChange=${setTryIt} /></div>
    <p class="muted">Everything works from your buds, in your ears or as a remote. Tap a row to change what it does.</p>
    ${tryIt && html`<p class="glass small" aria-live="polite">${lastG ? html`I saw <b>${lastG.replace(":", " ")}</b>. It would: <b>${label(cur[lastG])}</b>.` : "Tap or hold a bud. Nothing will happen except showing what it would do."}</p>`}
    <div class="budpair">${SIDES.map(([side, name, sub]) => html`<section class="glass budcard"><header><${BudArt} left=${side === "L"} /><div><h3>${name}</h3><p class="small muted">${sub}</p></div></header>
      ${KINDS.map(([kind, kl, n]) => { const key = `${side}:${kind}`;
        return html`<button class=${`grow ${lastG === key ? "hit" : ""}`} onClick=${() => setPick(key)} aria-label=${`${name}, ${kl}: ${label(cur[key])}. Change`}><${Dots} n=${n} /><span class="k">${kl}</span><span class="a">${label(cur[key])}</span></button>`; })}</section>`)}</div>
    <section class="glass stack"><h3>In the moment</h3><div class="sayings">${MOMENTS.map(([a, b]) => html`<div class="saying"><b>${b}</b><small>${a}</small></div>`)}</div></section>
    <section class="glass stack"><h3>Things you can say</h3><p class="small muted">Tap one to try it now.</p>
      <div class="sayings">${SAYINGS.map(([q, hint]) => html`<button class="saying" onClick=${() => ask(q)}>"${q}"<small>${hint}</small></button>`)}</div></section>
    <section class="glass stack"><h3>What the sounds mean</h3><div class="sounds">${SOUNDS.map(([k, v]) => html`<span><${Icon} name="ear" />${v}</span>`)}</div></section>
    <div><${Button} variant="quiet" onClick=${reset}>Reset to defaults</${Button}></div>
    <${Dialog} open=${!!pick} title=${pick ? `${pick.startsWith("L") ? "Left" : "Right"} bud, ${KINDS.find((k) => k[0] === pick.split(":")[1])[1].toLowerCase()}` : ""} onClose=${() => setPick(null)} actions=${html`<${Button} variant="quiet" onClick=${() => setPick(null)}>Cancel</${Button}>`}>
      <div class="stack" style="gap:6px">${g.actions.map((a) => html`<button class=${`grow ${pick && cur[pick] === a.id ? "hit" : ""}`} onClick=${() => choose(a.id)}><span class="a">${a.label}</span></button>`)}</div></${Dialog}>
  </div>`;
}
