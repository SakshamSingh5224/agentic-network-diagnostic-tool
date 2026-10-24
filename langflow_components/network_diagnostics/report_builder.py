from langflow.custom import Component
from langflow.io import DataInput, Output
from langflow.schema.message import Message

from netdiag.report import render_report


class DiagnosticReportComponent(Component):
    display_name = "Plain-Text Network Report"
    description = (
        "Deterministic fallback reporter: turns ping/diagnosis Data (and optional traceroute Data) "
        "into a human-readable summary with remediation steps - no LLM required."
    )
    icon = "file-text"
    name = "NetworkReport"

    inputs = [
        DataInput(name="ping_data", display_name="Ping + Diagnosis", required=True),
        DataInput(name="trace_data", display_name="Traceroute (optional)", required=False),
    ]
    outputs = [Output(display_name="Report", name="report", method="build")]

    def build(self) -> Message:
        ping = getattr(self.ping_data, "data", self.ping_data) or {}
        trace = getattr(self.trace_data, "data", self.trace_data) if self.trace_data else None
        text = render_report(ping.get("diagnosis", {}), [trace] if trace else [])
        self.status = text.splitlines()[1] if text else ""
        return Message(text=text)
