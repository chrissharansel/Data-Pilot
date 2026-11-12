"""RAG pipeline: retrieve -> build cited context -> generate. Becomes the RAG Agent's core tool in Phase 2."""
from langchain_core.prompts import ChatPromptTemplate

from ..config import settings
from ..services import vectorstore
from ..services.llm import clean, get_llm

SYSTEM = """You are DataPilot, a careful data analyst. Answer ONLY from the numbered context excerpts.
Cite evidence inline as [1], [2] matching the excerpt numbers. If the context does not contain the answer,
say so plainly and suggest what data would be needed. Never invent numbers. /no_think"""

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human", "Conversation so far:\n{history}\n\nContext:\n{context}\n\nQuestion: {question}"),
])


def retrieve(question: str, file_ids: list[str] | None, k: int | None = None) -> list[dict]:
    hits = vectorstore.search(question, k or settings.top_k, file_ids)
    return [{
        "n": i, "file_id": d.metadata.get("file_id"), "filename": d.metadata.get("filename"),
        "location": d.metadata.get("location"), "snippet": d.page_content[:600], "score": round(float(score), 4),
    } for i, (d, score) in enumerate(hits, start=1)]


def answer(question: str, file_ids: list[str] | None, history: list[dict]) -> dict:
    sources = retrieve(question, file_ids)
    if not sources:
        return {"answer": "I couldn't find any indexed content to answer from. Upload a file first.", "sources": []}
    context = "\n\n".join(f"[{s['n']}] ({s['filename']} - {s['location']})\n{s['snippet']}" for s in sources)
    hist = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history[-6:]) or "(none)"
    reply = get_llm().invoke(PROMPT.format_messages(history=hist, context=context, question=question))
    return {"answer": clean(reply.content), "sources": sources}
