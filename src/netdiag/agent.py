"""Phase 3 - agents that orchestrate ping -> diagnose -> (traceroute) -> report.

RuleBasedAgent : deterministic, offline, no LLM. Same tools + tracing.
LLMAgent       : an LLM decides which tools to call (FR3); falls back to the
                 rule-based result if the LLM/provider fails (NFR2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from netdiag.config import Settings
from netdiag.llm.base import LLMProvider
from netdiag.prompts import DEFAULT_USER_PROMPT, SYSTEM_PROMPT
from netdiag.report import render_report
from netdiag.tools import ToolRegistry, build_default_registry
from netdiag.tracing import CallTracer


@dataclass
class AgentReport:
    text: str
    diagnosis: Dict[str, Any] = field(default_factory=dict)
    pings: Dict[str, Any] = field(default_factory=dict)
    traces: List[Dict[str, Any]] = field(default_factory=list)
    agent_trace: List[Dict[str, Any]] = field(default_factory=list)
    mode: str = "rules"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "status": self.diagnosis.get("status"),
            "report": self.text,
            "diagnosis": self.diagnosis,
            "pings": self.pings,
            "traceroutes": self.traces,
            "agent_trace": self.agent_trace,
        }


class RuleBasedAgent:
    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        tracer: Optional[CallTracer] = None,
        settings: Optional[Settings] = None,
        gateway: Optional[str] = None,
        allow_trace: bool = True,
    ):
        self.settings = settings or Settings()
        self.registry = registry or build_default_registry(self.settings)
        self.tracer = tracer or CallTracer(self.settings.trace_log_path)
        self.gateway = gateway
        self.allow_trace = allow_trace

    def run(self) -> AgentReport:
        t = self.tracer
        t.note("Collect a baseline: ping gateway, Google DNS and Cloudflare DNS.")
        args = {"gateway": self.gateway} if self.gateway else {}
        ping_out = self.registry.execute("ping_endpoints", args, t, "Baseline connectivity check")
        if "error" in ping_out:
            diag = {
                "status": "inconclusive", "severity": "unknown",
                "summary": f"Ping stage failed: {ping_out['error']}",
                "findings": [], "needs_traceroute": False, "trace_targets": [],
            }
            return AgentReport(render_report(diag), diag, {}, [], t.to_list(), "rules")

        diag = ping_out["diagnosis"]
        traces: List[Dict[str, Any]] = []
        if diag["needs_traceroute"] and self.allow_trace:
            targets = diag["trace_targets"][: self.settings.max_traces]
            t.note(f"Anomaly detected ({diag['status']}); tracing {', '.join(targets)}.")
            for host in targets:
                traces.append(
                    self.registry.execute(
                        "run_traceroute", {"host": host}, t,
                        f"Locate where the path to {host} breaks or slows down",
                    )
                )
        else:
            t.note("No traceroute needed." if not diag["needs_traceroute"] else "Traceroute disabled.")
        return AgentReport(
            render_report(diag, traces), diag, ping_out.get("pings", {}), traces, t.to_list(), "rules"
        )


class LLMAgent:
    def __init__(
        self,
        provider: LLMProvider,
        registry: Optional[ToolRegistry] = None,
        tracer: Optional[CallTracer] = None,
        settings: Optional[Settings] = None,
        gateway: Optional[str] = None,
        allow_trace: bool = True,
    ):
        self.provider = provider
        self.settings = settings or Settings()
        self.registry = registry or build_default_registry(self.settings)
        self.tracer = tracer or CallTracer(self.settings.trace_log_path)
        self.gateway = gateway
        self.allow_trace = allow_trace

    def _tool_specs(self) -> List[Dict[str, Any]]:
        return [
            s for s in self.registry.specs() if self.allow_trace or s["name"] != "run_traceroute"
        ]

    def run(self, user_prompt: str = DEFAULT_USER_PROMPT) -> AgentReport:
        t = self.tracer
        prompt = user_prompt + (f" (My gateway IP is {self.gateway}.)" if self.gateway else "")
        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
        diag: Dict[str, Any] = {}
        pings: Dict[str, Any] = {}
        traces: List[Dict[str, Any]] = []
        final_text = ""
        t.note(f"LLM agent started with provider={self.provider.name}.")

        try:
            for _ in range(self.settings.max_agent_steps):
                resp = self.provider.generate(SYSTEM_PROMPT, messages, self._tool_specs())
                if resp.text:
                    t.note(f"model: {resp.text[:300]}")
                if not resp.tool_calls:
                    final_text = resp.text
                    break
                messages.append({
                    "role": "assistant", "content": resp.text,
                    "tool_calls": [
                        {"id": c.id, "name": c.name, "arguments": c.arguments} for c in resp.tool_calls
                    ],
                })
                for call in resp.tool_calls:
                    if not self.allow_trace and call.name == "run_traceroute":
                        result: Dict[str, Any] = {"error": "traceroute is disabled by the user"}
                    else:
                        result = self.registry.execute(call.name, call.arguments, t, resp.text[:200])
                    if call.name == "ping_endpoints" and "diagnosis" in result:
                        diag, pings = result["diagnosis"], result.get("pings", {})
                    elif call.name == "run_traceroute" and "error" not in result:
                        traces.append(result)
                    messages.append({
                        "role": "tool", "tool_call_id": call.id, "name": call.name,
                        "content": json.dumps(result)[:12000],
                    })
        except Exception as exc:  # noqa: BLE001 - provider/network/auth failure
            t.note(f"LLM stage failed ({exc}); falling back to rule-based report.")
            final_text = ""

        if not diag:  # model never pinged (or crashed) -> make sure we still diagnose
            fallback = RuleBasedAgent(
                self.registry, t, self.settings, self.gateway, self.allow_trace
            ).run()
            fallback.mode = "llm-fallback"
            return fallback

        text = render_report(diag, traces, narrative=final_text) if final_text else render_report(diag, traces)
        return AgentReport(text, diag, pings, traces, t.to_list(), "llm")
