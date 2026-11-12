// Shown when the approval gate pauses the run. Values are never displayed here, only what was found and where.
export default function ApprovalCard({ approval, onDecide, disabled }) {
  return (
    <section className="approval" role="alertdialog" aria-label="Approval needed">
      <h3>{approval.title}</h3>
      <p>{approval.message}</p>
      <ul>
        {approval.findings.map((f) => (
          <li key={`${f.kind}-${f.id}`}>
            <b>{f.label}</b>
            {f.columns.map((c) => <span key={c} className="chip">column: {c}</span>)}
            {f.patterns.map((p) => <span key={p} className="chip">{p} pattern</span>)}
          </li>
        ))}
      </ul>
      <div className="choices">
        <button className="btn" disabled={disabled} onClick={() => onDecide("mask")}>Mask sensitive values</button>
        <button className="btn ghost" disabled={disabled} onClick={() => onDecide("reject")}>Exclude this evidence</button>
        <button className="btn ghost danger" disabled={disabled} onClick={() => onDecide("approve")}>Show as-is</button>
      </div>
      <p className="muted small">Masking is recommended: the answer can still use everything else. Nothing is saved to memory when sensitive data is involved.</p>
    </section>
  );
}
