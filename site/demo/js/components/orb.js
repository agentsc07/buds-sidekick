import { html } from "../../vendor/htm-preact-standalone.module.js";
import { useStore } from "../store.js";
import { useTick } from "./live.js";

// Orb : Sidekick as a living light. Its state is the mode, plus "speaking" right after it answers and "active" while someone talks.
export function Orb() {
  const [mode, segs, replies] = useStore((s) => [s.ui.mode, s.segments, s.replies]);
  useTick(1000);
  const now = Date.now() / 1000;
  const last = replies[replies.length - 1];
  const speaking = last && now - last.ts < 4;
  const active = segs.length && now - segs[segs.length - 1].t1 < 3;
  const state = speaking ? "speaking" : { listen: "listening" }[mode] || mode;
  return html`<div class="orb" data-state=${state} data-active=${active ? "true" : "false"} role="img" aria-label=${`Sidekick is ${state}`}>
    <span class="core"></span><i class="o1"></i><i class="o2"></i><i class="o3"></i></div>`;
}
