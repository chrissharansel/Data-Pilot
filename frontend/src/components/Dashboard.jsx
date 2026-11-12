import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import PlotChart from "./PlotChart.jsx";

const VERDICTS = [["verified", "Verified", "ok"], ["partially_verified", "Partly verified", "warn"], ["unverified", "Unverified", "bad"], ["not_applicable", "No evidence", "none"]];

export default function Dashboard({ onOpenSession }) {
  const [d, setD] = useState(null);
  const [memories, setMemories] = useState([]);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    Promise.all([api.dashboard(), api.listMemory()]).then(([dash, mem]) => { setD(dash); setMemories(mem); }).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  if (error) return <div className="dash"><p className="err">{error}</p></div>;
  if (!d) return <div className="dash"><p className="muted">Loading…</p></div>;

  const total = d.counts.investigations || 0;
  const kpis = [["Files", d.counts.files], ["Investigations", total], ["Reports", d.counts.reports], ["Remembered findings", d.counts.memories], ["Sensitive-data approvals", d.counts.sensitive_flagged]];

  return (
    <div className="dash">
      <div className="kpis">{kpis.map(([k, v]) => <div className="kpi" key={k}><b>{v}</b><span>{k}</span></div>)}</div>

      <section className="card">
        <h2>Answer quality</h2>
        {total === 0 ? <p className="muted">No investigations yet.</p> : (
          <>
            <div className="vbar" role="img" aria-label="Verification breakdown">
              {VERDICTS.map(([key, , tone]) => d.verification[key] ? <i key={key} className={tone} style={{ flex: d.verification[key] }} /> : null)}
            </div>
            <ul className="legend">
              {VERDICTS.map(([key, label, tone]) => <li key={key}><i className={tone} />{label}: {d.verification[key] ?? 0}</li>)}
            </ul>
          </>
        )}
      </section>

      <section className="card">
        <h2>Datasets</h2>
        {d.datasets.length === 0 ? <p className="muted">Upload a CSV or Excel file to see its data-quality summary.</p> : (
          <div className="scroll">
            <table>
              <thead><tr><th>File</th><th>Rows</th><th>Columns</th><th>Missing cells</th></tr></thead>
              <tbody>
                {d.datasets.map((x) => (
                  <tr key={x.id}>
                    <td>{x.filename}</td><td>{x.rows.toLocaleString()}</td><td>{x.columns}</td>
                    <td className={x.missing_pct > 5 ? "warn" : ""}>{x.missing_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2>Recent charts</h2>
        {d.charts.length === 0 ? <p className="muted">Charts from your investigations appear here.</p> : (
          <div className="gallery">
            {d.charts.map((c) => (
              <figure key={c.id} className="card">
                <PlotChart figure={c.figure} title={c.title} />
                <figcaption>
                  <span>{c.question}</span>
                  {c.session_id && <button className="link" onClick={() => onOpenSession(c.session_id)}>Open investigation</button>}
                </figcaption>
              </figure>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h2>What DataPilot remembers
          {memories.length > 0 && <button className="link danger" onClick={async () => { if (confirm("Forget everything?")) { await api.clearMemory(); load(); } }}>Forget all</button>}
        </h2>
        <p className="muted">Only verified findings without sensitive data are kept. They are used as background for related questions and are never treated as evidence.</p>
        {memories.length === 0 && <p className="muted">Nothing remembered yet.</p>}
        <ul className="memories">
          {memories.map((m) => (
            <li key={m.id}>
              <div><b>{m.question}</b><small>{m.summary}</small><small>{m.files.join(", ")}</small></div>
              <button className="link danger" onClick={async () => { await api.deleteMemory(m.id); load(); }}>Forget</button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
