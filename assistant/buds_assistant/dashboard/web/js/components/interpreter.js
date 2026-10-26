// The interpreter panel: what they said, what you heard, how far behind we are.
import { html, useState } from "../../vendor/htm-preact-standalone.module.js";
import { useStore, toast } from "../store.js";
import { api } from "../api.js";
import { Icon, Button, Segmented } from "./ui.js";

const WHY = { echo: "Skipped: that was our own speaker", caught_up: "Skipped a short phrase to catch up", unclear: "Unclear: I did not want to guess" };
const LANG = { te: "Telugu", en: "English" };

export function InterpreterPanel() {
  const [ui, rows] = useStore((s) => [s.ui, s.translations]);
  const [typed, setTyped] = useState("");
  const m = ui.models;
  const ready = m.translate === "ready" && m.telugu === "ready";
  const last = [...rows].reverse().find((r) => !r.skipped && r.ok);
  const setWay = async (two_way) => { try { await api.post("/api/v2/interpreter", { two_way }); } catch (e) { toast(e.message); } };
  const send = async (e) => {
    e.preventDefault();
    if (!typed.trim()) return;
    try { const r = await api.post("/api/translate", { text: typed, src: "auto", speak: true }); if (!r.ok) toast(r.error || "I could not translate that."); setTyped(""); }
    catch (err) { toast(err.message); }
  };
  return html`<section class="interp stack" style="gap:var(--s4)">
    <div class="row wrap">
      <span class="small muted">${LANG[ui.interpreter?.from] || "Telugu"} → ${LANG[ui.interpreter?.to] || "English"}, in your ear</span>
      <span class="spacer"></span>
      ${!ready ? html`<span class="pill warn" aria-live="polite"><${Icon} name="alert" />Getting ready: ${m.translate !== "ready" ? "translation model" : "Telugu speech"}…</span>`
        : last ? html`<span class="pill ok num" title="Time from the end of a phrase to the start of its translation">${last.p50}s typical delay${last.behind > 4 ? `, ${last.behind}s behind` : ""}</span>`
        : html`<span class="pill ok">Listening for Telugu and English</span>`}
    </div>
    <div class="panes">
      <div><h3>What they said</h3>${!rows.length ? html`<p class="muted small">Phrases appear here as they are spoken.</p>` : null}</div>
      <div><h3>What you heard</h3></div>
    </div>
    <div class="pairs">${rows.slice(-12).map((r, i) => r.skipped
      ? html`<div class="pair skipped" key=${i}><p class="small muted"><${Icon} name="close" /> ${WHY[r.reason] || r.reason}</p></div>`
      : html`<div class="pair" key=${i}>
          <div><span class="pill">${LANG[r.src] || r.src}</span><p>${r.text}</p></div>
          <div>${r.ok ? html`<span class="pill">${LANG[r.dst] || r.dst}</span><p class="voice">${r.translated}</p>` : html`<p class="small" style="color:var(--bad)" role="alert">Could not translate: ${r.error}</p>`}</div></div>`)}</div>
    <form class="row" onSubmit=${send}><input type="text" aria-label="Type a phrase to translate" placeholder="Type a phrase to translate and speak it" value=${typed} onInput=${(e) => setTyped(e.target.value)} />
      <${Button} type="submit" variant="quiet" disabled=${!typed.trim()}>Translate</${Button}></form>
    <p class="small muted">Telugu recognition is experimental: it works best with clear speech close to the microphone. If it is unclear, Sidekick says so instead of guessing.</p>
  </section>`;
}

// Typed translation (always available): English <-> Telugu, optionally spoken. Shows the last result only.
export function TranslateBox() {
  const [typed, setTyped] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const send = async (e) => {
    e.preventDefault();
    if (!typed.trim() || busy) return;
    setBusy(true);
    try { const r = await api.post("/api/translate", { text: typed, src: "auto", speak: true }); if (!r.ok) toast(r.error || "I could not translate that."); else { setRes(r); setTyped(""); } }
    catch (err) { toast(err.message); }
    setBusy(false);
  };
  return html`<section class="translatebox stack" style="gap:var(--s2)" aria-label="Translate">
    <form class="row" onSubmit=${send}><input type="text" aria-label="Phrase to translate" placeholder="Translate English or Telugu, and hear it" value=${typed} onInput=${(e) => setTyped(e.target.value)} />
      <${Button} type="submit" variant="quiet" disabled=${!typed.trim() || busy}>${busy ? "Translating…" : "Translate"}</${Button}></form>
    ${res && html`<p class="voice" aria-live="polite"><span class="pill">${LANG[res.dst] || res.dst}</span> ${res.text}</p>`}
  </section>`;
}
