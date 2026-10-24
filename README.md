# Agentic Network Diagnostic Tool

Diagnoses *why* your internet is slow or down. It pings your WiFi gateway, Google DNS (8.8.8.8) and
Cloudflare DNS (1.1.1.1), classifies the failure with a deterministic engine, and - when something is wrong -
lets an AI agent run and interpret a **traceroute**, then explains the result in plain English with fix steps.

```
$ netdiag run --show-trace
NETWORK DIAGNOSIS: ISP / UPSTREAM ISSUE
Your local network is fine but neither Google DNS nor Cloudflare DNS is reachable ...
  - WiFi gateway (192.168.1.1): reachable, 0% loss, 2.1 ms avg
  - Google DNS (8.8.8.8): UNREACHABLE, 100% packet loss
Traceroute to 8.8.8.8:
  - The path stops responding after hop 2 (100.64.0.1, carrier-grade NAT) ...
```

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .                  # core: pure standard library, no dependencies
pip install -e ".[llm]"           # + Anthropic/OpenAI SDKs for --mode llm
pip install -e ".[langflow]"      # + Langflow
pip install -e ".[dev]"           # + pytest, ruff
```
Linux needs `ping` and `traceroute` (`sudo apt install iputils-ping traceroute`). macOS and Windows ship with them.

## Use

```bash
netdiag ping                       # Phase 1+2: probes + deterministic diagnosis (fast, no traceroute)
netdiag run                        # full run; traceroute only if an anomaly is found (offline, no LLM)
netdiag run --show-trace           # also print the sequence of tool calls (FR5)
netdiag run --gateway 192.168.43.1 # phone hotspot / gateway auto-detect failed
netdiag run --json                 # machine-readable
netdiag trace 8.8.8.8              # standalone traceroute + analysis

# AI agent mode: the LLM decides which tools to call and writes the explanation
export ANTHROPIC_API_KEY=...       # or OPENAI_API_KEY (+ --provider openai)
netdiag run --mode llm --show-trace
```
Exit codes: `0` healthy, `1` problem found, `2` inconclusive - handy for cron/monitoring.
Every tool call is also appended to `logs/agent_trace.jsonl`.

If the LLM call fails (bad key, no network - which is exactly when you need this tool), the run **falls back to the
deterministic report** instead of crashing.

## Diagnosis rules

| Gateway | Google / Cloudflare | Status |
|---|---|---|
| down / lossy / slow | any | **Local network issue** |
| OK | both down | **ISP issue** |
| OK | one down | **External DNS endpoint issue** |
| OK | loss >= 10% or latency >= 150 ms | **Degraded connection** |
| OK | OK | **Healthy** |
| not detected, externals down | | Inconclusive (traceroute still run) |
| `ping` unavailable | | Inconclusive |

Thresholds live in `src/netdiag/config.py`.

## Langflow

See [`langflow_components/README.md`](langflow_components/README.md): three drop-in components
(Ping, Traceroute, Report) that wrap the same tool registry, plus the agent system prompt.

## Extending (NFR3 / NFR4)

* **New diagnostic tool** (speed test, port scan): add a function and `registry.register(Tool(...))` in
  `src/netdiag/tools.py`. It is automatically exposed to every LLM provider and logged by the tracer.
* **New LLM**: subclass `LLMProvider` (one method, `generate`) and add it to `get_provider`.
  OpenAI-compatible servers (Ollama, vLLM) already work via `OPENAI_BASE_URL`.

## Development

```bash
pytest      # 80 tests, no network required
ruff check .
```
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the requirement-to-code traceability matrix.

## Limitations

* ICMP can be blocked by firewalls/captive portals; a "down" result means "no ICMP reply".
* Non-English Windows installs: the summary line is localised, so the parser falls back to per-reply `time=` lines.
* Some routers ignore traceroute probes; the analysis says so rather than blaming them.
* The Langflow components follow the documented component API but need to be loaded into a live Langflow once to confirm for your version.

## Using Groq (or any OpenAI-compatible provider)

The `openai` provider works with any OpenAI-compatible endpoint, including Groq and Ollama:

```bash
pip install -e ".[llm]"
export OPENAI_BASE_URL="https://api.groq.com/openai/v1"
read -s -p "Groq API key: " OPENAI_API_KEY; export OPENAI_API_KEY; echo

# list the models your key can use, then pick a chat model that supports tool calling
curl -s "$OPENAI_BASE_URL/models" -H "Authorization: Bearer $OPENAI_API_KEY" \
  | python3 -c "import sys,json; [print(m['id']) for m in json.load(sys.stdin)['data']]"

netdiag run --mode llm --provider openai --model openai/gpt-oss-120b --show-trace
```

Notes:
* Use a general chat model. Speech, TTS and guard models cannot drive the agent.
* Small models may skip the tools; the run then reports `llm-fallback` and still prints a correct report.
* The measured values in the report always come from the tools, not the model.
