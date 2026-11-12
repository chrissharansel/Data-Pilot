import { useEffect, useState } from "react";
import { api } from "../api";

export default function StatusBar() {
  const [h, setH] = useState(null);
  useEffect(() => {
    const tick = () => api.health().then(setH).catch(() => setH({ api: "down" }));
    tick();
    const t = setInterval(tick, 15000);
    return () => clearInterval(t);
  }, []);
  if (!h) return null;
  const item = (label, ok) => (
    <span className={`pill ${ok ? "ok" : "bad"}`}><i />{label}</span>
  );
  return (
    <div className="status">
      {item("API", h.api === "ok")}
      {item("MongoDB", h.mongo === "ok")}
      {item(h.model_ready || h.ollama !== "ok" ? `Ollama · ${h.model ?? ""}` : `Pull ${h.model}`, h.ollama === "ok" && h.model_ready)}
    </div>
  );
}
