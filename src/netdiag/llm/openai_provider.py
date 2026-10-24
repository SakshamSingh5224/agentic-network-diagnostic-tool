from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from netdiag.llm.base import LLMProvider, LLMResponse, ToolCallRequest

DEFAULT_MODEL = "gpt-4o-mini"


def to_openai_messages(system: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                    }
                    for tc in m["tool_calls"]
                ],
            })
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


class OpenAIProvider(LLMProvider):
    """Also works with any OpenAI-compatible server (set OPENAI_BASE_URL, e.g. Ollama)."""

    name = "openai"

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.environ.get("NETDIAG_MODEL") or DEFAULT_MODEL
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import openai
            except ImportError as exc:
                raise RuntimeError("Install the SDK: pip install -e '.[llm]'") from exc
            self._client = openai.OpenAI()  # reads OPENAI_API_KEY / OPENAI_BASE_URL
        return self._client

    def generate(self, system, messages, tools) -> LLMResponse:
        kwargs: Dict[str, Any] = dict(model=self.model, messages=to_openai_messages(system, messages))
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]
        msg = self._get_client().chat.completions.create(**kwargs).choices[0].message
        calls = [
            ToolCallRequest(
                id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}")
            )
            for tc in (msg.tool_calls or [])
        ]
        return LLMResponse(text=msg.content or "", tool_calls=calls)
