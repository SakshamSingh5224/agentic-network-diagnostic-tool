"""Generate the importable Langflow flow (langflow_components/flows/network_diagnostic_agent.json).

Run inside the Langflow venv:
    python langflow_components/build_flow.py
Then in Langflow: Projects -> Upload a flow -> choose the JSON file.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "network_diagnostics"))

from lfx.components.input_output import ChatInput, ChatOutput  # noqa: E402
from lfx.components.models_and_agents import AgentComponent  # noqa: E402
from lfx.graph import Graph  # noqa: E402
from ping_endpoints import PingEndpointsComponent  # noqa: E402
from traceroute_tool import TracerouteComponent  # noqa: E402


def load_prompt() -> str:
    text = (HERE / "agent_system_prompt.md").read_text(encoding="utf-8")
    return re.split(r"^---\s*$", text, maxsplit=1, flags=re.M)[1].strip()


def build_graph() -> Graph:
    chat_input = ChatInput()
    ping = PingEndpointsComponent()
    trace = TracerouteComponent()
    for tool in (ping, trace):  # same as switching "Tool Mode" on in the UI
        tool.add_tool_output = True
        tool._append_tool_to_outputs_map()
    agent = AgentComponent()
    agent.set(
        system_prompt=load_prompt(),
        input_value=chat_input.message_response,
        tools=[ping.to_toolkit, trace.to_toolkit],
    )
    chat_output = ChatOutput()
    chat_output.set(input_value=agent.message_response)
    return Graph(chat_input, chat_output)


if __name__ == "__main__":
    flow = build_graph().dump(
        name="Network Diagnostic Agent",
        description="Chat Input -> Agent (ping + traceroute tools) -> Chat Output",
    )
    # Graph.dump omits layout; add it so nodes render in the Langflow canvas.
    layout = {"ChatInput": (0, 300), "PingEndpoints": (0, 0), "NetworkTraceroute": (0, 650),
              "Agent": (700, 100), "ChatOutput": (1350, 300)}
    for n in flow["data"]["nodes"]:
        x, y = layout[n["data"]["type"]]
        n.update(type="genericNode", position={"x": x, "y": y}, width=320,
                 height=800 if n["data"]["type"] == "Agent" else 420,
                 selected=False, draggable=True)
    flow["data"]["viewport"] = {"x": 50, "y": 50, "zoom": 0.6}
    out = HERE / "flows" / "network_diagnostic_agent.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(flow, indent=2), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
