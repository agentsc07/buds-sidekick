// Shared UI parts. Each component's props and states are listed above it.
import { html, useEffect, useRef } from "../../vendor/htm-preact-standalone.module.js";
import { state, useStore, dismissToast } from "../store.js";

const ICONS = {
  home: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  people: "M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 20c0-3.5 3.6-6 8-6s8 2.5 8 6",
  library: "M5 4h4v16H5zM11 4h4v16h-4zM17.5 5l3.5 1-3.5 14-3.5-1z",
  settings: "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM19 12l2-1.2-2-3.4-2.2.8-1.8-1L14.6 4h-4l-.4 3.2-1.8 1L6.2 7.4 4.2 10.8 6 12l-.1 2 .1 0-1.8 1.2 2 3.4 2.2-.8 1.8 1 .4 3.2h4l.4-3.2 1.8-1 2.2.8 2-3.4L17 14z",
  ear: "M7 10a5 5 0 0 1 10 0c0 3-3 3.5-3 6.5a2.5 2.5 0 0 1-5 0M10 10a2 2 0 0 1 4 0",
  mic: "M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM6 11a6 6 0 0 0 12 0M12 17v4",
  autopilot: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  translate: "M4 5h9M8.5 3v2M6 5c.5 4 3 7 6 8M12 5c-.7 4-3.5 7-7 8.5M14 21l4-9 4 9M15.5 18h5",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  rewind: "M11 6L4 12l7 6zM20 6l-7 6 7 6z",
  mark: "M7 3h10v18l-5-4-5 4z",
  catchup: "M4 6h16M4 12h16M4 18h9",
  check: "M5 12.5l4.5 4.5L19 7.5",
  undo: "M9 7L4 12l5 5M4 12h10a6 6 0 0 1 0 12",
  up: "M7 11v9H4v-9zM7 11l4-8c1.5 0 2.5 1.3 2 3l-.7 3H19a2 2 0 0 1 2 2.4l-1.4 6.5a2 2 0 0 1-2 1.6H7",
  down: "M17 13V4h3v9zM17 13l-4 8c-1.5 0-2.5-1.3-2-3l.7-3H5a2 2 0 0 1-2-2.4L4.4 6.5a2 2 0 0 1 2-1.6H17",
  ask: "M4 5h16v11H9l-5 4z",
  battery: "M3 8h16v8H3zM21 11v2",
  alert: "M12 3l10 18H2zM12 10v5M12 18v.5",
  plus: "M12 5v14M5 12h14",
  close: "M6 6l12 12M18 6L6 18",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  touch: "M9 11V5a2 2 0 0 1 4 0v6M13 10a2 2 0 0 1 4 0v2M17 12a2 2 0 0 1 3 1v3c0 3-2 5-6 5h-2c-3 0-4-1-6-4l-2-3a2 2 0 0 1 3-2l2 2",
  pencil: "M4 20l4-1 11-11-3-3L5 16zM14 6l3 3",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
};

// Icon { name } : 24px line icon, inherits colour.
export const Icon = ({ name }) => html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${ICONS[name] || ""} /></svg>`;

// Button { variant: "" | "quiet" | "danger", size: "" | "sm", icon, disabled, onClick }
export const Button = ({ variant = "", size = "", icon, children, ...rest }) =>
  html`<button class=${`btn ${variant} ${size}`} ...${rest}>${icon && html`<${Icon} name=${icon} />`}${children}</button>`;

export const MODE_LABEL = { standby: "Standby", listen: "Listening", autopilot: "Autopilot", interpreter: "Interpreter", private: "Private" };
// ModeChip { mode } : the always-visible current mode (colour + word).
export const ModeChip = ({ mode }) => html`<span class="chip" data-mode=${mode}><i></i>${MODE_LABEL[mode] || mode}</span>`;

// Segmented { value, options: [{value,label}], onChange, label } : a single-choice control.
export const Segmented = ({ value, options, onChange, label }) =>
  html`<div class="seg" role="group" aria-label=${label}>${options.map((o) => html`<button aria-pressed=${value === o.value} onClick=${() => onChange(o.value)}>${o.label}</button>`)}</div>`;

// Toggle { checked, onChange, label, color } : on/off switch with an accessible name.
export const Toggle = ({ checked, onChange, label, color }) =>
  html`<button class="toggle" role="switch" aria-checked=${!!checked} aria-label=${label} style=${color ? `--c:${color}` : ""} onClick=${() => onChange(!checked)}></button>`;

// Avatar { name, color, size, talking, unsure } : initial in a voice colour; pulses while that voice is talking.
export const Avatar = ({ name = "?", color, size = 34, talking, unsure }) =>
  html`<span class=${`avatar ${talking ? "talking" : ""} ${unsure ? "unsure" : ""}`} style=${`--sz:${size}px;${color ? `--c:${color}` : ""}`} title=${name}>${unsure ? "?" : name.slice(0, 1).toUpperCase()}</span>`;

// Dialog { open, title, onClose, children, actions } : native <dialog> (focus trap + Esc come for free). Never a browser alert.
export function Dialog({ open, title, onClose, children, actions }) {
  const ref = useRef();
  useEffect(() => {
    const d = ref.current;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return html`<dialog ref=${ref} onClose=${onClose} onCancel=${onClose}>
    <h2>${title}</h2><div class="stack">${children}</div>
    <div class="actions">${actions}</div></dialog>`;
}

// EmptyState { icon, title, text, action } : always says what to do next.
export const EmptyState = ({ icon = "plus", title, text, action }) =>
  html`<div class="empty"><${Icon} name=${icon} /><h3>${title}</h3><p>${text}</p>${action}</div>`;

// Toasts : one host; each toast may carry an Undo action (6 s).
export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  return html`<div class="toasts" role="status" aria-live="polite">${toasts.map((t) =>
    html`<div class="toast" key=${t.id}>${t.msg}${t.undo && html`<button onClick=${() => { t.undo(); dismissToast(t.id); }}>Undo</button>`}</div>`)}</div>`;
}

export const when = (ts) => {
  const d = Math.max(0, Date.now() / 1000 - ts);
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
};
