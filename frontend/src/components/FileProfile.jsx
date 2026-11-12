import { useEffect, useState } from "react";
import { api } from "../api";

export default function FileProfile({ id, onClose }) {
  const [file, setFile] = useState(null);
  const [sheet, setSheet] = useState(0);
  useEffect(() => { api.getFile(id).then(setFile); }, [id]);
  if (!file) return null;
  const s = file.profile.sheets[sheet];
  const heads = s.preview[0] ? Object.keys(s.preview[0]) : [];

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Dataset profile">
        <header>
          <h2>{file.filename}</h2>
          <button onClick={onClose} aria-label="Close">✕</button>
        </header>
        {file.profile.sheets.length > 1 && (
          <div className="tabs">
            {file.profile.sheets.map((x, i) => (
              <button key={i} className={i === sheet ? "active" : ""} onClick={() => setSheet(i)}>{x.sheet}</button>
            ))}
          </div>
        )}
        <p className="muted">{s.rows.toLocaleString()} rows · {s.columns.length} columns</p>
        <div className="scroll">
          <table>
            <thead><tr><th>Column</th><th>Type</th><th>Missing</th><th>Unique</th><th>Mean</th><th>Min</th><th>Max</th></tr></thead>
            <tbody>
              {s.columns.map((c) => {
                const n = s.numeric_stats[c.name];
                return (
                  <tr key={c.name}>
                    <td>{c.name}</td><td>{c.dtype}</td>
                    <td className={c.nulls ? "warn" : ""}>{c.nulls}</td><td>{c.unique}</td>
                    <td>{n?.mean != null ? +n.mean.toFixed(2) : "–"}</td>
                    <td>{n?.min ?? "–"}</td><td>{n?.max ?? "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <h3>First rows</h3>
        <div className="scroll">
          <table>
            <thead><tr>{heads.map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>{s.preview.map((r, i) => <tr key={i}>{heads.map((h) => <td key={h}>{String(r[h] ?? "")}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
