import { useEffect, useState } from "react";
import { api } from "../api";
import PlotChart from "./PlotChart.jsx";
import { StatusBadge } from "./Verification.jsx";

export default function ReportView({ id, onClose, onDeleted }) {
  const [r, setR] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api.getReport(id).then(setR).catch((e) => setError(e.message)); }, [id]);

  const remove = async () => {
    if (!confirm("Delete this report?")) return;
    await api.deleteReport(id);
    onDeleted();
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel report" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Report">
        <header>
          <h2>{r?.title ?? "Report"}</h2>
          <button onClick={onClose} aria-label="Close">✕</button>
        </header>
        {error && <p className="err">{error}</p>}
        {r && (
          <>
            <div className="actions">
              <a className="btn" href={`/api/reports/${id}/pdf`} download>Download PDF</a>
              <a className="btn" href={`/api/reports/${id}/xlsx`} download>Download Excel</a>
              <button className="btn ghost danger" onClick={remove}>Delete</button>
              <StatusBadge verification={r.verification} />
            </div>
            <p className="muted"><b>Question:</b> {r.question}</p>

            <h3>Executive summary</h3>
            <p>{r.executive_summary}</p>

            <h3>Key findings</h3>
            <ul>{r.findings.map((f, i) => <li key={i}>{f.text} {f.refs.length > 0 && <span className="refs">[{f.refs.join(", ")}]</span>}</li>)}</ul>

            {r.charts.length > 0 && (
              <>
                <h3>Charts</h3>
                <div className="charts">{r.charts.map((c) => <PlotChart key={c.id} figure={c.figure} title={c.title} />)}</div>
              </>
            )}

            <h3>Recommendations</h3>
            <ul>{r.recommendations.map((x, i) => <li key={i}>{x}</li>)}</ul>

            <h3>Methodology</h3>
            <ul>{r.methodology.map((x, i) => <li key={i}>{x}</li>)}</ul>

            <h3>Limitations</h3>
            <ul>{r.limitations.map((x, i) => <li key={i}>{x}</li>)}</ul>
            <p className="muted">The PDF and Excel files also include the verification table and the full evidence appendix.</p>
          </>
        )}
      </div>
    </div>
  );
}
