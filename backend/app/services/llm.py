import re
from functools import lru_cache

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

from ..config import settings

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


@lru_cache
def get_llm(temperature: float = 0.2, json_mode: bool = False) -> ChatOllama:
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        format="json" if json_mode else None,
    )


def clean(text: str) -> str:
    """Qwen3 can emit <think> blocks; strip them from user-visible output."""
    return _THINK.sub("", text).strip()


async def chat(messages: list[dict], temperature: float = 0.3) -> str:
    """Simple chat helper used by document generation and other one-shot calls."""
    llm = get_llm(temperature=temperature)
    lc_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        else:
            lc_messages.append(HumanMessage(content=content))
    result = await llm.ainvoke(lc_messages)
    return clean(result.content if hasattr(result, "content") else str(result))
