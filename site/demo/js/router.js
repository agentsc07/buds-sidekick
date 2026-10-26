import { useState, useEffect } from "../vendor/htm-preact-standalone.module.js";

export function parse(hash) {
  const [name = "home", id] = (hash.replace(/^#\/?/, "") || "home").split("/");
  return { name, id };
}
export function useRoute() {
  const [r, setR] = useState(parse(location.hash));
  useEffect(() => { const f = () => setR(parse(location.hash)); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return r;
}
export const go = (path) => { location.hash = "#/" + path; };
