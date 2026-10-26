import { html, useState, useEffect } from "../../vendor/htm-preact-standalone.module.js";
import { state, set, useStore, colorFor, toast, loadPeople } from "../store.js";
import { api } from "../api.js";
import { go } from "../router.js";
import { Icon, Button, Avatar, Dialog, EmptyState, Segmented, when } from "../components/ui.js";
import { VoiceSheet } from "../components/voicesheet.js";
import { Library } from "./library.js";

const POLICY = [{ value: "transcript", label: "Notes only" }, { value: "audio", label: "Notes and audio" }, { value: "none", label: "Don't remember" }];
const POLICY_HELP = { transcript: "Keeps what they say as text. No audio is saved.", audio: "Keeps the text and short audio clips of what they say.", none: "Shows them live but saves nothing about them." };

// NameDialog : consent is part of naming someone (plain words, required). Used for unnamed voices and for adding a person.
function NameDialog({ open, title, intro, onClose, onSave, saving, label }) {
  const people = useStore((s) => s.people);
  const [mode, setMode] = useState("new");
  const [name, setName] = useState("");
  const [who, setWho] = useState("");
  const [ok, setOk] = useState(false);
  useEffect(() => { if (open) { setName(""); setOk(false); setWho(""); setMode("new"); } }, [open]);
  const hear = () => { const a = new Audio(`/api/v2/unnamed/${encodeURIComponent(label)}/clip?` + Date.now()); a.play().catch(() => toast("I no longer have that recording.")); };
  const can = mode === "existing" ? !!who : name.trim() && ok;
  return html`<${Dialog} open=${open} title=${title} onClose=${onClose}
    actions=${html`<${Button} variant="quiet" onClick=${onClose}>Cancel</${Button}><${Button} disabled=${!can || saving} onClick=${() => onSave(mode === "existing" ? { person_id: +who } : { name: name.trim() })}>${saving ? "Saving…" : "Save"}</${Button}>`}>
    <p class="muted">${intro}</p>
    ${label && html`<div><button class="btn quiet sm playbtn" onClick=${hear}><${Icon} name="ear" />Hear this voice</button></div>`}
    ${people.length > 0 && html`<${Segmented} label="Who" value=${mode} onChange=${setMode} options=${[{ value: "new", label: "New person" }, { value: "existing", label: "Someone I know" }]} />`}
    ${mode === "existing" ? html`<div class="field"><label for="nw">Person</label><select id="nw" value=${who} onChange=${(e) => setWho(e.target.value)}><option value="">Choose…</option>${people.map((p) => html`<option value=${p.id} selected=${String(p.id) === String(who)}>${p.name}</option>`)}</select></div>`
      : html`<div class="field"><label for="nm">Name</label><input id="nm" type="text" value=${name} onInput=${(e) => setName(e.target.value)} /></div>
        <label class="row" style="align-items:flex-start"><input type="checkbox" checked=${ok} onChange=${(e) => setOk(e.target.checked)} />
          <span>This person knows Sidekick will remember their voice and what they say, and has agreed.</span></label>`}</${Dialog}>`;
}

