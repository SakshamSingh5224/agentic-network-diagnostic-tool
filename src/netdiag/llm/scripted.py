"""Deterministic provider for tests and offline demos: replays a fixed list of responses."""

from __future__ import annotations

from typing import Any, Dict, List

from netdiag.llm.base import LLMProvider, LLMResponse


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, responses: List[LLMResponse]):
        self._responses = list(responses)
        self.calls: List[List[Dict[str, Any]]] = []  # messages seen per call

    def generate(self, system, messages, tools) -> LLMResponse:
        self.calls.append(list(messages))
        if not self._responses:
            return LLMResponse(text="(script exhausted)")
        return self._responses.pop(0)
