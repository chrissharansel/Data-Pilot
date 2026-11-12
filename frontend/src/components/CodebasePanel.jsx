import { useEffect, useState } from "react";
import { api } from "../api";

export default function CodebasePanel({ projectId }) {
  const [tree, setTree] = useState([]);
  const [path, setPath] = useState("");
  const [file, setFile] = useState(null);
  const [branches, setBranches] = useState([]);
  const [branch, setBranch] = useState("main");
  const [commits, setCommits] = useState([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [diff, setDiff] = useState(null);

  const refreshTree = (p = "") => {
    if (!projectId) return;
    api.codeTree(projectId, p).then(setTree).catch(() => setTree([]));
  };

  const refreshBranches = () => {
    if (!projectId) return;
    api.listBranches(projectId).then((b) => {
      setBranches(b);
      const def = b.find((x) => x.is_default) || b[0];
      if (def) setBranch(def.name);
    }).catch(() => {});
  };

  const refreshCommits = () => {
    if (!projectId) return;
    api.listCommits(projectId, branch).then(setCommits).catch(() => setCommits([]));
  };

  useEffect(() => {
    setPath("");
    setFile(null);
    setDiff(null);
    refreshTree("");
    refreshBranches();
  }, [projectId]);

  useEffect(() => {
    refreshCommits();
  }, [projectId, branch]);

  const openItem = async (item) => {
    setError("");
    if (item.type === "dir") {
      setPath(item.path);
      refreshTree(item.path);
      setFile(null);
    } else {
      try {
        const f = await api.codeFile(projectId, item.path);
        setFile(f);
      } catch (e) {
        setError(e.message);
      }
    }
  };

  const goUp = () => {
    if (!path) return;
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    const parent = parts.join("/");
    setPath(parent);
    refreshTree(parent);
    setFile(null);
  };

  const onUpload = async (e) => {
    const files = e.target.files;
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      await api.codeUpload(projectId, files);
      refreshTree(path);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  const commit = async () => {
    if (!message.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.createCommit(projectId, { message: message.trim(), branch });
      setMessage("");
      refreshCommits();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const showDiff = async (commitId) => {
    setError("");
    try {
      const changes = await api.codeDiff(projectId, commitId, "working");
      setDiff({ from: commitId, changes });
    } catch (e) {
      setError(e.message);
    }
  };

  if (!projectId) {
    return <div className="panel-empty">Select or create a project to manage the codebase.</div>;
  }

  return (
    <div className="code-panel">
      <div className="code-toolbar">
        <label>
          Branch
          <select value={branch} onChange={(e) => setBranch(e.target.value)}>
            {branches.map((b) => (
              <option key={b.id} value={b.name}>{b.name}</option>
            ))}
          </select>
        </label>
        <label className="upload-btn">
          Upload files
          <input type="file" multiple hidden onChange={onUpload} />
        </label>
        <input
          className="commit-msg"
          placeholder="Commit message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <button disabled={busy || !message.trim()} onClick={commit}>
          {busy ? "…" : "Commit"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="code-body">
        <div className="code-tree">
          <div className="tree-header">
            <button disabled={!path} onClick={goUp}>↑ Up</button>
            <span className="muted">{path || "/"}</span>
          </div>
          <ul>
            {tree.map((item) => (
              <li key={item.path}>
                <button onClick={() => openItem(item)}>
                  {item.type === "dir" ? "📁" : "📄"} {item.name}
                </button>
              </li>
            ))}
            {tree.length === 0 && <li className="muted">Empty — upload files to start</li>}
          </ul>
        </div>

        <div className="code-viewer">
          {file && (
            <>
              <div className="viewer-header">{file.path} · {file.size} bytes</div>
              {file.content != null ? (
                <pre className="code-content">{file.content}</pre>
              ) : (
                <div className="muted">Binary file</div>
              )}
            </>
          )}
          {diff && (
            <div className="diff-view">
              <h4>Changes since {diff.from.slice(0, 8)}…</h4>
              <ul>
                {diff.changes.map((c) => (
                  <li key={c.path}><span className={`status ${c.status}`}>{c.status}</span> {c.path}</li>
                ))}
                {diff.changes.length === 0 && <li className="muted">No differences</li>}
              </ul>
              <button onClick={() => setDiff(null)}>Close</button>
            </div>
          )}
          {!file && !diff && <div className="panel-empty">Select a file or view a commit diff</div>}
        </div>

        <div className="commit-list">
          <h4>Commits</h4>
          <ul>
            {commits.map((c) => (
              <li key={c.id}>
                <button onClick={() => showDiff(c.id)}>
                  <code>{c.id.slice(0, 8)}</code> {c.message}
                </button>
                <span className="muted">{new Date(c.created_at).toLocaleString()}</span>
              </li>
            ))}
            {commits.length === 0 && <li className="muted">No commits yet</li>}
          </ul>
        </div>
      </div>
    </div>
  );
}
