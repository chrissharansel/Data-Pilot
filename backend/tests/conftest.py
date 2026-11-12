import pytest

from app.agents import nodes


@pytest.fixture(autouse=True)
def no_real_memory(monkeypatch):
    """Tests never touch Chroma or the embedding model; memory tests install their own recall."""
    monkeypatch.setattr(nodes, "recall_memories", lambda question, names, k=None: [])
