import json

import pytest

from conftest import down, healthy
from netdiag import agent as agent_mod
from netdiag import cli
from netdiag.agent import LLMAgent, RuleBasedAgent
from netdiag.config import Settings
from netdiag.diagnosis import diagnose
from netdiag.llm import get_provider
from netdiag.llm.anthropic_provider import to_anthropic_messages
from netdiag.llm.base import LLMProvider, LLMResponse, ToolCallRequest
from netdiag.llm.openai_provider import to_openai_messages
from netdiag.llm.scripted import ScriptedProvider
from netdiag.report import render_report
from netdiag.tools import Tool, ToolRegistry
from netdiag.tracing import CallTracer

TRACE = {"host": "8.8.8.8", "reached": False, "analysis": {"findings": ["Path stops after hop 2."]}}


def make_registry(pings):
    """Registry whose tools return canned data - no real network."""
    reg = ToolRegistry()

    def ping_endpoints(gateway=None):
        return {"gateway": "192.168.1.1", "pings": {k: v.to_dict() for k, v in pings.items()},
                "diagnosis": diagnose(pings).to_dict()}

    reg.register(Tool("ping_endpoints", "d", {"type": "object"}, ping_endpoints))
    reg.register(Tool("run_traceroute", "d", {"type": "object"}, lambda host: {**TRACE, "host": host}))
    return reg


def isp_down():
    return {"gateway": healthy("192.168.1.1"), "google_dns": down("8.8.8.8"), "cloudflare_dns": down("1.1.1.1")}


def all_ok():
    return {"gateway": healthy("192.168.1.1"), "google_dns": healthy("8.8.8.8"), "cloudflare_dns": healthy("1.1.1.1")}


# ---- rule-based agent ---------------------------------------------------
def test_rules_agent_traces_on_failure_and_logs_sequence():
    t = CallTracer()
    r = RuleBasedAgent(make_registry(isp_down()), t, Settings()).run()
    assert r.diagnosis["status"] == "isp_issue" and len(r.traces) == 1
    assert [e.tool for e in t.entries if e.kind == "tool_call"] == ["ping_endpoints", "run_traceroute"]
    assert "ISP" in r.text and "Path stops after hop 2" in r.text and "Recommended steps" in r.text


def test_rules_agent_skips_traceroute_when_healthy():
    t = CallTracer()
    r = RuleBasedAgent(make_registry(all_ok()), t).run()
    assert r.traces == [] and r.diagnosis["status"] == "healthy"
    assert [e.tool for e in t.entries if e.kind == "tool_call"] == ["ping_endpoints"]


def test_rules_agent_no_trace_flag():
    r = RuleBasedAgent(make_registry(isp_down()), CallTracer(), allow_trace=False).run()
    assert r.traces == []


def test_rules_agent_survives_ping_tool_failure():
    reg = ToolRegistry()
    reg.register(Tool("ping_endpoints", "d", {"type": "object"}, lambda gateway=None: 1 / 0))
    r = RuleBasedAgent(reg, CallTracer()).run()
    assert r.diagnosis["status"] == "inconclusive"


# ---- LLM agent ------------------------------------------------------------
def script(*responses):
    return ScriptedProvider(list(responses))


def test_llm_agent_full_loop():
    p = script(
        LLMResponse("Checking.", [ToolCallRequest("1", "ping_endpoints", {})]),
        LLMResponse("Tracing.", [ToolCallRequest("2", "run_traceroute", {"host": "8.8.8.8"})]),
        LLMResponse("Your ISP link is down. Reboot the modem."),
    )
    t = CallTracer()
    r = LLMAgent(p, make_registry(isp_down()), t, Settings()).run()
    assert r.mode == "llm" and "Reboot the modem" in r.text and "UNREACHABLE" in r.text
    assert [e.tool for e in t.entries if e.kind == "tool_call"] == ["ping_endpoints", "run_traceroute"]
    # tool results were fed back to the model
    assert any(m["role"] == "tool" for m in p.calls[-1])


def test_llm_agent_falls_back_when_provider_crashes():
    class Broken(LLMProvider):
        def generate(self, *a):
            raise RuntimeError("401 bad key")
    r = LLMAgent(Broken(), make_registry(isp_down()), CallTracer(), Settings()).run()
    assert r.mode == "llm-fallback" and r.diagnosis["status"] == "isp_issue"


