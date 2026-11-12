import { useEffect, useState } from "react";
import { api } from "../api";

export default function DocumentsPanel({ projectId }) {
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState("view");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => {
    if (!projectId) return;
    api.listDocuments(projectId).then(setDocs).catch(() => setDocs([]));
  };

  useEffect(() => {
    setSelected(null);
    setContent("");
    setMode("view");
    refresh();
  }, [projectId]);

  const openDoc = async (id) => {
    setError("");
    const d = await api.getDocument(projectId, id);
    setSelected(d);
    setTitle(d.title);
    setContent(d.content || "");
    setMode("view");
  };

  const save = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const d = await api.updateDocument(projectId, selected.id, { title, content });
      setSelected(d);
      setMode("view");
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const createBlank = async () => {
    setBusy(true);
    setError("");
    try {
      const d = await api.createDocument(projectId, {
        title: title || "Untitled",
        content: content || "# New document\n\n",
      });
      setSelected(d);
      setTitle(d.title);
      setContent(d.content || "");
      setMode("edit");
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setError("");
    try {
      const d = await api.generateDocument(projectId, { query: query.trim(), title: title || undefined });
      setSelected(d);
      setTitle(d.title);
      setContent(d.content || "");
      setMode("view");
      setQuery("");
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    if (!confirm("Delete this document?")) return;
    await api.deleteDocument(projectId, id);
    if (selected?.id === id) {
      setSelected(null);
      setContent("");
    }
    refresh();
  };

  if (!projectId) {
    return <div className="panel-empty">Select or create a project to manage documents.</div>;
  }

  return (
    <div className="docs-panel">
      <div className="docs-list">
        <div className="docs-toolbar">
          <button onClick={() => { setMode("create"); setTitle(""); setContent(""); setSelected(null); }}>
            + New
          </button>
          <button onClick={() => { setMode("generate"); setQuery(""); }}>
            Generate with AI
          </button>
        </div>
        <ul>
          {docs.map((d) => (
            <li key={d.id} className={selected?.id === d.id ? "active" : ""}>
              <button className="doc-item" onClick={() => openDoc(d.id)}>
                <span className="doc-title">{d.title}</span>
                <span className="doc-meta">{d.source} · {new Date(d.updated_at).toLocaleDateString()}</span>
              </button>
              <button className="icon-btn" onClick={() => remove(d.id)} title="Delete">×</button>
            </li>
          ))}
          {docs.length === 0 && <li className="muted">No documents yet</li>}
        </ul>
      </div>

      <div className="docs-editor">
        {error && <div className="error">{error}</div>}

        {mode === "generate" && (
          <div className="generate-form">
            <h3>Generate document with AI</h3>
            <input
              placeholder="Optional title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <textarea
              rows={4}
              placeholder="Describe the document you want… e.g. Write a daily requirements document for the login feature covering acceptance criteria and open questions."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button disabled={busy || !query.trim()} onClick={generate}>
              {busy ? "Generating…" : "Generate"}
            </button>
          </div>
        )}

        {mode === "create" && (
          <div className="generate-form">
            <h3>New document</h3>
            <input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
            <textarea rows={12} value={content} onChange={(e) => setContent(e.target.value)} />
            <button disabled={busy} onClick={createBlank}>{busy ? "Saving…" : "Create"}</button>
          </div>
        )}

        {(mode === "view" || mode === "edit") && selected && (
          <>
            <div className="editor-header">
              {mode === "edit" ? (
                <input value={title} onChange={(e) => setTitle(e.target.value)} />
              ) : (
                <h3>{selected.title}</h3>
              )}
              <div className="row">
                {mode === "view" ? (
                  <button onClick={() => setMode("edit")}>Edit</button>
                ) : (
                  <button disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
                )}
              </div>
            </div>
            {mode === "edit" ? (
              <textarea className="md-editor" value={content} onChange={(e) => setContent(e.target.value)} />
            ) : (
              <pre className="md-preview">{content}</pre>
            )}
          </>
        )}

        {!selected && mode === "view" && (
          <div className="panel-empty">Select a document or create one.</div>
        )}
      </div>
    </div>
  );
}
