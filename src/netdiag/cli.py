"""Command line interface: `netdiag run | ping | trace`.

Exit codes (script-friendly): 0 healthy, 1 problem found, 2 inconclusive/error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from typing import List, Optional

from netdiag.agent import AgentReport, LLMAgent, RuleBasedAgent
from netdiag.config import Settings
from netdiag.diagnosis import diagnose
from netdiag.llm import get_provider
from netdiag.platform_utils import detect_default_gateway
from netdiag.probes import ping_all
from netdiag.report import render_report
from netdiag.traceroute import run_traceroute
from netdiag.tracing import CallTracer


def _exit_code(status: Optional[str]) -> int:
    return {"healthy": 0, "inconclusive": 2, None: 2}.get(status, 1)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="netdiag", description="Agentic network diagnostic tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--gateway", help="Gateway IP (default: auto-detect)")
        sp.add_argument("--json", action="store_true", help="Machine-readable output")

    run = sub.add_parser("run", help="Full diagnosis: ping, diagnose, agentic traceroute, report")
    common(run)
    run.add_argument("--mode", choices=["rules", "llm"], default="rules",
                     help="rules = deterministic, offline (default); llm = AI agent decides tool calls")
    run.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    run.add_argument("--model", help="Override the provider's default model")
    run.add_argument("--no-trace", action="store_true", help="Never run traceroute")
    run.add_argument("--max-traces", type=int, default=1, help="Max traceroutes per run")
    run.add_argument("--show-trace", action="store_true", help="Print the agent call trace")
    run.add_argument("--trace-log", default=Settings().trace_log_path, help="JSONL trace log path")

    ping = sub.add_parser("ping", help="Ping probes + deterministic diagnosis only (no traceroute)")
    common(ping)

    tr = sub.add_parser("trace", help="Run and analyse a single traceroute")
    tr.add_argument("host")
    tr.add_argument("--json", action="store_true")
    return p


def _cmd_ping(args: argparse.Namespace) -> int:
    s = Settings()
    gw = args.gateway or detect_default_gateway()
    pings = ping_all(gw, s)
    diag = diagnose(pings, s).to_dict()
    if args.json:
        print(json.dumps({"pings": {k: v.to_dict() for k, v in pings.items()}, "diagnosis": diag}, indent=2))
    else:
        print(render_report(diag))
    return _exit_code(diag["status"])


def _cmd_trace(args: argparse.Namespace) -> int:
    res = run_traceroute(args.host)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        for h in res.hops:
            rtt = f"{h.best_rtt:.1f} ms" if h.best_rtt is not None else "*"
            print(f"{h.index:>3}  {h.address or '*':<18} {rtt}")
        for f in res.analysis.get("findings", []):
            print(f"- {f}")
        if res.error:
            print(f"error: {res.error}", file=sys.stderr)
    return 0 if res.reached else (2 if res.error else 1)


def _cmd_run(args: argparse.Namespace) -> int:
    s = replace(Settings(), max_traces=args.max_traces, trace_log_path=args.trace_log)
    tracer = CallTracer(s.trace_log_path)
    kwargs = dict(tracer=tracer, settings=s, gateway=args.gateway, allow_trace=not args.no_trace)
    if args.mode == "llm":
        agent = LLMAgent(get_provider(args.provider, args.model), **kwargs)
    else:
        agent = RuleBasedAgent(**kwargs)
    report: AgentReport = agent.run()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.text)
        if args.show_trace:
            print("\n" + tracer.format())
        print(f"\n(trace log: {s.trace_log_path})")
    return _exit_code(report.diagnosis.get("status"))


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    handler = {"run": _cmd_run, "ping": _cmd_ping, "trace": _cmd_trace}[args.cmd]
    try:
        return handler(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
