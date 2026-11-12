export const STATUS = {
  verified: ["Verified", "ok"],
  partially_verified: ["Partly verified", "warn"],
  unverified: ["Unverified", "bad"],
  not_applicable: ["No evidence to verify", "none"],
};

export function StatusBadge({ verification }) {
  const [label, tone] = STATUS[verification?.status] ?? ["Not verified", "none"];
  const score = verification && verification.status !== "not_applicable" && verification.support_score != null;
  return <span className={`vbadge ${tone}`}>{label}{score ? ` · ${verification.support_score}%` : ""}</span>;
}

export default function Verification({ verification }) {
  if (!verification) return null;
  return (
    <details className="verification">
      <summary><StatusBadge verification={verification} /> <span>How this was checked</span></summary>
      {verification.issues?.map((i, k) => <p key={k} className="vissue">{i}</p>)}
      {verification.claims?.length > 0 && (
        <div className="scroll">
          <table>
            <thead><tr><th>Claim</th><th>Verdict</th><th>Evidence</th></tr></thead>
            <tbody>
              {verification.claims.map((c, i) => (
                <tr key={i}>
                  <td className="wrap">{c.claim}{c.note && <small>{c.note}</small>}</td>
                  <td><span className={`verdict ${c.verdict}`}>{c.verdict}</span></td>
                  <td>{c.evidence?.join(", ") || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

const DECISIONS = { approve: "shown as-is after your approval", mask: "masked", reject: "excluded" };

export function ApprovalNote({ approval }) {
  if (!approval?.flagged) return null;
  return (
    <p className="approvalnote">
      Sensitive data was detected and {DECISIONS[approval.decision] ?? "handled"}
      {approval.decided_by === "policy" ? " by policy" : ""}.
    </p>
  );
}
