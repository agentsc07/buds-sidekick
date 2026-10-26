import { html, useState, useEffect } from "../../vendor/htm-preact-standalone.module.js";
import { useStore, toast } from "../store.js";
import { api } from "../api.js";
import { go } from "../router.js";
import { useTryMode } from "../hooks.js";
import { Icon, Button, Segmented } from "../components/ui.js";
import { Conversation } from "../components/live.js";

const STEPS = ["Check", "Connect", "Mic check", "Your voice", "Gestures", "Privacy", "Try it"];
const READING = "I'm setting up my assistant. Today is a good day to plan the week: the budget review is on Thursday, I'll send the report on Friday, and then we can talk about the demo. Please remind me if I forget anything important.";
const GESTURES = [["L:single", "Left, single tap", "Ask"], ["L:double", "Left, double tap", "Replay"], ["L:triple", "Left, triple tap", "Private"], ["L:hold", "Left, touch and hold", "Translate (experimental, off)"],
  ["R:single", "Right, single tap", "Mark"], ["R:double", "Right, double tap", "Autopilot"], ["R:triple", "Right, triple tap", "Who is talking"], ["R:hold", "Right, touch and hold", "Listen"]];

function Check({ next }) {
  const [checks, setChecks] = useState(null);
  const [dl, setDl] = useState({});
  const running = Object.values(dl).some((x) => x.state === "running");
  const run = () => { setChecks(null); api.get("/api/v2/health").then((r) => setChecks(r.checks)); };
  useEffect(run, []);
  useEffect(() => {                                                // follow the downloads, then re-check when they finish
    if (!running) return;
    const i = setInterval(async () => { try { const r = await api.get("/api/v2/setup/download"); setDl(r.items); if (!Object.values(r.items).some((x) => x.state === "running")) run(); } catch (e) {} }, 1000);
    return () => clearInterval(i);
  }, [running]);
  const start = async () => { try { setDl((await api.post("/api/v2/setup/download", {})).items); } catch (e) { toast(e.message); } };
  const todo = checks && checks.some((c) => c.downloadable);
  const items = Object.entries(dl);
  return html`<div class="stack"><h2>Is everything ready?</h2>
    ${!checks ? html`<p class="muted">Checking…</p>` : checks.map((c) => html`<div class=${`health ${c.ok ? "ok" : "bad"}`}><${Icon} name=${c.ok ? "check" : "alert"} />
      <div><b>${c.label}</b><p class="small muted">${c.detail}</p>${!c.ok && html`<p class="small fix">${c.fix}</p>`}</div></div>`)}
    ${items.length > 0 && html`<div class="stack" aria-live="polite">${items.map(([name, x]) => html`<div class="meter"><span>${name}</span>
      <div class="bar"><i style=${`width:${x.pct || 0}%`} class=${x.state === "done" ? "best" : ""}></i></div>
      <span class="small muted">${x.state === "failed" ? "Failed: " + x.error : x.state === "done" ? "Ready" : (x.pct || 0) + "%"}</span></div>`)}
      ${running && html`<p class="small muted">The language skills are a few gigabytes. You can keep going and come back, it carries on in the background.</p>`}</div>`}
    <div class="row"><${Button} variant="quiet" onClick=${run}>Check again</${Button}>
      ${todo && !running && html`<${Button} icon="check" onClick=${start}>Download what is missing</${Button}>`}
      <${Button} onClick=${next}>Continue</${Button}></div></div>`;
}

function Connect({ next }) {
  const buds = useStore((s) => s.ui.buds);
  const on = !!buds.battery;
  return html`<div class="stack"><h2>Connect your buds</h2>
    <p>Turn off Bluetooth on your phone first. The buds can only talk to one device at a time. Then connect them to this Mac in System Settings, Bluetooth.</p>
    <div class=${`health ${on ? "ok" : "bad"}`}><${Icon} name=${on ? "check" : "alert"} /><div><b>${on ? "Buds connected" : "Waiting for your buds"}</b>
      ${on && html`<p class="small muted">Battery: left ${buds.battery.left}%, right ${buds.battery.right}%, case ${buds.battery.case}%</p>`}</div></div>
    <div class="row"><${Button} onClick=${next}>${on ? "Continue" : "Skip for now"}</${Button}></div></div>`;
}