function UnnamedTray() {
  const segLen = useStore((s) => s.segments.length);
  const [list, setList] = useState([]);
  const [target, setTarget] = useState(null);
  const refresh = () => api.get("/api/v2/unnamed").then(setList).catch(() => {});
  useEffect(() => { refresh(); }, [segLen]);
  if (!list.length) return null;
  const save = async (who) => {
    try { await api.post(`/api/v2/unnamed/${encodeURIComponent(target.label)}/name`, { ...who, consent: "Agreed to be remembered (confirmed in the dashboard)" });
      toast("Saved. I'll recognise this voice from now on."); setTarget(null); refresh(); loadPeople(); }
    catch (e) { toast(e.message); }
  };
  const dismiss = async (u) => { try { await api.post(`/api/v2/unnamed/${encodeURIComponent(u.label)}/dismiss`); refresh(); } catch (e) { toast(e.message); } };
  return html`<section class="tray"><h2>Voices I couldn't name</h2>
    <p class="muted small">Listen, then tell me who it is. I keep these for a few days and then forget them. Change that in Settings, Privacy.</p>
    <div class="tray-list">${list.map((u) => html`<div class="tray-one"><${Avatar} name="?" unsure size=${40} />
      <div><b>${u.label}</b><p class="small muted">${when(u.last_seen)}, ${u.utterances} ${u.utterances === 1 ? "time" : "times"}, ${u.seconds}s.${u.last_text ? ` "${u.last_text}"` : ""}</p></div>
      <${Button} size="sm" onClick=${() => setTarget(u)}>Who is this?</${Button}><button class="linkbtn" onClick=${() => dismiss(u)}>Not now</button></div>`)}</div>
    <${NameDialog} open=${!!target} label=${target?.label} title=${`Who is ${target?.label}?`} intro="Listen to the voice, then say who it is. I'll recognise them next time." onClose=${() => setTarget(null)} onSave=${save} /></section>`;
}

export function People() {
  const [people, ui] = useStore((s) => [s.people, s.ui]);
  const [loops, setLoops] = useState([]);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => { api.get("/api/v2/open-loops").then(setLoops).catch(() => {}); loadPeople(); }, []);
  const add = async (name) => {
    setSaving(true);
    try { await api.post("/api/people/enroll", { name, consent: "Agreed to be remembered (confirmed in the dashboard)", seconds: 12 });
      toast(`Saved ${name}.`); setAdding(false); loadPeople(); }
    catch (e) { toast(e.message); }
    setSaving(false);
  };
  return html`<div class="stack" style="gap:var(--s5)">
    <div class="row"><h2>People</h2><span class="spacer"></span><${Button} icon="plus" onClick=${() => setAdding(true)}>Add a person</${Button}></div>
    <${UnnamedTray} />
    ${!people.length ? html`<${EmptyState} icon="people" title="No one is saved yet" text="Start with your own voice, so Sidekick can tell you apart from everyone else."
        action=${html`<${Button} onClick=${() => go("setup")}>Set up my voice</${Button}>`} />`
      : html`<div class="people-grid">${people.map((p) => {
        const mine = loops.filter((l) => l.person === p.name);
        return html`<a class="person-card" href=${"#/people/" + p.id}>
          <${Avatar} name=${p.name} color=${p.color} size=${48} />
          <div><h3>${p.name}</h3><p class="small muted">${p.last_seen ? `Last talked ${when(p.last_seen)}` : "Not heard yet"}</p>
            <p class="small">${mine.length ? `${mine.length} open ${mine.length === 1 ? "promise" : "promises"}` : "Nothing open"}</p></div></a>`;
      })}</div>`}
    <${VoiceSheet} open=${adding} onClose=${() => setAdding(false)} onDone=${() => loadPeople()} />
    <section class="stack" style="gap:var(--s3)"><h2>Conversations</h2><${Library} embedded /></section>
  </div>`;
}

const VERDICT = { good: ["check", "Recognised well"], fair: ["alert", "Mostly recognised"], needs_more: ["alert", "Needs another recording"] };
const SRC = { buds: "Buds mic", laptop: "Mac mic", enrol: "First recording", other: "Other" };

