"""Tool registry (NFR3 / NFR4).

Each diagnostic capability is a `Tool`: name + description + JSON-schema + a plain
function returning a JSON-serialisable dict. The same registry feeds
  * the rule-based agent,
  * any LLM provider (via `specs()`),
  * the Langflow components.
Adding a future tool (speed test, port scan, ...) = one `registry.register(Tool(...))`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from netdiag.config import Settings
from netdiag.diagnosis import diagnose
from netdiag.platform_utils import detect_default_gateway, is_valid_host
from netdiag.probes import ping_all, ping_host
from netdiag.traceroute import run_traceroute
from netdiag.tracing import CallTracer


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON schema for the arguments object
    func: Callable[..., Dict[str, Any]]
    summarize: Optional[Callable[[Dict[str, Any]], str]] = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> List[str]:
        return list(self._tools)

    def specs(self) -> List[Dict[str, Any]]:
        """Provider-neutral tool specs: {name, description, parameters}."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    def execute(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        tracer: Optional[CallTracer] = None,
        reasoning: str = "",
    ) -> Dict[str, Any]:
        """Run a tool. Never raises - errors come back as {"error": ...} (NFR2)."""
        args = arguments or {}
        tool = self._tools.get(name)
        tracer = tracer or CallTracer()
        with tracer.span(name, args, reasoning) as entry:
            if tool is None:
                entry.status, entry.error = "error", f"unknown tool: {name}"
                return {"error": f"unknown tool: {name}", "available": self.names()}
            try:
                result = tool.func(**args)
            except TypeError as exc:
                entry.status, entry.error = "error", f"bad arguments: {exc}"
                return {"error": f"bad arguments for {name}: {exc}"}
            except Exception as exc:  # noqa: BLE001
                entry.status, entry.error = "error", str(exc)
                return {"error": f"{name} failed: {exc}"}
            entry.result_summary = (tool.summarize(result) if tool.summarize else str(result))[:300]
            return result


def build_default_registry(settings: Optional[Settings] = None) -> ToolRegistry:
    s = settings or Settings()
    reg = ToolRegistry()

    def get_default_gateway() -> Dict[str, Any]:
        return {"gateway": detect_default_gateway()}

    def ping_endpoints(gateway: Optional[str] = None) -> Dict[str, Any]:
        gw = gateway or detect_default_gateway()
        if gateway and not is_valid_host(gateway):
            return {"error": f"invalid gateway: {gateway!r}"}
        pings = ping_all(gw, s)
        diagnosis = diagnose(pings, s)
        return {
            "gateway": gw,
            "pings": {k: v.to_dict() for k, v in pings.items()},
            "diagnosis": diagnosis.to_dict(),
        }

    def ping_one(host: str) -> Dict[str, Any]:
        return ping_host(host, host, s).to_dict()

    def traceroute(host: str) -> Dict[str, Any]:
        return run_traceroute(host, s).to_dict()

    reg.register(Tool(
        "get_default_gateway",
        "Detect the IP address of this machine's default gateway (WiFi router / phone hotspot).",
        {"type": "object", "properties": {}},
        get_default_gateway,
        lambda r: f"gateway={r.get('gateway')}",
    ))
    reg.register(Tool(
        "ping_endpoints",
        "Ping the local WiFi gateway, Google DNS (8.8.8.8) and Cloudflare DNS (1.1.1.1) in "
        "parallel, parse loss/latency, and return a deterministic diagnosis (status, findings, "
        "whether a traceroute is recommended and to which hosts). ALWAYS call this first.",
        {
            "type": "object",
            "properties": {
                "gateway": {
                    "type": "string",
                    "description": "Optional gateway IP. Omit to auto-detect.",
                }
            },
        },
        ping_endpoints,
        lambda r: r.get("error") or f"status={r['diagnosis']['status']}; {r['diagnosis']['summary']}",
    ))
    reg.register(Tool(
        "ping_host",
        "Ping a single host or IP to check reachability and latency.",
        {
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Hostname or IP"}},
            "required": ["host"],
        },
        ping_one,
        lambda r: f"{r['host']}: loss={r['loss_pct']}% avg={r['rtt_avg_ms']}ms err={r['error']}",
    ))
    reg.register(Tool(
        "run_traceroute",
        "Run a traceroute to a host/IP and return the hops plus an analysis (where the path "
        "stops responding, latency jumps). Use it only when ping_endpoints reports an anomaly "
        "or an unreachable node.",
        {
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Hostname or IP to trace"}},
            "required": ["host"],
        },
        traceroute,
        lambda r: r.get("error") or "; ".join(r.get("analysis", {}).get("findings", []))[:250],
    ))
    return reg
