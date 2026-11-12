const LABELS = { planner: "Planner", data: "Data", investigate: "Investigate", rag: "RAG", writer: "Writer", verifier: "Verifier", approval: "Approval", memory: "Memory" };
const time = (ts) => new Date(ts).toLocaleTimeString([], { hour12: false });

export function PlanView({ plan }) {
  if (!plan) return null;
  return (
    <div className="plan">
      <b>Objective:</b> {plan.objective}
      <ol>{plan.steps.map((s, i) => <li key={i}><span className={`badge ${s.agent}`}>{LABELS[s.agent]}</span> {s.task}</li>)}</ol>
    </div>
  );
}

export function LogList({ logs }) {
  return (
    <ul className="log">
      {logs.map((l, i) => (
        <li key={i}>
          <time>{time(l.ts)}</time>
          <span className={`badge ${l.agent}`}>{LABELS[l.agent] ?? l.agent}</span>
          <div><b>{l.action}</b>{l.detail && <small>{l.detail}</small>}</div>
        </li>
      ))}
    </ul>
  );
}

// Shown under a finished answer; collapsed by default.
export default function AgentLog({ logs, plan }) {
  if (!logs?.length) return null;
  return (
    <details className="agentlog">
      <summary>Agent log · {logs.length} steps</summary>
      <PlanView plan={plan} />
      <LogList logs={logs} />
    </details>
  );
}
