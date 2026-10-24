"""Provider-neutral LLM interface (NFR4). Swap models without touching the agent or tools.

Neutral message format used by the agent:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCallRequest-as-dict, ...]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: List[ToolCallRequest] = field(default_factory=list)


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def generate(
        self, system: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> LLMResponse:
        """Return the model's next turn: final text and/or tool-call requests."""
