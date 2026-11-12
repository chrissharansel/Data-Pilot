import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import AgentLog, { LogList, PlanView } from "./AgentLog.jsx";
import PlotChart from "./PlotChart.jsx";
import Verification, { ApprovalNote } from "./Verification.jsx";
import ApprovalCard from "./ApprovalCard.jsx";

function Evidence({ sources, calcs }) {
  const [open, setOpen] = useState(false);
  const total = (sources?.length || 0) + (calcs?.length || 0);
  if (!total) return null;
  return (
    <div className="evidence">
      <button onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} evidence ({total})</button>
      {open && calcs?.map((c) => (
        <blockquote key={c.id}>
          <b>[{c.id}] {c.tool}</b> <span>{Object.entries(c.args).map(([k, v]) => `${k}=${v}`).join(", ")}</span>
          <pre>{c.result}</pre>
        </blockquote>
      ))}
      {open && sources?.map((s) => (
        <blockquote key={s.n}>
          <b>[{s.n}] {s.filename}</b> <span>{s.location}</span>
          <pre>{s.snippet}</pre>
        </blockquote>
      ))}
    </div>
  );
}

export default function Chat({ files, scope, sessionId, messages, setMessages, setSessionId, onSent, onReport }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reporting, setReporting] = useState(null);   // id of the message a report is being generated for
  const [approval, setApproval] = useState(null);   // pending approval request from the gate
  const [useMemory, setUseMemory] = useState(true);
  const [live, setLive] = useState(null);   // {plan, logs} while an investigation is running
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy, live]);

  const waiting = useRef(false);   // true while the run is paused for a human decision

  // One handler serves both the first run and the resume after an approval.
  const handleEvent = (event, data) => {
    if (event === "session") setSessionId(data.session_id);
    else if (event === "plan") setLive((l) => ({ ...l, plan: data }));
    else if (event === "log") setLive((l) => ({ ...l, logs: [...l.logs, data] }));
    else if (event === "approval") { waiting.current = true; setApproval(data); }
    else if (event === "final") {
      waiting.current = false; setApproval(null);
      setMessages((m) => [...m, { role: "assistant", content: data.answer, id: data.id, sources: data.sources, verification: data.verification,
        approval: data.approval, evidence: data.evidence, charts: data.charts, plan: data.plan, logs: data.logs }]);
    } else if (event === "error") { waiting.current = false; setApproval(null); setError(data.message); }
  };

  const run = async (start) => {
    setError(""); setBusy(true); waiting.current = false;
    try {
      await start(handleEvent);
      onSent();
    } catch (e) {
      waiting.current = false; setApproval(null); setError(e.message);
    } finally {
      setBusy(false);
      if (!waiting.current) setLive(null);
    }
  };

  const ask = (q) => {
    const question = (q ?? text).trim();
    if (!question || busy || approval) return;
    setText(""); setLive({ plan: null, logs: [] });
    setMessages((m) => [...m, { role: "user", content: question }]);
    run((on) => api.investigate({ question, session_id: sessionId, file_ids: scope.length ? scope : null, use_memory: useMemory }, on));
  };

  const decide = (decision) => {
    const thread_id = approval.thread_id;
    setApproval(null);
    run((on) => api.resume({ thread_id, decision }, on));
  };

  const makeReport = async (m) => {
    setReporting(m.id); setError("");
    try {
      const r = await api.createReport({ session_id: sessionId, message_id: m.id });
      onReport(r.id);
    } catch (e) {
      setError(e.message);
    } finally {
      setReporting(null);
    }
  };

  const starters = ["Summarise what's in these files", "Find anomalies and data quality problems", "Show the trend over time"];

  return (
    <section className="chat">
      <div className="thread">
        {messages.length === 0 && (
          <div className="empty">
            <h2>{files.length ? "What should we look into?" : "Start by uploading a file"}</h2>
            <p>Answers are grounded in your uploaded files and show the passages they came from.</p>
            {files.length > 0 && <div className="starters">{starters.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}</div>}
          </div>
        )}
        {messages.map((m, i) => (
          <article key={i} className={`msg ${m.role}`}>
            {m.role === "assistant" ? <ReactMarkdown>{m.content}</ReactMarkdown> : <p>{m.content}</p>}
            {m.role === "assistant" && m.charts?.length > 0 && (
              <div className="charts">{m.charts.map((c) => <PlotChart key={c.id} figure={c.figure} title={c.title} />)}</div>
            )}
            {m.role === "assistant" && <Evidence sources={m.sources} calcs={m.evidence ?? m.data_evidence} />}
            {m.role === "assistant" && <Verification verification={m.verification} />}
            {m.role === "assistant" && <ApprovalNote approval={m.approval} />}
            {m.role === "assistant" && <AgentLog logs={m.logs} plan={m.plan} />}
            {m.role === "assistant" && m.id && m.verification && (
              <button className="reportbtn" disabled={reporting === m.id} onClick={() => makeReport(m)}>
                {reporting === m.id ? "Writing report…" : "Generate report"}
              </button>
            )}
          </article>
        ))}
        {live && (
          <article className="msg assistant live">
            <div className="livehead">{busy ? <><span className="spinner" /> Agents working…</> : "Waiting for your decision"}</div>
            <PlanView plan={live.plan} />
            <LogList logs={live.logs} />
            {approval && <ApprovalCard approval={approval} onDecide={decide} disabled={busy} />}
          </article>
        )}
        {error && <div className="err">{error}</div>}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <textarea
          rows={1} value={text} disabled={!!approval} placeholder="Ask a question about your data or documents"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }}
        />
        <button disabled={busy || !!approval || !text.trim()}>Ask</button>
      </form>
      <label className="memtoggle">
        <input type="checkbox" checked={useMemory} onChange={(e) => setUseMemory(e.target.checked)} />
        Use memory: recall related past findings and remember new verified ones
      </label>
    </section>
  );
}
