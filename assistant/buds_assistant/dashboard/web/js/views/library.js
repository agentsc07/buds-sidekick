import { html, useState, useEffect } from "../../vendor/htm-preact-standalone.module.js";
import { useStore, colorFor, toast } from "../store.js";
import { api } from "../api.js";
import { go } from "../router.js";
import { Icon, Avatar, Segmented, EmptyState, when } from "../components/ui.js";

function Loop({ l, onChange }) {
  const [done, setDone] = useState(false);
  const tick = async () => {
    try { await api.post(`/api/v2/open-loops/${l.id}/done`); setDone(true); onChange && onChange();
      toast("Marked done", () => api.post(`/api/v2/open-loops/${l.id}/reopen`).then(() => { setDone(false); onChange && onChange(); })); }
    catch (e) { toast(e.message); }
  };
  return html`<label class=${`row loop ${done ? "done" : ""}`}><input type="checkbox" checked=${done} onChange=${tick} /><span>${l.text}${l.due ? html` <span class="muted">by ${l.due}</span>` : ""}</span><span class="spacer"></span><span class="small muted">${l.person || ""}</span></label>`;
}

function OpenLoops() {
  const me = useStore((s) => s.ui.self_name);
  const [loops, setLoops] = useState(null);
  const load = () => api.get("/api/v2/open-loops").then(setLoops).catch((e) => toast(e.message));
  useEffect(() => { load(); }, []);
  if (!loops) return html`<p class="muted">Loading…</p>`;
  if (!loops.length) return html`<${EmptyState} icon="check" title="No open promises" text="When you say 'I'll send it Friday' with Autopilot on, Sidekick writes it down and it appears here." />`;
  const mine = loops.filter((l) => l.person === (me || "Me")), theirs = loops.filter((l) => l.person !== (me || "Me"));
  return html`<div class="stack" style="gap:var(--s5)">
    <section class="stack" style="gap:6px"><h3>You promised</h3>${mine.length ? mine.map((l) => html`<${Loop} l=${l} key=${l.id} />`) : html`<p class="muted">Nothing open.</p>`}</section>
    <section class="stack" style="gap:6px"><h3>Others promised you</h3>${theirs.length ? theirs.map((l) => html`<${Loop} l=${l} key=${l.id} />`) : html`<p class="muted">Nothing open.</p>`}</section></div>`;
}

function Cards({ q }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { const h = setTimeout(() => api.get("/api/v2/library" + (q ? `?q=${encodeURIComponent(q)}` : "")).then(setRows).catch((e) => toast(e.message)), 200); return () => clearTimeout(h); }, [q]);
  if (!rows) return html`<p class="muted">Loading…</p>`;
  if (!rows.length) return q ? html`<${EmptyState} icon="search" title="Nothing matches" text=${`No conversation mentions "${q}". Try a name or a word someone said.`} />`
    : html`<${EmptyState} icon="library" title="No conversations yet" text="Turn on Listen on the Home screen. Conversations with people you've saved show up here afterwards." action=${html`<a href="#/home">Go to Home</a>`} />`;
  return html`<div class="convs">${rows.map((c) => html`<a class="conv" href=${"#/library/" + c.id}>
    <div><h3>${c.title}</h3><p class="small muted">${when(c.date)}${c.marks ? `, ${c.marks} marked` : ""}</p><p class="summary">${c.summary}</p></div>
    <div class="faces">${c.people.slice(0, 4).map((n) => html`<${Avatar} name=${n} color=${colorFor(n)} size=${28} />`)}</div></a>`)}</div>`;
}

export function Library({ embedded }) {
  const [tab, setTab] = useState("conversations");
  const [q, setQ] = useState("");
  if (embedded) return html`<div class="stack"><div class="field"><input type="search" aria-label="Search conversations" placeholder="What did people say about…" value=${q} onInput=${(e) => setQ(e.target.value)} /></div><${Cards} q=${q} /></div>`;
  return html`<div class="stack" style="gap:var(--s5)">
    <div class="row wrap"><h2>Library</h2><span class="spacer"></span>
      <${Segmented} label="Library section" value=${tab} onChange=${setTab} options=${[{ value: "conversations", label: "Conversations" }, { value: "loops", label: "Open promises" }]} /></div>
    ${tab === "conversations" ? html`<div class="field"><input type="search" aria-label="Search conversations" placeholder="What did people say about…" value=${q} onInput=${(e) => setQ(e.target.value)} /></div><${Cards} q=${q} />` : html`<${OpenLoops} />`}
  </div>`;
}

export function Conversation({ id }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { setD(null); api.get(`/api/v2/library/${id}`).then(setD).catch((e) => setErr(e.message)); }, [id]);
  if (err) return html`<${EmptyState} icon="alert" title="Can't open this conversation" text=${err} action=${html`<a href="#/library">Back to the library</a>`} />`;
  if (!d) return html`<p class="muted">Loading…</p>`;
  const marks = d.bookmarks.map((b) => b.ts);
  const marked = new Set(marks.map((ts) => { let best = null; for (const s of d.transcript) if (best == null || Math.abs(s.t1 - ts) < Math.abs(best.t1 - ts)) best = s; return best?.id; }));
  const items = d.loops.filter((l) => d.card.people.includes(l.person));
  return html`<div class="stack" style="gap:var(--s5)"><a class="small" href="#/library">All conversations</a>
    <div><h2>${d.card.title}</h2><p class="muted">${when(d.card.date)}, with ${d.card.people.join(", ")}</p></div>
    ${d.card.summary && html`<p class="voice brief">${d.card.summary}</p>`}
    <section class="stack" style="gap:6px"><h3>Action items</h3>${items.length ? items.map((l) => html`<${Loop} l=${l} key=${l.id} />`) : html`<p class="muted">None from this conversation.</p>`}</section>
    <section><h3>Transcript</h3><div class="convo">${d.transcript.map((s) => html`<div class=${`line plain ${marked.has(s.id) ? "marked" : ""}`} key=${s.id}>
      <${Avatar} name=${s.speaker || "?"} color=${s.color || colorFor(s.speaker)} unsure=${!s.speaker && !s.person_id} />
      <div class="said"><b>${s.speaker || s.cluster || "Unknown"}</b> <span class="small muted num">${when(s.t1)}</span>${marked.has(s.id) ? html` <span class="pill"><${Icon} name="mark" />Marked</span>` : ""}<p>${s.text}</p></div></div>`)}</div></section></div>`;
}
