from __future__ import annotations

from typing import Optional

from netdiag.llm.base import LLMProvider, LLMResponse, ToolCallRequest

__all__ = ["LLMProvider", "LLMResponse", "ToolCallRequest", "get_provider"]


def get_provider(name: str, model: Optional[str] = None) -> LLMProvider:
    """Factory. Add new providers here - nothing else in the codebase needs to change."""
    if name == "anthropic":
        from netdiag.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model)
    if name == "openai":
        from netdiag.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(model)
    raise ValueError(f"unknown provider {name!r} (choose: anthropic, openai)")
