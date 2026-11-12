import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Sidebar from "./components/Sidebar.jsx";
import Chat from "./components/Chat.jsx";
import FileProfile from "./components/FileProfile.jsx";
import StatusBar from "./components/StatusBar.jsx";
import ReportView from "./components/ReportView.jsx";
import Dashboard from "./components/Dashboard.jsx";

export default function App() {
  const [files, setFiles] = useState([]);
  const [scope, setScope] = useState([]);          // file ids the questions are limited to ([] = all)
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [profileId, setProfileId] = useState(null);
  const [reports, setReports] = useState([]);
  const [reportId, setReportId] = useState(null);
  const [view, setView] = useState("investigate");
  const [navOpen, setNavOpen] = useState(false);

  const refreshFiles = useCallback(() => api.listFiles().then(setFiles).catch(() => {}), []);
  const refreshSessions = useCallback(() => api.sessions().then(setSessions).catch(() => {}), []);

  const refreshReports = useCallback(() => api.listReports().then(setReports).catch(() => {}), []);

  useEffect(() => { refreshFiles(); refreshSessions(); refreshReports(); }, [refreshFiles, refreshSessions, refreshReports]);

  const openSession = async (id) => {
    setSessionId(id);
    setMessages(await api.history(id));
    setView("investigate");
    setNavOpen(false);
  };
  const newSession = () => { setSessionId(null); setMessages([]); setNavOpen(false); };

  const toggleScope = (id) => setScope((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const removeFile = async (id) => {
    await api.deleteFile(id);
    setScope((s) => s.filter((x) => x !== id));
    if (profileId === id) setProfileId(null);
    refreshFiles();
  };

  return (
    <div className="shell">
      <Sidebar
        open={navOpen} reports={reports} onOpenReport={setReportId} files={files} scope={scope} sessions={sessions} sessionId={sessionId}
        onToggleScope={toggleScope} onUploaded={refreshFiles} onDelete={removeFile}
        onProfile={setProfileId} onOpenSession={openSession} onNew={newSession}
      />
      <main className="main">
        <header className="topbar">
          <button className="menu" onClick={() => setNavOpen((v) => !v)} aria-label="Toggle navigation">☰</button>
          <nav className="nav" aria-label="Views">
            <button className={view === "investigate" ? "active" : ""} onClick={() => setView("investigate")}>Investigate</button>
            <button className={view === "dashboard" ? "active" : ""} onClick={() => setView("dashboard")}>Dashboard</button>
          </nav>
          <StatusBar />
        </header>
        {view === "dashboard" ? <Dashboard onOpenSession={openSession} /> : (
          <Chat
          files={files} scope={scope} sessionId={sessionId} messages={messages}
          setMessages={setMessages} setSessionId={setSessionId} onSent={refreshSessions}
          onReport={(id) => { refreshReports(); setReportId(id); }}
        />
        )}
      </main>
      {reportId && <ReportView id={reportId} onClose={() => setReportId(null)} onDeleted={() => { setReportId(null); refreshReports(); }} />}
      {profileId && <FileProfile id={profileId} onClose={() => setProfileId(null)} />}
    </div>
  );
}
