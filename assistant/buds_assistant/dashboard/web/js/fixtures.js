// Demo data (?demo=1): every view renders from this with no backend, for design review and browser checks.
// ?demo=1&state=standby|listen|autopilot|interpreter|private|disconnected|ollama-down
import { state, set } from "./store.js";

const now = () => Date.now() / 1000;
const base = { live_translation: true, interpreter: { two_way: false, from: "te", to: "en" }, memory_level: "remember", placement: "ear", route: "ear", conversation_id: 7, ring_seconds: 8,
  buds: { battery: { left: 82, right: 79, case: 64 }, wear: { L: "in_ear", R: "in_ear" } },
  models: { chat: "ready", embed: "ready", translate: "unloaded" }, autopilot: { enabled: false, sensitivity: "balanced", feed: [] }, banner: null, self_name: "Me" };
const STATES = {
  standby: { ...base, mode: "standby", conversation_id: null, ring_seconds: 0 },
  listen: { ...base, mode: "listen" },
  autopilot: { ...base, mode: "autopilot", autopilot: { enabled: true, sensitivity: "balanced", feed: [] } },
  interpreter: { ...base, mode: "interpreter", models: { chat: "ready", embed: "ready", translate: "ready" }, placement: "remote", route: "remote" },
  private: { ...base, mode: "private", conversation_id: null, ring_seconds: 0 },
  disconnected: { ...base, mode: "standby", conversation_id: null, buds: { battery: null, wear: { L: null, R: null } }, banner: "Buds not connected. Mode features that need them are paused until they reconnect." },
  "ollama-down": { ...base, mode: "listen", models: { chat: "unloaded", embed: "unloaded", translate: "unloaded" } },
};

const PEOPLE = [
  { id: 1, name: "Me", color: "#2f6fed", policy: "transcript", last_seen: now() - 120, segments: 41 },
  { id: 2, name: "Ravi", color: "#e0762b", policy: "transcript", last_seen: now() - 60, segments: 23 },
  { id: 3, name: "Priya", color: "#1a9c57", policy: "audio", last_seen: now() - 86400 * 2, segments: 12 },
  { id: 4, name: "Dev", color: "#9b59d0", policy: "none", last_seen: now() - 86400 * 9, segments: 0 },
];
const t = (s) => now() - s;
const SEGMENTS = [
  { speaker: "Ravi", person_id: 2, text: "Good morning everyone. Quick update on the budget before we start.", t0: t(210), t1: t(204), conf: 0.86, lang: "en" },
  { speaker: "Me", person_id: 1, is_self: true, text: "Morning Ravi. Go ahead.", t0: t(200), t1: t(198), conf: 0.93, lang: "en" },
  { speaker: "Priya", person_id: 3, text: "When is the demo? I need to book the room.", t0: t(150), t1: t(145), conf: 0.81, lang: "en" },
  { speaker: "Me", person_id: 1, is_self: true, text: "The demo is October fourteenth. I'll send the deck Friday.", t0: t(120), t1: t(114), conf: 0.9, lang: "en" },
  { speaker: "Speaker A", person_id: null, cluster: "Speaker A", text: "Excuse me, when does the parking permit expire?", t0: t(80), t1: t(75), conf: 0.31, lang: "en" },
  { speaker: "Ravi", person_id: 2, text: "About the Q3 report, I am still working on it.", t0: t(40), t1: t(35), conf: 0.88, lang: "en" },
];
const DECISIONS = [
  { trigger: "identity", outcome: "said", reason: null, reason_text: null, text: "Ravi. He owes you the Q3 report.", person: "Ravi", hint_id: 11, ts: t(209) },
  { trigger: "question", outcome: "said", reason: null, reason_text: null, text: "Demo is October 14, you said Tuesday.", person: "Priya", hint_id: 12, ts: t(144) },
  { trigger: "capture", outcome: "noted", reason: null, reason_text: null, text: "Noted: send the deck, Friday", person: "Me", hint_id: 13, fact_id: 91, ts: t(113) },
  { trigger: "question", outcome: "held_back", reason: "unknown_voice", reason_text: "Skipped: I don't know this voice", text: "", person: null, ts: t(74) },
  { trigger: "commitment", outcome: "held_back", reason: "too_soon", reason_text: "Skipped: too soon after the last whisper", text: "", person: "Ravi", ts: t(34) },
];
const LOOPS = [
  { id: 91, text: "send the deck", due: "Friday", person: "Me", owner: "Me" },
  { id: 92, text: "send the Q3 report", due: "Friday", person: "Ravi", owner: "Ravi" },
  { id: 93, text: "book the demo room", due: "Monday", person: "Priya", owner: "Priya" },
];
const LIBRARY = [
  { id: 7, title: "Budget catch-up", date: t(3600 * 3), people: ["Me", "Ravi", "Priya"], summary: "send the Q3 report · send the deck", marks: 2, segments: 24 },
  { id: 6, title: "Vendor call", date: t(86400 * 2), people: ["Me", "Priya"], summary: "Priya joined from finance last week", marks: 0, segments: 15 },
  { id: 5, title: "Conversation on Monday 28 Sep", date: t(86400 * 4), people: ["Me", "Ravi"], summary: "The trip was fine, busy as always", marks: 1, segments: 9 },
];
const SLOTS = [["L:single", "ask"], ["L:double", "replay"], ["L:triple", "private_toggle"], ["L:hold", "interpreter_toggle"],
  ["R:single", "mark"], ["R:double", "autopilot_toggle"], ["R:triple", "who"], ["R:hold", "listen_toggle"]];
