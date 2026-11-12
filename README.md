# DataPilot AI: Autonomous Data Investigation Platform

Upload business files, ask questions in plain language, and let a team of AI agents investigate: they calculate exact
numbers, hunt for anomalies, search your documents, check their own answer against the evidence, and write a report.
Everything runs **locally** with free, open-source tools. No paid APIs, and your files never leave your machine.

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite, Plotly.js |
| Backend | Python, FastAPI |
| LLM | Ollama running **Qwen3 4B** (local) |
| Agent orchestration | **LangGraph** (state graph, conditional routing, loops, human-in-the-loop `interrupt`) |
| RAG | LangChain + **ChromaDB** + Sentence Transformers (`all-MiniLM-L6-v2`) |
| Data / anomalies | Pandas, NumPy, scikit-learn (Isolation Forest), z-score, IQR |
| Charts / exports | Plotly (interactive), matplotlib + ReportLab (PDF), openpyxl (Excel) |
| Database | MongoDB (metadata, history, reports, memory) |

## What it does

- **Upload** CSV, Excel (all sheets), PDF, Word, text and Markdown files, then profile and index them.
- **Ask questions** about your data and documents. Answers carry citations: `[D1]` for a calculation, `[1]` for a document passage.
- **Six agents** work as one graph: Planner → Data → Investigation → RAG → Writer → Verifier (details below), plus a Report Agent on demand.
- **Investigate**: statistical anomalies (z-score, IQR, Isolation Forest), robust trends, data-quality checks, cross-dataset matching.
- **Verify**: every answer is checked for invalid citations and invented numbers, and revised once if it fails.
- **Report**: one click produces a structured report with PDF and Excel downloads.
- **Approve**: row-level sensitive data pauses the run until you choose to mask it, exclude it or show it.
- **Remember**: verified findings are recalled as background for related questions later (never as evidence).
- **See everything**: a live agent log shows each agent's actions; a dashboard shows answer quality, dataset health and charts.

## Architecture

```
React (Vite) ──/api──► FastAPI ─┬─ routers/   files · investigate (SSE stream + resume) · chat · reports · memory · dashboard
                                ├─ services/  parsers · vectorstore (Chroma) · llm (Ollama) · export (PDF/Excel) · dashboard
                                ├─ rag/       retrieval + cited answers (LangChain)
                                └─ agents/    LangGraph graph, nodes, tools, analysis, verification, sensitive-data, memory, report

MongoDB : files + profiles · chat history · reports · memories
ChromaDB: document chunks · memory embeddings
Ollama  : qwen3:4b
```

```
START → recall → planner ─► data_agent ─► investigation_agent ─► rag_agent ─► approval_gate ─► synthesizer ─► verifier ─► END
         │         │           (only the agents the plan asks for run, always in this order)            │ ▲            │
  related past   JSON plan                                                                  pause for human     └─ revise once ◄┘
  findings       (with fallback)                                                            decision (interrupt)   if unsupported
```

| Agent | Role | How it works |
|---|---|---|
| **Planner** | Understands the request, plans steps | Returns a JSON plan; invalid or empty plans fall back to a sensible default. |
| **Data Agent** | Exact numbers from tables | Tool-calling loop over five typed, read-only Pandas tools. The model never writes or runs code. |
| **Investigation Agent** | Anomalies, trends, inconsistencies | Four tools over plain statistical functions (no LLM in the maths); builds Plotly charts. |
| **RAG Agent** | Finds relevant passages | Semantic search in ChromaDB, limited to the files you selected. |
| **Verification Agent** | Validates findings against evidence | Rule-based citation and number checks, then a model claim check; sends the Writer back once if it fails. |
| **Report Agent** | Evidence-based reports | Model writes the title, summary, findings and recommendations; everything factual is assembled by code. |

The Writer node composes the answer from collected evidence only. The approval gate sits between evidence collection and writing.

## Requirements