function MicCheck({ next }) {
  const [state, setState] = useState("idle");
  const [r, setR] = useState(null);
  const run = async () => { setState("running"); try { setR(await api.post("/api/v2/setup/mic-check", { seconds: 6 })); setState("done"); } catch (e) { toast(e.message); setState("idle"); } };
  const bar = (label, m, best) => html`<div class="meter"><span>${label}</span><div class="bar"><i style=${`width:${m ? Math.min(100, m.snr_db * 2.5) : 0}%`} class=${best ? "best" : ""}></i></div><span class="small muted num">${m ? `${m.snr_db} dB` : "not available"}</span></div>`;
  return html`<div class="stack"><h2>Which microphone hears people best?</h2>
    <p>Ask someone to talk about 1 metre from you for a few seconds. Sidekick listens through the buds and through the Mac and compares how clearly each one hears.</p>
    ${state === "idle" && html`<${Button} icon="mic" onClick=${run}>Start the 6 second check</${Button}>`}
    ${state === "running" && html`<p class="voice" aria-live="polite">Listening for 6 seconds, then 6 more…</p>`}
    ${r && html`<div class="stack">${bar("Buds", r.buds, r.recommend === "ear")}${bar("Mac", r.mac, r.recommend === "remote")}<p class="voice">${r.advice}</p></div>`}
    <div class="row">${r && html`<${Button} variant="quiet" onClick=${run}>Check again</${Button}>`}<${Button} onClick=${next}>${r ? "Continue" : "Skip for now"}</${Button}></div></div>`;
}

const CHECK_TEXT = "Please send me the quarterly budget before the meeting on Friday. I think we should move the review to Thursday afternoon, and then walk through the numbers together.";

// Timed(): run a recording action with a visible countdown.
function useTimed(seconds) {
  const [state, setState] = useState("idle");
  const [secs, setSecs] = useState(0);
  useEffect(() => { if (state !== "recording") return; const i = setInterval(() => setSecs((s) => s + 1), 1000); return () => clearInterval(i); }, [state]);
  const run = async (fn) => { setState("recording"); setSecs(0); try { const r = await fn(); setState("idle"); return r; } catch (e) { toast(e.message); setState("idle"); } };
  return { state, secs, pct: Math.min(100, (secs / seconds) * 100), run };
}

// VoiceCheck: more voice samples (other microphone) and a held-out check that tells you how well you are recognised.
function VoiceCheck() {
  const more = useTimed(20), check = useTimed(15);
  const [report, setReport] = useState(null);
  const addBuds = async () => { const r = await more.run(() => api.post("/api/v2/setup/add-voice-sample", { placement: "ear", seconds: 20 })); if (r) toast(`Added ${r.added} voice samples from the buds`); };
  const calibrate = async () => { const r = await check.run(() => api.post("/api/v2/setup/calibrate", { seconds: 15 })); if (r) setReport(r); };
  const busy = more.state === "recording" || check.state === "recording";
  return html`<div class="stack voicecheck"><h3>How well do I know your voice?</h3>
    <p class="muted small">Buds and Mac microphones make you sound different. Record on the buds too, then run the check.</p>
    <div class="row wrap"><${Button} variant="quiet" disabled=${busy} onClick=${addBuds}>Add a sample from my buds (20 s)</${Button}>
      <${Button} variant="quiet" disabled=${busy} onClick=${calibrate}>Check recognition (15 s)</${Button}></div>
    ${more.state === "recording" && html`<div><p class="small">Put your buds in and read the sentence above again, or just talk.</p><div class="bar big"><i style=${`width:${more.pct}%`}></i></div></div>`}
    ${check.state === "recording" && html`<div><p class="small">Read this out loud:</p><blockquote class="voice reading">${CHECK_TEXT}</blockquote><div class="bar big"><i style=${`width:${check.pct}%`}></i></div></div>`}
    ${report && html`<div class=${`health ${report.verdict === "poor" ? "bad" : "ok"}`}><${Icon} name=${report.verdict === "poor" ? "alert" : "check"} /><div><b>${{ good: "Recognition works well", fair: "Recognition works, with some close calls", poor: "I can't reliably tell voices apart here" }[report.verdict]}</b>
      <p class="small muted">${report.summary}</p><p class="small muted num">Match threshold set to ${report.threshold}</p></div></div>`}</div>`;
}

