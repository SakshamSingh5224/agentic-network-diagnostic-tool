from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema import Data

from netdiag.tools import build_default_registry
from netdiag.tracing import get_default_tracer


class TracerouteComponent(Component):
    display_name = "Network Traceroute"
    description = (
        "Runs a traceroute to a host/IP and analyses the hops (where the path stops responding, "
        "latency jumps). Enable Tool Mode so the Agent can call it only when pings show an anomaly."
    )
    icon = "route"
    name = "NetworkTraceroute"

    inputs = [
        MessageTextInput(
            name="host",
            display_name="Host or IP",
            info="Destination to trace, e.g. 8.8.8.8",
            tool_mode=True,
            required=True,
        ),
    ]
    outputs = [Output(display_name="Traceroute Analysis", name="result", method="run")]

    def run(self) -> Data:
        result = build_default_registry().execute(
            "run_traceroute", {"host": self.host}, get_default_tracer(), "invoked from Langflow"
        )
        self.status = "; ".join(result.get("analysis", {}).get("findings", [])) or result.get("error", "")
        return Data(data=result)
