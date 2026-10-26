// Tiny fetch client. Errors carry the server's plain-language message so the UI can show them as is.
import { DEMO } from "./store.js";

async function call(method, path, body) {
  if (DEMO) { const { demo } = await import("./fixtures.js"); return demo(method, path, body); }
  const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Something went wrong (${r.status}).`);
  return data;
}
export const api = { get: (p) => call("GET", p), post: (p, b) => call("POST", p, b || {}), put: (p, b) => call("PUT", p, b || {}) };
