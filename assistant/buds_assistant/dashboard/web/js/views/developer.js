import { html, useState, useEffect } from "../../vendor/htm-preact-standalone.module.js";
import { useStore, toast } from "../store.js";
import { api } from "../api.js";
import { EmptyState, when } from "../components/ui.js";

// Developer: the tools for tuning Sidekick. Not part of the everyday UI.
export function Developer() {
  const models = useStore((s) => s.ui.models);
  const live = useStore((s) => s.decisions);
  const [log, setLog] = useState([]);
  useEffect(() => { api.get("/api/v2/autopilot/feed?n=500").then(setLog).catch((e) => toast(e.message)); }, [live.length]);
  return html`<div class="stack" style="gap:var(--s5)"><h2>Developer</h2>
    <p class="muted">The original analysis dashboard is still here: <a href="/dev/">raw events, latency and settings</a>.</p>
    <section class="stack" style="gap:6px"><h3>Models</h3>${Object.entries(models).map(([k, v]) => html`<p class="row"><span style="width:90px">${k}</span><span class=${`pill ${v === "ready" ? "ok" : ""}`}>${v}</span></p>`)}</section>
    <section class="stack" style="gap:6px"><h3>Latency</h3><p class="muted small">No timing data is published yet. Per-stage timings arrive with the hardening pass.</p></section>
    <section class="stack" style="gap:6px"><h3>Autopilot decisions</h3>
      ${!log.length ? html`<${EmptyState} icon="autopilot" title="No decisions yet" text="Turn on Autopilot and talk. Every whisper and every silence is listed here with its reason." />`
        : html`<div class="table-wrap"><table class="dev"><thead><tr><th>When</th><th>Trigger</th><th>Outcome</th><th>Why or what</th><th>Person</th></tr></thead><tbody>
          ${[...log].reverse().map((d) => html`<tr><td class="num">${when(d.ts)}</td><td>${d.trigger}</td><td>${d.outcome}</td><td>${d.text || d.reason_text || d.reason}</td><td>${d.person || ""}</td></tr>`)}</tbody></table></div>`}</section></div>`;
}
