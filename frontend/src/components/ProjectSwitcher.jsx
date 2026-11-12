import { useEffect, useState } from "react";
import { api } from "../api";

export default function ProjectSwitcher({ projectId, onSelect }) {
  const [projects, setProjects] = useState([]);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");

  const refresh = () => api.listProjects().then(setProjects).catch(() => {});

  useEffect(() => { refresh(); }, []);

  const current = projects.find((p) => p.id === projectId);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    const p = await api.createProject({ name: name.trim(), description: desc.trim() });
    setName("");
    setDesc("");
    setCreating(false);
    await refresh();
    onSelect(p.id);
  };

  return (
    <div className="project-switcher">
      <button className="project-btn" onClick={() => setOpen((v) => !v)}>
        {current ? current.name : "Select project"} ▾
      </button>
      {open && (
        <div className="project-menu">
          {projects.map((p) => (
            <button
              key={p.id}
              className={p.id === projectId ? "active" : ""}
              onClick={() => { onSelect(p.id); setOpen(false); }}
            >
              {p.name}
            </button>
          ))}
          <hr />
          {creating ? (
            <form className="project-create" onSubmit={create}>
              <input
                autoFocus
                placeholder="Project name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <input
                placeholder="Description (optional)"
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
              />
              <div className="row">
                <button type="submit">Create</button>
                <button type="button" onClick={() => setCreating(false)}>Cancel</button>
              </div>
            </form>
          ) : (
            <button onClick={() => setCreating(true)}>+ New project</button>
          )}
        </div>
      )}
    </div>
  );
}
