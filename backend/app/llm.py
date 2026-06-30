"""LLM factory: gpt-oss-120b via the Azure OpenAI-compatible /openai/v1 endpoint.

Plain ChatOpenAI (NOT AzureChatOpenAI) — the endpoint is OpenAI-compatible, so the
standard v1 client + base_url is correct; AzureChatOpenAI would build ?api-version
URLs and 400 on tool calls.
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import Settings, get_settings


def build_llm(settings: Settings | None = None) -> ChatOpenAI:
    s = settings or get_settings()
    # reasoning_effort is a top-level langchain-openai param; if a gateway rejects it,
    # the documented fallback is model_kwargs={"extra_body": {"reasoning_effort": ...}}.
    return ChatOpenAI(
        model=s.deployment,
        base_url=s.base_url,
        api_key=s.api_key,
        reasoning_effort=s.reasoning_effort,
    )
