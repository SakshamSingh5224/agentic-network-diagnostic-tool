from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from netdiag.llm.base import LLMProvider, LLMResponse, ToolCallRequest

DEFAULT_MODEL = "claude-sonnet-5-5"


def to_anthropic_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Neutral messages -> Anthropic format (tool results are merged into one user turn)."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            blocks: List[Dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls", []):
                blocks.append(
                    {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]}
                )
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            prev = out[-1] if out else None
            if prev and prev["role"] == "user" and isinstance(prev["content"], list):
                prev["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: Optional[str] = None, max_tokens: int = 1024):
        self.model = model or os.environ.get("NETDIAG_MODEL") or DEFAULT_MODEL
        self.max_tokens = max_tokens
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError("Install the SDK: pip install -e '.[llm]'") from exc
            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        return self._client

    def generate(self, system, messages, tools) -> LLMResponse:
        kwargs: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=to_anthropic_messages(messages),
        )
        if tools:
            kwargs["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                for t in tools
            ]
        resp = self._get_client().messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            ToolCallRequest(id=b.id, name=b.name, arguments=dict(b.input))
            for b in resp.content
            if b.type == "tool_use"
        ]
        return LLMResponse(text=text, tool_calls=calls)
