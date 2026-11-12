// All backend calls live here. Vite proxies /api to FastAPI during development.
async function request(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* non-JSON error */ }
    throw new Error(detail);
  }
  return res.json();
}

// POST + Server-Sent Events: calls onEvent(name, data) for each event as it arrives.
async function stream(path, body, onEvent) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (event && data) onEvent(event, JSON.parse(data));
    }
  }
}

export const api = {
  health: () => request("/api/health"),
  listFiles: () => request("/api/files"),
  getFile: (id) => request(`/api/files/${id}`),
  deleteFile: (id) => request(`/api/files/${id}`, { method: "DELETE" }),
  upload: (fileList) => {
    const form = new FormData();
    [...fileList].forEach((f) => form.append("files", f));
    return request("/api/files/upload", { method: "POST", body: form });
  },
  chat: (body) =>
    request("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  investigate: (body, onEvent) => stream("/api/investigate/stream", body, onEvent),
  resume: (body, onEvent) => stream("/api/investigate/resume", body, onEvent),
  dashboard: () => request("/api/dashboard"),
  listMemory: () => request("/api/memory"),
  deleteMemory: (id) => request(`/api/memory/${id}`, { method: "DELETE" }),
  clearMemory: () => request("/api/memory", { method: "DELETE" }),
  createReport: (body) =>
    request("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  listReports: () => request("/api/reports"),
  getReport: (id) => request(`/api/reports/${id}`),
  deleteReport: (id) => request(`/api/reports/${id}`, { method: "DELETE" }),
  sessions: () => request("/api/chat/sessions"),
  history: (id) => request(`/api/chat/${id}`),
};
