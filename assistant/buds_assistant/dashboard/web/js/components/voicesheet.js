import { html, useState, useEffect } from "../../vendor/htm-preact-standalone.module.js";
import { useStore, toast, loadPeople } from "../store.js";
import { api } from "../api.js";
import { Button, Dialog, Icon, Segmented } from "./ui.js";

const SAY = "Please send me the quarterly budget before the meeting on Friday. I think we should move the review to Thursday afternoon.";

// VoiceSheet : record a voice, hear it back, and save it as a new person or add it to someone who already exists.
// Props: open, onClose, personId (preselect "add to this person"), onDone.
export function VoiceSheet({ open, onClose, personId, onDone }) {
  const people = useStore((s) => s.people);
  const [mode, setMode] = useState(personId ? "existing" : "new");
  const [who, setWho] = useState(personId || "");
  const [name, setName] = useState("");
  const [ok, setOk] = useState(false);
  const [src, setSrc] = useState("buds");
  const [secs, setSecs] = useState(0);
  const [phase, setPhase] = useState("idle");        // idle | recording | saving | done
  useEffect(() => { if (open) { setMode(personId ? "existing" : "new"); setWho(personId || ""); setName(""); setOk(false); setPhase("idle"); setSecs(0); } }, [open, personId]);
  useEffect(() => { if (phase !== "recording") return; const i = setInterval(() => setSecs((s) => s + 1), 1000); return () => clearInterval(i); }, [phase]);
  const total = 12;
  const ready = mode === "existing" ? !!who : name.trim() && ok;
  const record = async () => {
    setPhase("recording"); setSecs(0);
    const body = { placement: src === "buds" ? "ear" : "remote", source: src, seconds: total };
    try {
      if (mode === "existing") await api.post("/api/v2/voices/add", { ...body, person_id: +who });
      else await api.post("/api/v2/voices/new", { ...body, name: name.trim(), consent: "Agreed to be remembered (confirmed in the dashboard)" });
      setPhase("done"); loadPeople(); onDone && onDone();
    } catch (e) { toast(e.message); setPhase("idle"); }
  };
  const hear = () => { const a = new Audio("/api/v2/voices/last-clip?" + Date.now()); a.play().catch(() => toast("I couldn't play that.")); };
  return html`<${Dialog} open=${open} title="Add a voice" onClose=${onClose} actions=${html`<${Button} variant="quiet" onClick=${onClose}>${phase === "done" ? "Close" : "Cancel"}</${Button}>`}>
    <${Segmented} label="Who" value=${mode} onChange=${setMode} options=${[{ value: "new", label: "New person" }, { value: "existing", label: "Add to someone I know" }]} />
    ${mode === "new" ? html`<div class="field"><label for="vn">Name</label><input id="vn" type="text" value=${name} onInput=${(e) => setName(e.target.value)} /></div>
        <label class="row" style="align-items:flex-start"><input type="checkbox" checked=${ok} onChange=${(e) => setOk(e.target.checked)} />
          <span>This person knows I'll remember their voice and what they say, and has agreed.</span></label>`
      : html`<div class="field"><label for="vw">Person</label><select id="vw" value=${who} onChange=${(e) => setWho(e.target.value)}><option value="">Choose…</option>
          ${people.map((p) => html`<option value=${p.id} selected=${String(p.id) === String(who)}>${p.name}</option>`)}</select></div>`}
    <div class="row wrap"><span class="small muted">Record with</span><${Segmented} label="Microphone" value=${src} onChange=${setSrc} options=${[{ value: "buds", label: "Buds" }, { value: "laptop", label: "Mac" }]} /></div>
    <p class="small muted">Ask them to read this at a normal pace, about ${total} seconds:</p><blockquote class="reading voice" style="margin:0">${SAY}</blockquote>
    ${phase === "recording" && html`<div><div class="bar big"><i style=${`width:${Math.min(100, (secs / total) * 100)}%`}></i></div><p class="small muted num" aria-live="polite">Listening… ${secs} of ${total} seconds</p></div>`}
    ${phase === "done" && html`<div class="row"><${Icon} name="check" /> Saved. <button class="btn quiet sm playbtn" onClick=${hear}><${Icon} name="ear" />Hear it back</button></div>`}
    <div style="justify-self:center">${phase !== "done" && html`<button class="recbtn" aria-pressed=${phase === "recording"} disabled=${!ready || phase === "recording"} aria-label="Start recording" onClick=${record}><${Icon} name="mic" /></button>`}</div>
  </${Dialog}>`;
}
