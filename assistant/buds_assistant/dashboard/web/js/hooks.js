import { useEffect } from "../vendor/htm-preact-standalone.module.js";
import { api } from "./api.js";

// useTryMode(active): while true, gestures on the buds are shown on the dashboard but do nothing. The server expires it after 60 s,
// so this refreshes every 30 s and switches it off on cleanup.
export function useTryMode(active) {
  useEffect(() => {
    if (!active) return;
    api.post("/api/v2/gestures/try", { on: true });
    const i = setInterval(() => api.post("/api/v2/gestures/try", { on: true }), 30000);
    return () => { clearInterval(i); api.post("/api/v2/gestures/try", { on: false }); };
  }, [active]);
}