// VoiceHealth : how well this voice is recognised, per microphone, in plain words, with the one action that helps.
function VoiceHealth({ pid, name }) {
  const [h, setH] = useState(null);
  const [rec, setRec] = useState(false);
  const load = () => api.get(`/api/v2/voices/${pid}/health`).then(setH).catch(() => setH(null));
  useEffect(() => { load(); }, [pid]);
  if (!h) return null;
  const [icon, word] = VERDICT[h.verdict] || VERDICT.needs_more;
  const forgetLearning = async () => { try { const r = await api.post(`/api/v2/voices/${pid}/forget-learning`); toast(r.removed ? "Forgot what I learned by listening" : "There was nothing to forget"); load(); } catch (e) { toast(e.message); } };
  return html`<section class="glass vhealth"><div class="sec-title"><h3>How well I know ${name}'s voice</h3><span class=${`verdict ${h.verdict}`}><${Icon} name=${icon} />${word}</span></div>
    <p class="muted">${h.advice}</p>
    ${Object.entries(h.sources).map(([k, v]) => html`<div class="vsrc"><span style="width:8.5em">${SRC[k] || k}</span><div class="bar"><i style=${`width:${Math.max(4, Math.min(100, v.own_min * 100))}%`} class=${v.own_min >= 0.7 ? "best" : ""}></i></div><span class="small muted num">${v.samples} ${v.samples === 1 ? "sample" : "samples"}</span></div>`)}
    <div class="row wrap"><${Button} onClick=${() => setRec(true)}>Record more</${Button}><${Button} variant="quiet" size="sm" onClick=${forgetLearning}>Forget what I learned by listening</${Button}></div>
    <${VoiceSheet} open=${rec} personId=${pid} onClose=${() => setRec(false)} onDone=${load} /></section>`;
}

// RenameName : the person's name with a pencil; click to edit in place.
function RenameName({ p, onDone, isSelf }) {
  const [edit, setEdit] = useState(false);
  const [name, setName] = useState(p.name);
  const save = async (e) => {
    e.preventDefault();
    try { await api.post(`/api/v2/people/${p.id}/rename`, { name }); setEdit(false); toast("Renamed"); onDone(); } catch (err) { toast(err.message); }
  };
  if (!edit) return html`<div class="row"><h2>${p.name}</h2>${!isSelf && html`<button class="iconbtn sm" aria-label=${`Rename ${p.name}`} title="Rename" onClick=${() => { setName(p.name); setEdit(true); }}><${Icon} name="pencil" /></button>`}</div>`;
  return html`<form class="row" onSubmit=${save}><input type="text" aria-label="New name" value=${name} onInput=${(e) => setName(e.target.value)} autofocus style="max-width:220px" />
    <${Button} type="submit" size="sm" disabled=${!name.trim()}>Save</${Button}><${Button} type="button" variant="quiet" size="sm" onClick=${() => setEdit(false)}>Cancel</${Button}></form>`;
}