const ACTIONS = [["ask", "Ask the assistant"], ["replay", "Replay the last seconds"], ["catch_up", "Catch me up"], ["mark", "Mark this moment"],
  ["who", "Who is talking"], ["listen_toggle", "Listen on / off"], ["autopilot_toggle", "Autopilot on / off"], ["interpreter_toggle", "Interpreter on / off"],
  ["private_toggle", "Private on / off"], ["stop", "Stop speaking"]];

export function initDemo() {
  const q = new URLSearchParams(location.search).get("state") || "listen";
  const ui = JSON.parse(JSON.stringify(STATES[q] || STATES.listen));
  const live = ["listen", "autopilot", "interpreter", "ollama-down"].includes(q);
  const translations = q === "interpreter" ? [
    { src: "te", dst: "en", text: "రేపు మధ్యాహ్నం మన సమావేశం మూడు గంటలకు ఉంటుంది", translated: "Our meeting is at 3 o'clock tomorrow afternoon.", ok: true, p50: 4.4, behind: 0.0 },
    { skipped: true, reason: "echo" },
    { src: "te", dst: "en", text: "మీరు నాకు శుక్రవారం రిపోర్ట్ పంపగలరా", translated: "Can you send me the report on Friday?", ok: true, p50: 4.6, behind: 0.0 }] : [];
  if (q === "interpreter") { ui.interpreter = { two_way: false, from: "te", to: "en" }; ui.models.telugu = "ready"; }
  set({ ui, connection: "live", people: PEOPLE, peopleLoaded: true, translations, segments: live && q !== "interpreter" ? SEGMENTS : [], decisions: live && q !== "interpreter" ? DECISIONS : [] });
}

