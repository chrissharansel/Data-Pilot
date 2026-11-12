import { useRef, useState } from "react";
import { api } from "../api";

const fmt = (b) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`);

export default function Sidebar({ open, reports, onOpenReport, files, scope, sessions, sessionId, onToggleScope, onUploaded, onDelete, onProfile, onOpenSession, onNew }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [msg, setMsg] = useState("");

  const send = async (list) => {
    if (!list.length) return;
    setBusy(true); setMsg("");
    try {
      const r = await api.upload(list);
      if (r.errors.length) setMsg(r.errors.map((e) => `${e.filename}: ${e.error}`).join("\n"));
      onUploaded();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className={`side ${open ? "open" : ""}`}>
      <div className="brand">DataPilot<span>AI</span></div>

      <div
        className={`drop ${drag ? "drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
        onClick={() => input.current.click()}
        role="button" tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && input.current.click()}
      >
        <input ref={input} type="file" multiple hidden accept=".csv,.xlsx,.xls,.pdf,.txt,.md,.docx"
               onChange={(e) => { send(e.target.files); e.target.value = ""; }} />
        {busy ? "Reading and indexing files…" : "Drop files here or click to upload"}
        <small>CSV, Excel, PDF, Word, text</small>
      </div>
      {msg && <pre className="err">{msg}</pre>}

      <section>
        <h2>Files {scope.length > 0 && <em>{scope.length} selected</em>}</h2>
        {files.length === 0 && <p className="muted">No files yet. Upload one to start investigating.</p>}
        <ul className="files">
          {files.map((f) => (
            <li key={f.id}>
              <label>
                <input type="checkbox" checked={scope.includes(f.id)} onChange={() => onToggleScope(f.id)} />
                <span className="fname" title={f.filename}>{f.filename}</span>
              </label>
              <div className="meta">
                {fmt(f.size)} · {f.chunks} chunks
                {f.kind === "tabular" && <button onClick={() => onProfile(f.id)}>Profile</button>}
                <button className="danger" onClick={() => confirm(`Delete ${f.filename}?`) && onDelete(f.id)}>Delete</button>
              </div>
            </li>
          ))}
        </ul>
        {files.length > 0 && <p className="muted">Tick files to limit questions to them. None ticked searches everything.</p>}
      </section>

      <section>
        <h2>Reports</h2>
        {reports.length === 0 && <p className="muted">Use “Generate report” under an answer to create one.</p>}
        <ul className="sessions">
          {reports.map((r) => (
            <li key={r.id}><button onClick={() => onOpenReport(r.id)} title={r.title}>{r.title}</button></li>
          ))}
        </ul>
      </section>

      <section>
        <h2>History <button className="link" onClick={onNew}>New</button></h2>
        <ul className="sessions">
          {sessions.map((s) => (
            <li key={s.session_id}>
              <button className={s.session_id === sessionId ? "active" : ""} onClick={() => onOpenSession(s.session_id)}>{s.title}</button>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
