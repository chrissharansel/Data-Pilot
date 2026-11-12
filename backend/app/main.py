import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import settings
from .routers import chat, codebase, dashboard, documents, files, investigate, memory, projects, reports

app = FastAPI(title="DataPilot AI", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(codebase.router)
app.include_router(files.router)
app.include_router(chat.router)
app.include_router(investigate.router)
app.include_router(reports.router)
app.include_router(memory.router)
app.include_router(dashboard.router)


@app.get("/api/health")
async def health():
    status = {
        "api": "ok",
        "mongo": "down",
        "ollama": "down",
        "model": settings.ollama_model,
        "model_ready": False,
    }
    try:
        await db.client.admin.command("ping")
        status["mongo"] = "ok"
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{settings.ollama_base_url}/api/tags")
            status["ollama"] = "ok"
            names = [m["name"] for m in r.json().get("models", [])]
            status["model_ready"] = any(n.startswith(settings.ollama_model) for n in names)
    except Exception:
        pass
    return status