export function Person({ id }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [preview, setPreview] = useState(null);
  const [typed, setTyped] = useState("");
  const self = useStore((s) => s.ui.self_name);
  const load = () => api.get(`/api/v2/people/${id}`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); load(); }, [id]);
  if (err) return html`<${EmptyState} icon="alert" title="This person is gone" text=${err} action=${html`<${Button} onClick=${() => go("people")}>Back to people</${Button}>`} />`;
  if (!d) return html`<p class="muted">Loading…</p>`;
  const p = d.person;
  const setPolicy = async (policy) => { try { await api.post(`/api/people/${id}/policy`, { policy }); setD({ ...d, person: { ...p, policy } }); toast("Saved"); } catch (e) { toast(e.message); } };
  const tick = async (l) => { try { await api.post(`/api/v2/open-loops/${l.id}/done`); setD({ ...d, commitments: d.commitments.filter((x) => x.id !== l.id) });
    toast("Marked done", () => api.post(`/api/v2/open-loops/${l.id}/reopen`).then(load)); } catch (e) { toast(e.message); } };
  const makeAssistant = async () => { try { await api.post(`/api/v2/people/${id}/make-assistant`); toast(`Done. ${p.name} is no longer listed, and what it "said" is removed.`); loadPeople(); go("people"); } catch (e) { toast(e.message); } };
  const askForget = async () => { try { setPreview(await api.post(`/api/v2/people/${id}/forget-preview`)); setTyped(""); } catch (e) { toast(e.message); } };
  const forget = async () => { try { await api.post(`/api/v2/people/${id}/forget`); setPreview(null); toast(`Forgot ${p.name}`); loadPeople(); go("people"); } catch (e) { toast(e.message); } };
  const n = preview || {};
  return html`<div class="stack" style="gap:var(--s5)">
    <a class="small" href="#/people">All people</a>
    <div class="row"><${Avatar} name=${p.name} color=${p.color} size=${64} /><div><${RenameName} p=${p} isSelf=${p.name === self} onDone=${() => { load(); loadPeople(); }} /><p class="muted">${p.last_seen || d.last_seen ? `Last talked ${when(d.last_seen)}` : "Not heard yet"}</p></div></div>
    ${d.assistant_like && html`<section class="glass row wrap"><span style="flex:1;min-width:220px"><b>This sounds like my own voice.</b> The mic may have picked me up while I was speaking. If so, I'll stop listing it as a person and forget what it "said".</span>
      <${Button} onClick=${makeAssistant}>Yes, that's Sidekick</${Button}></section>`}
    <${VoiceHealth} pid=${id} name=${p.name} />
    <p class="voice brief">${d.brief}</p>
    <section class="stack" style="gap:8px"><h3>Open promises</h3>
      ${!d.commitments.length ? html`<p class="muted">Nothing open.</p>` : d.commitments.map((l) => html`<label class="row loop"><input type="checkbox" onChange=${() => tick(l)} /><span>${l.text}${l.due ? html` <span class="muted">by ${l.due}</span>` : ""}</span></label>`)}</section>
    ${d.facts.length ? html`<section class="stack" style="gap:8px"><h3>What I know</h3>${d.facts.filter((f) => f.kind !== "commitment").map((f) => html`<p>${p.name} ${f.text}</p>`)}</section>` : null}
    ${d.topics.length ? html`<section><h3>Talks about</h3><p class="muted">${d.topics.join(", ")}</p></section>` : null}
    <section class="stack" style="gap:8px"><h3>Recent conversations</h3>
      ${d.recent_conversations.length ? d.recent_conversations.map((c) => html`<a href=${"#/library/" + c.id}>${c.title || "Conversation"}, ${when(c.start)}</a>`) : html`<p class="muted">None yet.</p>`}</section>
    <section class="stack" style="gap:8px"><h3>What Sidekick remembers about ${p.name}</h3>
      <${Segmented} label="Remember setting" value=${p.policy} options=${POLICY} onChange=${setPolicy} /><p class="small muted">${POLICY_HELP[p.policy]}</p></section>
    <section class="row wrap"><${Button} variant="danger" onClick=${askForget}>Forget ${p.name}</${Button}>
      ${p.name !== self && html`<${Button} variant="quiet" onClick=${makeAssistant} title="Use this if ${p.name} is really the assistant's own voice, picked up by the mic">This is Sidekick's own voice</${Button}>`}</section>
    <${Dialog} open=${!!preview} title=${`Forget ${p.name}?`} onClose=${() => setPreview(null)}
      actions=${html`<${Button} variant="quiet" onClick=${() => setPreview(null)}>Keep</${Button}><${Button} variant="danger" disabled=${typed.trim().toLowerCase() !== p.name.toLowerCase()} onClick=${forget}>Forget ${p.name} for good</${Button}>`}>
      <p>This deletes ${n.segments || 0} saved ${n.segments === 1 ? "line" : "lines"}, ${n.facts || 0} ${n.facts === 1 ? "note" : "notes"}, ${n.audio_files || 0} audio ${n.audio_files === 1 ? "file" : "files"} and ${n.voice_samples || 0} voice ${n.voice_samples === 1 ? "sample" : "samples"}. It cannot be undone.</p>
      <div class="field"><label for="ty">Type ${p.name} to confirm</label><input id="ty" type="text" value=${typed} onInput=${(e) => setTyped(e.target.value)} /></div></${Dialog}>
  </div>`;
}