function Voice({ next }) {
  const [state, setState] = useState("idle");
  const [secs, setSecs] = useState(0);
  const me = useStore((s) => s.people.some((p) => p.name === s.ui.self_name) && s.ui.voice_ready !== false);
  useEffect(() => { if (state !== "recording") return; const i = setInterval(() => setSecs((s) => s + 1), 1000); return () => clearInterval(i); }, [state]);
  const record = async () => {
    setState("recording"); setSecs(0);
    try { await api.post("/api/v2/setup/enroll-self", { seconds: 20 }); setState("done"); toast("Saved your voice"); }
    catch (e) { toast(e.message); setState("idle"); }
  };
  return html`<div class="stack"><h2>Teach Sidekick your voice</h2>
    <p>This is how Sidekick tells you apart from everyone else, and how it knows a command is really from you. Read this out loud at a normal pace:</p>
    <blockquote class="voice reading">${READING}</blockquote>
    ${state === "recording" && html`<div><div class="bar big"><i style=${`width:${Math.min(100, secs * 5)}%`}></i></div><p class="small muted num" aria-live="polite">${secs} of 20 seconds</p></div>`}
    ${state === "done" && html`<p class="row"><${Icon} name="check" /> Saved. I'll recognise you from now on.</p>`}
    ${(state === "done" || me) && state !== "recording" && html`<${VoiceCheck} />`}
    <div class="row">${state === "idle" && !me && html`<${Button} icon="mic" onClick=${record}>Record 20 seconds</${Button}>`}
      ${me && state !== "recording" && state !== "done" && html`<p class="muted">Your voice is already saved.</p>`}
      <${Button} variant=${state === "done" || me ? "" : "quiet"} disabled=${state === "recording"} onClick=${next}>${state === "done" || me ? "Continue" : "Skip for now"}</${Button}></div></div>`;
}

function Practice({ next }) {
  useTryMode(true);
  const tokens = useStore((s) => s.tokens);
  const [seen, setSeen] = useState({});
  useEffect(() => {
    const t = tokens[tokens.length - 1]; if (!t) return;
    const g = t.token.replace(/_(start|end)$/, ""); if (t.token.endsWith("_end")) return;
    setSeen((s) => ({ ...s, [g]: true }));
  }, [tokens.length]);
  const n = Object.keys(seen).length;
  return html`<div class="stack"><h2>Learn the gestures</h2>
    <p>Try each one on your buds now. Nothing will happen except a tick here. ${n}/8 done.</p>
    <div class="practice">${GESTURES.map(([g, label, what]) => html`<div class=${`pg ${seen[g] ? "got" : ""}`}><${Icon} name=${seen[g] ? "check" : "plus"} /><div><b>${label}</b><p class="small muted">${what}</p></div></div>`)}</div>
    <div class="row"><${Button} onClick=${next}>${n === 8 ? "Continue" : "Skip for now"}</${Button}></div></div>`;
}

function Privacy({ next }) {
  const level = useStore((s) => s.ui.memory_level);
  const set = async (l) => { try { await api.post("/api/v2/memory-level", { level: l }); } catch (e) { toast(e.message); } };
  return html`<div class="stack"><h2>What should Sidekick remember?</h2>
    <${Segmented} label="Memory" value=${level === "recording" ? "remember" : level} onChange=${set} options=${[{ value: "remember", label: "Remember conversations" }, { value: "live", label: "Don't save anything" }]} />
    <ul class="plain-list"><li>Voices you haven't named are never saved.</li><li>Recording raw audio is off. You switch it on yourself, for one conversation at a time.</li><li>Everything stays on this Mac. You can delete it all in Settings.</li></ul>
    <div class="row"><${Button} onClick=${next}>Continue</${Button}></div></div>`;
}

function TryIt({ done }) {
  const mode = useStore((s) => s.ui.mode);
  const [saving, setSaving] = useState(false);
  const start = async () => { try { await api.post("/api/v2/mode", { mode: "autopilot" }); } catch (e) { toast(e.message); } };
  const finish = async () => { setSaving(true); try { await api.post("/api/v2/setup/done"); } catch (e) { toast(e.message); } go("home"); };
  return html`<div class="stack"><h2>Try it</h2>
    <p>Turn on Autopilot, then say: <b class="voice">"I'll send the report on Friday."</b> Sidekick will whisper that it noted it, and it shows up below.</p>
    ${mode !== "autopilot" ? html`<div><${Button} icon="autopilot" onClick=${start}>Turn on Autopilot</${Button}></div>` : html`<p class="row"><${Icon} name="check" /> Autopilot is on.</p>`}
    <${Conversation} limit=${5} />
    <div class="row"><${Button} disabled=${saving} onClick=${finish}>Finish setup</${Button}></div></div>`;
}

export function Setup() {
  const [i, setI] = useState(() => { const q = new URLSearchParams(location.search).get("step"); if (q != null) return Math.min(+q, STEPS.length - 1); try { return Math.min(+localStorage.getItem("setupStep") || 0, STEPS.length - 1); } catch (e) { return 0; } });
  const to = (n) => { setI(n); try { localStorage.setItem("setupStep", n); } catch (e) { /* private window */ } };
  const next = () => to(Math.min(i + 1, STEPS.length - 1));
  const Step = [Check, Connect, MicCheck, Voice, Practice, Privacy, TryIt][i];
  return html`<div class="setup"><ol class="steps" aria-label="Setup steps">${STEPS.map((s, n) => html`<li aria-current=${n === i ? "step" : undefined} class=${n < i ? "past" : ""}>${s}</li>`)}</ol>
    <div class="step"><${Step} next=${next} done=${() => go("home")} /></div>
    <div class="row"><${Button} variant="quiet" size="sm" disabled=${i === 0} onClick=${() => to(i - 1)}>Back</${Button}><span class="spacer"></span><a class="small" href="#/home">Skip setup</a></div></div>`;
}
