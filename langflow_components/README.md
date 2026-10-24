# Langflow integration (FR4)

The Python package `netdiag` is the engine; Langflow only orchestrates it. Three custom components wrap the
shared tool registry, so adding a new tool later (speed test, port scan) means one `registry.register(...)` plus
one small component file.

| Component | Purpose | Use as |
|---|---|---|
| Network Ping Diagnostics | ping gateway + 8.8.8.8 + 1.1.1.1, deterministic diagnosis | Agent tool (Tool Mode) |
| Network Traceroute | traceroute + hop analysis | Agent tool (Tool Mode) |
| Plain-Text Network Report | LLM-free report builder | normal node |

## Setup

```bash
# from the repo root, in a virtualenv
pip install -e ".[langflow]"
export LANGFLOW_COMPONENTS_PATH="$(pwd)/langflow_components"
langflow run            # opens http://127.0.0.1:7860
```
`netdiag` must be installed in the *same* environment as Langflow (the `pip install -e` above does that).

## Build the flow (about 3 minutes)

1. New flow -> add **Chat Input**, **Agent**, **Chat Output**.
2. Search "Network" in the sidebar and add **Network Ping Diagnostics** and **Network Traceroute**.
   On each, click **Tool Mode** (toggle in the component header) and connect the *Toolset* output to the Agent's **Tools** input.
3. In the Agent: pick your model/provider + API key, and paste `agent_system_prompt.md` into **Agent Instructions**.
4. Wire Chat Input -> Agent -> Chat Output. Open the Playground and send: *"Why is my internet down?"*
5. (Optional) Export via **Export** and commit the JSON under `langflow_components/flows/`.

## Tracing (FR5)

* Every tool call from these components is appended to `logs/agent_trace.jsonl` (tool, arguments, duration, summary).
  Override with `NETDIAG_TRACE_LOG`.
* Langflow's own Playground also shows each tool call and the Agent's reasoning steps.