- Python 3.10+ and Node.js 18+
- [Ollama](https://ollama.com/download)
- MongoDB (local install, or Docker: `docker compose up -d`)
- About 8 GB of RAM (qwen3:4b plus embeddings). A GPU is optional.

## Install and run

```bash
# 1. Model (Ollama must be running: `ollama serve`, or the desktop app)
ollama pull qwen3:4b

# 2. MongoDB, skip if you already run one
docker compose up -d

# 3. Backend
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
uvicorn app.main:app --reload --port 8000

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

The first upload downloads the embedding model (~90 MB) once; afterwards everything works offline.
The status chips at the top right show whether the API, MongoDB and the Ollama model are ready.
Interactive API docs: http://localhost:8000/docs

## Try it with the sample data

```bash
python scripts/make_sample_data.py      # creates ./sample_data/ (sales.csv, customers.csv, refund_policy.txt)
```

Upload the three files, then try these. The data has planted problems, so you know what correct looks like:

| Ask | You should see |
|---|---|
| "Find anomalies in sales.csv" | Spreadsheet rows **335** (amount 12000), **39** (9800) and **213** (7450.5) flagged by several methods, with a scatter chart. |
| "Check sales.csv for data quality problems" | **Duplicate rows** and **region spelling variants** (`north `, `NORTH`). |
| "How is average order amount trending by month?" | A **rising** trend with a line chart. |
| "Which region has the highest total amount?" | A grouped bar chart and a verified answer citing `[D1]`. |
| "Compare sales.csv and customers.csv" | Key `customer_id`: **10** ids only in sales, **5** only in customers. |
| "What does the policy say about refunds over 5000?" | A passage from `refund_policy.txt` cited as `[1]`. |
| "Show orders from customer C001 with their email" | The **approval card** appears. Choose *Mask* and the answer shows `[REDACTED]` instead of emails. |

Then click **Generate report** under an answer, open it, and download the PDF and Excel versions. Check the **Dashboard** tab
for answer quality, dataset health, recent charts and remembered findings.

## Configuration (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `MONGO_URI` / `MONGO_DB` | `mongodb://localhost:27017` / `datapilot` | Database |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `qwen3:4b` | Local LLM (a larger Qwen3 is more reliable if you have the RAM) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence Transformers model |
| `CHROMA_DIR` / `UPLOAD_DIR` | `./storage/...` | Local storage |
| `SENSITIVE_POLICY` | `ask` | `ask` pauses for a human decision, `mask` always masks, `allow` disables the check |
| `MAX_AGENT_STEPS` | `5` | Tool-call limit per agent |
| `MEMORY_TOP_K` / `MEMORY_MAX_DISTANCE` | `3` / `1.0` | How many past findings to recall, and how similar they must be |

## Privacy, safety and trust

- **Local only.** The LLM, embeddings, vector store and files all stay on your machine.
- **Agents cannot run code.** They choose from typed, read-only tools; failed calls return an error the agent can correct.
- **Human approval.** Row-level values under sensitive column names (email, phone, salary, card, address...) or that look sensitive
  (emails, SSNs, Aadhaar, Luhn-valid card numbers, international phone numbers) pause the run. The approval card shows
  *what* was found, never the values. Masked or excluded data is also removed from the agent summaries, charts and the streamed log.
  Aggregates such as `sum(salary) by department` are statistics and pass. Detection is heuristic, so it does not replace a data-protection review, and personal names are not detected.
- **Deleting a file** asks for confirmation. Agents have no tool that modifies or deletes anything.
- **Verification is not proof.** The support score is the share of claims backed by evidence, not a probability of correctness.
- **Memory is never evidence.** Only verified findings are remembered, never when sensitive data was involved, and the Writer is told not to cite them. You can delete any memory, or all of them, on the Dashboard.
- **Excel export is formula-safe.** All cells are stored as text, so content from uploaded files can never run as a formula.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

57 tests run the real LangGraph graph and the real FastAPI routes with a scripted fake LLM and a fake MongoDB, so they need neither Ollama nor a database.
They cover the Pandas and statistical tools, planner fallbacks, routing, the verification and revision loop, the approval pause and resume
(including a check that no raw value reaches the model after masking), memory rules, report generation, and PDF/Excel export.

## API reference

| Endpoint | Purpose |
|---|---|
| `POST /api/files/upload`, `GET /api/files`, `GET/DELETE /api/files/{id}` | Files and dataset profiles |
| `POST /api/investigate/stream` | Run the agents; streams SSE events `session`, `plan`, `log`, `approval`, `final`, `error` |
| `POST /api/investigate/resume` `{thread_id, decision}` | Continue a run paused at the approval gate (`approve` / `mask` / `reject`) |
| `POST /api/chat`, `GET /api/chat/sessions`, `GET /api/chat/{id}` | Simple RAG chat and history |
| `POST /api/reports`, `GET /api/reports[/{id}]`, `GET /api/reports/{id}/pdf` and `/xlsx` | Reports and downloads |
| `GET /api/memory`, `DELETE /api/memory[/{id}]` | Inspect and forget remembered findings |
| `GET /api/dashboard`, `GET /api/health` | Dashboard data; service status |

## Project layout

```
datapilot-ai/
├─ backend/
│  ├─ app/
│  │  ├─ main.py  config.py  db.py
│  │  ├─ routers/   files  chat  investigate  reports  memory  dashboard
│  │  ├─ services/  parsers  vectorstore  llm  export  dashboard
│  │  ├─ rag/       pipeline.py
│  │  └─ agents/    state  graph  nodes  tools  inv_tools  analysis  charts  verify  sensitive  memory  report
│  ├─ tests/        (7 files, 57 tests)
│  └─ requirements.txt  requirements-dev.txt  .env.example
├─ frontend/src/    App, api.js, components/ (Chat, Sidebar, AgentLog, ApprovalCard, Verification, ReportView, Dashboard, PlotChart, ...)
├─ scripts/make_sample_data.py
└─ docker-compose.yml   (MongoDB only)
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Red "Pull qwen3:4b" chip | Run `ollama pull qwen3:4b`; make sure Ollama is running. |
| "The investigation failed…" | Ollama is not reachable or the model is not pulled. Check `OLLAMA_BASE_URL`. |
| Red MongoDB chip | Start MongoDB (`docker compose up -d`) or fix `MONGO_URI`. |
| First upload is slow | The embedding model downloads once, and large files take longer to embed. |
| Agent picks the wrong tool or gives up | qwen3:4b is small. Rephrase more specifically (name the file and column), or set a larger Qwen3 in `OLLAMA_MODEL`. |
| "approval request is no longer available" | Pending approvals live in server memory and are lost on restart. Ask the question again. |
| `?` in the PDF where text should be | The PDF uses built-in Latin fonts, so non-Latin scripts (e.g. Devanagari) do not render. The Excel export is unaffected. |

## Known limits

- Only the first 5,000 rows of each sheet are embedded for search; the Data Agent's tools read the full file, so exact numbers are unaffected.
- Pending approvals use an in-process checkpointer. A restart cancels them; the next question starts fresh.
- Sensitive-data detection is rule-based and English-centric; it will miss some cases and flag some harmless ones.
- Small local models make mistakes. That is why verification, evidence and the revision loop exist; read the evidence before acting on a result.
- Authentication is not included; run it on a trusted machine or add a reverse proxy with auth before exposing it.

## Build history

Phase 1: upload, parsing, RAG with citations, memory · Phase 2: LangGraph agents, Pandas tools, live agent log ·
Phase 3: Investigation Agent, Plotly charts · Phase 4: Verification and Report agents, PDF/Excel export ·
Phase 5: human approval gate, cross-session memory, dashboard, sample data.
