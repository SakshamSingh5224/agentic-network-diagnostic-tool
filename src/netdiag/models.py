"""Plain data containers shared by every layer (CLI, agent, Langflow components)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import Any, Dict, List, Optional


def to_jsonable(obj: Any) -> Any:
    """Round-trip through JSON so Enums etc. become plain values."""
    return json.loads(json.dumps(obj, default=str))


class Status(str, Enum):
    HEALTHY = "healthy"
    LOCAL_NETWORK_ISSUE = "local_network_issue"
    ISP_ISSUE = "isp_issue"
    EXTERNAL_DNS_ISSUE = "external_dns_issue"
    DEGRADED_CONNECTION = "degraded_connection"
    INCONCLUSIVE = "inconclusive"


class ProbeState(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class CommandResult:
    command: List[str]
    returncode: Optional[int]
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: Optional[str] = None  # set when the command could not run at all

    @property
    def output(self) -> str:
        return (self.stdout or "") + ("\n" + self.stderr if self.stderr else "")


@dataclass
class PingResult:
    host: str
    label: str = ""
    reachable: bool = False
    sent: Optional[int] = None
    received: Optional[int] = None
    loss_pct: Optional[float] = None
    rtt_min_ms: Optional[float] = None
    rtt_avg_ms: Optional[float] = None
    rtt_max_ms: Optional[float] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    raw_output: str = field(default="", repr=False)

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        d = asdict(self)
        if not include_raw:
            d.pop("raw_output", None)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PingResult:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Hop:
    index: int
    address: Optional[str] = None
    rtt_ms: List[float] = field(default_factory=list)
    timed_out: bool = False
    flag: Optional[str] = None  # e.g. "!H" (host unreachable) from traceroute

    @property
    def best_rtt(self) -> Optional[float]:
        return min(self.rtt_ms) if self.rtt_ms else None


@dataclass
class TracerouteResult:
    host: str
    destination_ip: Optional[str] = None
    hops: List[Hop] = field(default_factory=list)
    reached: bool = False
    truncated: bool = False  # command hit our time limit; output is partial
    error: Optional[str] = None
    duration_ms: float = 0.0
    analysis: Dict[str, Any] = field(default_factory=dict)
    raw_output: str = field(default="", repr=False)

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        d = asdict(self)
        if not include_raw:
            d.pop("raw_output", None)
        return to_jsonable(d)


@dataclass
class Diagnosis:
    status: Status
    severity: Severity
    summary: str
    findings: List[str] = field(default_factory=list)
    needs_traceroute: bool = False
    trace_targets: List[str] = field(default_factory=list)
    probe_states: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return to_jsonable(asdict(self))
