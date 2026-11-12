"""ChromaDB + Sentence-Transformers wrapper. One collection; every chunk carries file_id metadata."""
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from ..config import settings


@lru_cache
def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name=settings.embedding_model)


@lru_cache
def get_store() -> Chroma:
    return Chroma(collection_name="datapilot", embedding_function=get_embeddings(), persist_directory=settings.chroma_dir)


@lru_cache
def get_memory_store() -> Chroma:
    return Chroma(collection_name="datapilot_memory", embedding_function=get_embeddings(), persist_directory=settings.chroma_dir)


def add_memory(memory_id: str, text: str, meta: dict) -> None:
    get_memory_store().add_texts([text], metadatas=[meta], ids=[memory_id])


def delete_memory(ids: list[str]) -> None:
    if ids:
        get_memory_store().delete(ids=ids)


def search_memory(query: str, k: int) -> list[tuple[Document, float]]:
    return get_memory_store().similarity_search_with_score(query, k=k)


def add_documents(docs: list[Document], file_id: str) -> int:
    for d in docs:
        d.metadata["file_id"] = file_id
    ids = [f"{file_id}-{i}" for i in range(len(docs))]
    for s in range(0, len(docs), 128):  # batch to keep memory low
        get_store().add_documents(docs[s:s + 128], ids=ids[s:s + 128])
    return len(docs)


def delete_file(file_id: str) -> None:
    get_store().delete(where={"file_id": file_id})


def search(query: str, k: int, file_ids: list[str] | None = None) -> list[tuple[Document, float]]:
    flt = None
    if file_ids:
        flt = {"file_id": file_ids[0]} if len(file_ids) == 1 else {"file_id": {"$in": file_ids}}
    return get_store().similarity_search_with_score(query, k=k, filter=flt)
