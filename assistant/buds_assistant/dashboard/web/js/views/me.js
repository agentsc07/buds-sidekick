import { html, useState, useEffect } from "../../vendor/htm-preact-standalone.module.js";
import { toast } from "../store.js";
import { api } from "../api.js";
import { Icon, Button, EmptyState } from "../components/ui.js";

// My day: the calendar, to-dos and reminders Sidekick uses to answer for you. Sample data is flagged and removable.
function Add({ placeholder, whenPlaceholder, onAdd, label }) {
  const [text, setText] = useState(""); const [when, setWhen] = useState("");
  const go = async (e) => { e.preventDefault(); if (!text.trim()) return; if (await onAdd(text.trim(), when.trim())) { setText(""); setWhen(""); } };
  return html`<form class="row wrap add" onSubmit=${go}>
    <input type="text" aria-label=${label} placeholder=${placeholder} value=${text} onInput=${(e) => setText(e.target.value)} />
    <input type="text" aria-label=${label + " when"} placeholder=${whenPlaceholder} value=${when} onInput=${(e) => setWhen(e.target.value)} style="max-width:220px" />
    <${Button} type="submit" variant="quiet" icon="plus" disabled=${!text.trim()}>Add</${Button}></form>`;
}

export function MyDay() {
  const [d, setD] = useState(null);
  const load = () => api.get("/api/v2/me").then(setD).catch((e) => toast(e.message));
  useEffect(() => { load(); const i = setInterval(load, 20000); return () => clearInterval(i); }, []);
  if (!d) return html`<p class="muted">Loading…</p>`;
  const act = (fn) => async (...a) => { try { await fn(...a); await load(); return true; } catch (e) { toast(e.message); return false; } };
  const sample = act((on) => api.post("/api/v2/me/sample", { on }));
  return html`<div class="stack" style="gap:var(--s5)">
    <div class="row wrap"><h2>Day</h2><span class="spacer"></span>
      ${d.sample ? html`<span class="pill warn">Sample data</span><${Button} variant="quiet" size="sm" onClick=${() => sample(false)}>Clear sample data</${Button}>`
        : html`<${Button} variant="quiet" size="sm" onClick=${() => sample(true)}>Load sample data</${Button}>`}</div>
    <p class="muted">Sidekick checks this when someone asks if you are free, warns you about meetings and reminders, and adds your promises to the to-do list.</p>
    <section class="stack" style="gap:6px"><h3>Calendar</h3>
      ${!d.events.length ? html`<p class="muted">Nothing coming up.</p>` : d.events.map((e) => html`<div class="row loop" key=${e.id}><${Icon} name="calendar" /><span><b>${e.title}</b> <span class="muted">${e.when_label}${e.people.length ? `, with ${e.people.join(", ")}` : ""}</span></span><span class="spacer"></span>
        <button class="iconbtn" aria-label=${`Remove ${e.title}`} onClick=${() => act(() => fetch(`/api/v2/me/events/${e.id}`, { method: "DELETE" }).then((r) => { if (!r.ok) throw new Error("Could not remove that event."); }))()}><${Icon} name="close" /></button></div>`)}
      <${Add} label="New event" placeholder="Event, like Budget review with Priya" whenPlaceholder="Friday at 2 pm" onAdd=${act((t, w) => api.post("/api/v2/me/events", { title: t, when: w }))} /></section>
    <section class="stack" style="gap:6px"><h3>To-do</h3>
      ${!d.todos.length ? html`<${EmptyState} icon="check" title="Nothing to do" text="Promises you make with Autopilot on land here by themselves." />` : d.todos.map((t) => html`<label class="row loop" key=${t.id}>
        <input type="checkbox" onChange=${act(() => api.post(`/api/v2/me/todos/${t.id}/done`))} /><span>${t.text}${t.due_text ? html` <span class="muted">${t.due_text}</span>` : ""}</span>
        <span class="spacer"></span>${t.source === "promise" && html`<span class="pill">You promised</span>`}</label>`)}
      <${Add} label="New to-do" placeholder="Something to do" whenPlaceholder="by Friday (optional)" onAdd=${act((t, w) => api.post("/api/v2/me/todos", { text: t, when: w }))} /></section>
    <section class="stack" style="gap:6px"><h3>Reminders</h3>
      ${!d.reminders.length ? html`<p class="muted">No reminders.</p>` : d.reminders.map((r) => html`<div class="row loop" key=${r.id}><${Icon} name="alert" /><span>${r.text} <span class="muted">${r.when_label}</span></span><span class="spacer"></span>
        <button class="iconbtn" aria-label=${`Dismiss ${r.text}`} onClick=${act(() => api.post(`/api/v2/me/reminders/${r.id}/done`))}><${Icon} name="check" /></button></div>`)}
      <${Add} label="New reminder" placeholder="Remind me to…" whenPlaceholder="tomorrow at 9" onAdd=${act((t, w) => api.post("/api/v2/me/reminders", { text: t, when: w }))} /></section>
  </div>`;
}
