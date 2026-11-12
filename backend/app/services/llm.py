import re
from functools import lru_cache

from langchain_ollama import ChatOllama

from ..config import settings

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


@lru_cache
def get_llm(temperature: float = 0.2, json_mode: bool = False) -> ChatOllama:
    return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url,
                      temperature=temperature, format="json" if json_mode else None)


def clean(text: str) -> str:
    """Qwen3 can emit <think> blocks; strip them from user-visible output."""
    return _THINK.sub("", text).strip()