def test_llm_agent_pings_for_itself_if_model_skips_tools():
    r = LLMAgent(script(LLMResponse("All good!")), make_registry(all_ok()), CallTracer()).run()
    assert r.mode == "llm-fallback" and r.diagnosis["status"] == "healthy"


def test_llm_agent_blocks_traceroute_when_disabled():
    p = script(
        LLMResponse("", [ToolCallRequest("1", "ping_endpoints", {})]),
        LLMResponse("", [ToolCallRequest("2", "run_traceroute", {"host": "8.8.8.8"})]),
        LLMResponse("done"),
    )
    r = LLMAgent(p, make_registry(isp_down()), CallTracer(), allow_trace=False).run()
    assert r.traces == []
    assert "disabled" in p.calls[-1][-1]["content"]


def test_llm_agent_unknown_tool_is_reported_back_not_crash():
    p = script(
        LLMResponse("", [ToolCallRequest("1", "ping_endpoints", {})]),
        LLMResponse("", [ToolCallRequest("2", "format_disk", {})]),
        LLMResponse("done"),
    )
    r = LLMAgent(p, make_registry(all_ok()), CallTracer()).run()
    assert r.mode == "llm" and "unknown tool" in p.calls[-1][-1]["content"]


# ---- provider message conversion (no SDK needed) ---------------------------
NEUTRAL = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "calling", "tool_calls": [
        {"id": "a", "name": "ping_endpoints", "arguments": {}},
        {"id": "b", "name": "run_traceroute", "arguments": {"host": "8.8.8.8"}}]},
    {"role": "tool", "tool_call_id": "a", "name": "ping_endpoints", "content": "{}"},
    {"role": "tool", "tool_call_id": "b", "name": "run_traceroute", "content": "{}"},
]


def test_anthropic_conversion_merges_tool_results():
    out = to_anthropic_messages(NEUTRAL)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert [b["type"] for b in out[1]["content"]] == ["text", "tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["a", "b"]


def test_openai_conversion():
    out = to_openai_messages("SYS", NEUTRAL)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert json.loads(out[2]["tool_calls"][1]["function"]["arguments"]) == {"host": "8.8.8.8"}
    assert [m["role"] for m in out[3:]] == ["tool", "tool"]


def test_provider_factory():
    assert get_provider("anthropic").name == "anthropic" and get_provider("openai").name == "openai"
    with pytest.raises(ValueError):
        get_provider("nope")


# ---- report + CLI ------------------------------------------------------------
def test_report_with_narrative_still_prints_facts():
    d = diagnose(isp_down()).to_dict()
    text = render_report(d, narrative="Your ISP is down.")
    assert "Your ISP is down." in text and "8.8.8.8" in text and "Recommended steps" not in text


def test_cli_run_json_and_exit_code(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(agent_mod, "build_default_registry", lambda s=None: make_registry(isp_down()))
    code = cli.main(["run", "--json", "--trace-log", str(tmp_path / "t.jsonl")])
    data = json.loads(capsys.readouterr().out)
    assert code == 1 and data["status"] == "isp_issue" and len(data["agent_trace"]) >= 2
    assert (tmp_path / "t.jsonl").exists()


def test_cli_healthy_exit_zero(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(agent_mod, "build_default_registry", lambda s=None: make_registry(all_ok()))
    assert cli.main(["run", "--show-trace", "--trace-log", str(tmp_path / "t.jsonl")]) == 0
    assert "Agent trace" in capsys.readouterr().out


def test_cli_ping_survives_missing_ping(monkeypatch, capsys):
    from netdiag.models import PingResult

    def no_ping(gw, settings):
        return {k: PingResult(host=k, error="command not found: ping")
                for k in ("google_dns", "cloudflare_dns")}

    monkeypatch.setattr(cli, "ping_all", no_ping)
    monkeypatch.setattr(cli, "detect_default_gateway", lambda: None)
    assert cli.main(["ping"]) == 2
    assert "INCONCLUSIVE" in capsys.readouterr().out
