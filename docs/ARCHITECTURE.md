# Architecture

```
            +-------------------------- netdiag (engine, stdlib only) --------------------------+
 CLI ------>|  platform_utils  ->  probes (ping, parse) -> diagnosis (deterministic rules)        |
 Langflow-->|        |                  traceroute (run, parse, hop analysis)                     |
 components |  tools.ToolRegistry  (ping_endpoints, ping_host, run_traceroute, get_default_gateway)
            |  tracing.CallTracer  (memory + logs/agent_trace.jsonl)     report (plain text)     |
            |  agent: RuleBasedAgent | LLMAgent --> llm.LLMProvider (anthropic | openai | ...)   |
            +--------------------------------------------------------------------------------------+
```

Design principle: **the engine is deterministic and trusted; the LLM only chooses tools and explains.**
Numbers in the final report always come from the tools, never from the model.

## Requirement traceability

| Req | Implementation | Tests |
|---|---|---|
| FR1 multi-endpoint ping | `probes.ping_all` (concurrent; gateway auto-detected via `platform_utils`) | `test_ping_parsing`, `test_gateway` |
| FR2 parse + diagnose | `probes.parse_ping_output`, `diagnosis.diagnose` | `test_ping_parsing`, `test_diagnosis` |
| FR3 agentic traceroute | `LLMAgent` tool loop; `RuleBasedAgent` trigger on `needs_traceroute`; `traceroute.py` | `test_agent_cli`, `test_traceroute` |
| FR4 Langflow orchestration | `langflow_components/` wrapping the shared registry | manual (see its README) |
| FR5 call tracing | `tracing.CallTracer`, JSONL log, `--show-trace` | `test_tracing_tools` |
| FR6 plain-text report | `report.render_report` (+ LLM narrative) | `test_agent_cli` |
| NFR1 < 5 s ping phase | parallel pings, per-OS hard deadline (`-w`/`-t`), subprocess timeout 4.5 s | `test_platform` cmds |
| NFR2 graceful failure | every runner/tool/agent boundary returns errors as data; LLM failure falls back to rules | `*_survives_*`, `*_never_raises` |
| NFR3 scalability | `ToolRegistry.register`, one component file per tool | `test_new_tool_is_exposed...` |
| NFR4 extensibility | `LLMProvider` interface, neutral message format, scripted provider for tests | provider conversion tests |
| NFR5 platform independence | `platform_utils` (Linux/macOS/Windows commands + parsers) | `test_ping_commands_per_os`, parser tests |

## Security notes

* Hosts passed to ping/traceroute (including ones chosen by an LLM) are validated by `is_valid_host`
  and commands run with `shell=False`, preventing option and command injection.
* The LLM only ever sees tool output (IPs, latencies, hops) - and only in `--mode llm`.