let sensitivity = "balanced", cats = { capture: true, question: true, commitment: true, mention: true, identity: true };
let slots = SLOTS.map(([gesture, action]) => ({ gesture, action }));
export async function demo(method, path, body) {
  const ok = { ok: true };
  if (path === "/api/v2/mode") { set({ ui: { ...state.ui, mode: body.mode, autopilot: { ...state.ui.autopilot, enabled: body.mode === "autopilot" } } }); return state.ui; }
  if (path === "/api/v2/memory-level") { set({ ui: { ...state.ui, memory_level: body.level } }); return state.ui; }
  if (path === "/api/v2/state") return state.ui;
  if (path.startsWith("/api/v2/autopilot/feed")) return state.decisions;
  if (path === "/api/v2/autopilot") { if (method === "PUT") { sensitivity = body.sensitivity || sensitivity; if (body.categories) cats = body.categories; } return { sensitivity, categories: cats, enabled: state.ui.autopilot.enabled }; }
  if (path === "/api/v2/gestures") { if (method === "PUT") body.slots.forEach((s) => (slots.find((x) => x.gesture === s.gesture).action = s.action)); return { slots: slots.map((s) => ({ ...s, label: ACTIONS.find((a) => a[0] === s.action)?.[1] })), actions: ACTIONS.map(([id, label]) => ({ id, label })), defaults: Object.fromEntries(SLOTS) }; }
  if (path === "/api/v2/gestures/reset") { slots = SLOTS.map(([gesture, action]) => ({ gesture, action })); return demo("GET", "/api/v2/gestures"); }
  if (path === "/api/v2/health") return { checks: [
    { id: "ollama", label: "Language model service", ok: true, detail: "Ollama is running.", fix: "" },
    { id: "models", label: "Language models", ok: false, detail: "Missing: gemma4:12b-mlx", fix: "Install with `ollama pull gemma4:12b-mlx`" },
    { id: "buds", label: "Galaxy Buds", ok: true, detail: "Simulated buds (no hardware).", fix: "" },
    { id: "speaker_model", label: "Voice recognition model", ok: true, detail: "Installed.", fix: "" },
    { id: "whisper", label: "Speech recognition", ok: true, detail: "Installed.", fix: "" }] };
  if (/^\/api\/v2\/voices\/\d+\/health/.test(path)) return { sources: { enrol: { samples: 4, own_min: 0.8, own_mean: 0.84 }, buds: { samples: 3, own_min: 0.72, own_mean: 0.8 } }, nearest_stranger: 0.41, verdict: "good", advice: "Your voice is recognised well on every microphone you set up." };
  if (path.startsWith("/api/v2/voices/")) return { added: 3, person_id: 9, sources: { buds: 3 }, removed: 0 };
  if (path === "/api/people") return PEOPLE;
  if (path === "/api/live") return SEGMENTS;
  if (path === "/api/v2/unnamed") return [{ label: "Speaker A", utterances: 3, last_text: "Excuse me, when does the parking permit expire?", seconds: 14.2 }];
  if (path.startsWith("/api/v2/unnamed/")) return { person_id: 9 };
  if (/^\/api\/v2\/people\/\d+\/forget-preview/.test(path)) return { segments: 23, facts: 4, voice_samples: 3, audio_files: 0, bookmarks: 1, hints: 6, people: 1 };
  if (/^\/api\/v2\/people\/\d+\/forget/.test(path)) return ok;
  if (/^\/api\/v2\/people\/\d+$/.test(path)) { const p = PEOPLE.find((x) => x.id === +path.split("/").pop()) || PEOPLE[1];
    return { person: p, facts: [{ id: 1, kind: "fact", text: "is the new finance lead" }], topics: ["budget", "report", "demo"], commitments: LOOPS.filter((l) => l.person === p.name),
      recent_conversations: LIBRARY.slice(0, 2).map((c) => ({ id: c.id, title: c.title, start: c.date })), last_seen: p.last_seen, brief: `Before you talk to ${p.name}: open: send the Q3 report by Friday. Last said: I am still working on it.` }; }
  if (path.startsWith("/api/v2/library/")) { const c = LIBRARY.find((x) => x.id === +path.split("/").pop()) || LIBRARY[0];
    return { card: c, transcript: SEGMENTS.map((s, i) => ({ ...s, id: i + 1, color: PEOPLE.find((p) => p.name === s.speaker)?.color })), bookmarks: [{ id: 1, ts: t(118), note: "" }], loops: LOOPS }; }
  if (path.startsWith("/api/v2/library")) { const q = new URLSearchParams(path.split("?")[1] || "").get("q"); return q ? LIBRARY.filter((c) => (c.title + c.summary).toLowerCase().includes(q.toLowerCase())) : LIBRARY; }
  if (path === "/api/v2/open-loops") return LOOPS;
  if (path === "/api/v2/me") { const e = (id, title, when_label, people = []) => ({ id, title, when_label, people }); return { sample: true,
    events: [e(1, "Demo prep", "today at 4 pm"), e(2, "Standup", "tomorrow at 10 am", ["Ravi"]), e(3, "Budget review", "Thursday at 2 pm", ["Priya"])],
    todos: [{ id: 1, text: "send the deck", due_text: "Friday", source: "promise" }, { id: 2, text: "Review the Q3 report", due_text: "Friday", source: "manual" }],
    reminders: [{ id: 1, text: "Call mum", when_label: "today at 7 pm" }] }; }
  if (path === "/api/v2/interpreter") { const cur = state.ui.interpreter || { from: "te", to: "en" }; let from = body.src || cur.from, to = body.dst || cur.to; if (from === to) { if (body.src) to = from === "te" ? "en" : "te"; else from = to === "te" ? "en" : "te"; } set({ ui: { ...state.ui, interpreter: { ...cur, from, to } } }); return { from, to }; }
  if (path === "/api/translate") return { ok: true, text: "ధన్యవాదాలు", src: "en", dst: "te" };
  if (path === "/api/v2/activity") return [{ ts: t(60), text: "Switched to Autopilot" }, { ts: t(900), text: "Changed settings" }, { ts: t(7200), text: "Forgot a person (4 lines, 1 notes deleted)" }];
  if (path === "/api/v2/gestures/try") return { on: !!body.on, seconds: 60 };
  if (path === "/api/v2/delete-everything") return { ok: true, deleted: {} };
  if (path === "/api/settings") return { ring_seconds: 8, placement: "auto", telugu_stt: false, speaker_threshold: 0.62, hint_min_gap: 20, hints_per_hour: 12, hint_max_words: 20, chat_model: "qwen3.5:4b-mlx", translate_model: "gemma4:12b-mlx", voice_en: "Samantha", voice_te: "Geeta", store_unknown: false };
  if (path === "/api/v2/setup/add-voice-sample") { await new Promise((r) => setTimeout(r, 900)); return { added: 5, total: 10 }; }
  if (path === "/api/v2/setup/calibrate") { await new Promise((r) => setTimeout(r, 900)); return { verdict: "fair", threshold: 0.58, self_min: 0.66, impostor_max: 0.5, summary: "Recognition works, but close calls are possible: you score at least 0.66, other voices up to 0.5. Uncertain voices will be shown as unsure." }; }
  if (path === "/api/v2/setup/status") return { done: true, has_me: true };
  if (path === "/api/v2/setup/mic-check") { await new Promise((r) => setTimeout(r, 900)); return { buds: { level_db: -24, snr_db: 22 }, mac: { level_db: -31, snr_db: 31 }, errors: {}, recommend: "remote", advice: "The Mac microphone heard more clearly. Sit near the Mac, or keep the buds out as a remote." }; }
  if (path === "/api/v2/setup/enroll-self") { await new Promise((r) => setTimeout(r, 900)); return { id: 1, seconds: 20 }; }
  return ok;
}
