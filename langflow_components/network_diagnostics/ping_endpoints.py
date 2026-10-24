from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema import Data

from netdiag.tools import build_default_registry
from netdiag.tracing import get_default_tracer


class PingEndpointsComponent(Component):
    display_name = "Network Ping Diagnostics"
    description = (
        "Pings the WiFi gateway, Google DNS (8.8.8.8) and Cloudflare DNS (1.1.1.1), parses "
        "loss/latency and returns a deterministic diagnosis. Enable Tool Mode to give it to an Agent."
    )
    icon = "activity"
    name = "PingEndpoints"

    inputs = [
        MessageTextInput(
            name="gateway",
            display_name="Gateway IP (optional)",
            info="Leave empty to auto-detect the default gateway.",
            tool_mode=True,
            advanced=False,
        ),
    ]
    outputs = [Output(display_name="Ping + Diagnosis", name="result", method="run")]

    def run(self) -> Data:
        args = {"gateway": self.gateway} if self.gateway else {}
        result = build_default_registry().execute(
            "ping_endpoints", args, get_default_tracer(), "invoked from Langflow"
        )
        diag = result.get("diagnosis", {})
        self.status = diag.get("summary") or result.get("error", "")
        return Data(data=result)
