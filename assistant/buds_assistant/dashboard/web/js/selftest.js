// Browser self-test for the store's event handling. Run headless: tests/test_frontend_selftest.py loads selftest.html and reads #out.
import { state, set, apply, ingestHello } from "./store.js";

const results = [];
const check = (name, ok) => results.push(`${ok ? "PASS" : "FAIL"} ${name}`);
const seg = (seq, t0, text = "hi") => ({ seq, ts: 1000 + seq, type: "segment", data: { t0, t1: t0 + 1, speaker: "Ravi", text } });
const reset = () => set({ lastSeq: 0, segments: [], decisions: [], replies: [], marks: 0, toasts: [] });

reset();
const hello = [seg(1, 10), seg(2, 20), { seq: 3, ts: 1003, type: "autopilot_decision", data: { hint_id: 7, outcome: "said", trigger: "identity", text: "Ravi." } }];
ingestHello(hello); ingestHello(hello);
check("a reconnect replay does not duplicate transcript lines", state.segments.length === 2);
check("a reconnect replay does not duplicate decisions", state.decisions.length === 1);

apply({ seq: 4, ts: 1004, type: "autopilot_decision", data: { hint_id: 7, outcome: "held_back", reason: "stale", trigger: "identity" } });
check("a later verdict replaces the whisper's row", state.decisions.length === 1 && state.decisions[0].outcome === "held_back" && state.decisions[0].text === "Ravi.");

apply({ seq: 5, ts: 1005, type: "conversation_started", data: { id: 2 } });
check("a new conversation starts with an empty transcript and feed", state.segments.length === 0 && state.decisions.length === 0);

ingestHello([seg(1, 5)]);
check("a restarted server (lower numbering) is accepted from scratch", state.segments.length === 1);

reset();
apply({ seq: 1, ts: 1, type: "bookmark", data: {} });
check("an old bookmark replayed from history counts but does not pop a toast", state.marks === 1 && state.toasts.length === 0);
apply({ seq: 2, ts: Date.now() / 1000, type: "bookmark", data: {} });
check("a fresh bookmark shows its toast", state.toasts.length === 1);

document.getElementById("out").textContent = results.join("\n") + `\nDONE ${results.every((r) => r.startsWith("PASS")) ? "ALL-PASS" : "SOME-FAILED"}`;
