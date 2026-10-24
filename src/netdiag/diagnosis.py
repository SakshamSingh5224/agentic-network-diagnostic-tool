"""Phase 2 - deterministic diagnostic engine (FR2).

Pure functions: PingResult objects in, Diagnosis out. No I/O, no LLM.
The agent treats this as the trusted baseline and only adds interpretation.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from netdiag.config import EXTERNAL_TARGETS, LABELS, Settings
from netdiag.models import Diagnosis, PingResult, ProbeState, Severity, Status


def classify_probe(p: Optional[PingResult], local: bool, s: Settings) -> ProbeState:
    if p is None or (p.received is None and p.loss_pct is None):
        return ProbeState.UNKNOWN  # ping could not run -> we know nothing
    if not p.reachable or (p.loss_pct is not None and p.loss_pct >= 100):
        return ProbeState.DOWN
    limit = s.latency_warn_ms_local if local else s.latency_warn_ms_external
    if (p.loss_pct or 0) >= s.loss_warn_pct or (p.rtt_avg_ms is not None and p.rtt_avg_ms >= limit):
        return ProbeState.DEGRADED
    return ProbeState.OK


def describe_probe(key: str, p: Optional[PingResult]) -> str:
    name = LABELS.get(key, key)
    if p is None:
        return f"{name}: not tested (gateway could not be detected)"
    if p.received is None and p.loss_pct is None:
        return f"{name} ({p.host}): could not be tested - {p.error or 'unknown error'}"
    if not p.reachable:
        return f"{name} ({p.host}): UNREACHABLE, 100% packet loss"
    avg = f"{p.rtt_avg_ms:.1f} ms avg" if p.rtt_avg_ms is not None else "latency n/a"
    return f"{name} ({p.host}): reachable, {p.loss_pct:g}% loss, {avg}"


def diagnose(pings: Dict[str, PingResult], settings: Optional[Settings] = None) -> Diagnosis:
    s = settings or Settings()
    gw = pings.get("gateway")
    ext_keys = [k for k in EXTERNAL_TARGETS if k in pings]

    states: Dict[str, ProbeState] = {"gateway": classify_probe(gw, True, s)}
    for k in ext_keys:
        states[k] = classify_probe(pings[k], False, s)

    findings: List[str] = [describe_probe("gateway", gw)] + [
        describe_probe(k, pings[k]) for k in ext_keys
    ]
    out = {k: v.value for k, v in states.items()}
    g = states["gateway"]
    ext = {k: states[k] for k in ext_keys}
    down = [k for k, v in ext.items() if v == ProbeState.DOWN]
    degraded = [k for k, v in ext.items() if v == ProbeState.DEGRADED]
    first_ext_host = pings[ext_keys[0]].host if ext_keys else EXTERNAL_TARGETS["google_dns"]

    def make(status, severity, summary, trace=None):
        return Diagnosis(
            status=status,
            severity=severity,
            summary=summary,
            findings=findings,
            needs_traceroute=bool(trace),
            trace_targets=trace or [],
            probe_states=out,
        )

    if all(v == ProbeState.UNKNOWN for k, v in states.items() if k != "gateway") or not ext_keys:
        return make(
            Status.INCONCLUSIVE,
            Severity.UNKNOWN,
            "Ping could not be run, so the network state is unknown.",
        )

    # 1) Local network: gateway down or unhealthy
    if g == ProbeState.DOWN:
        return make(
            Status.LOCAL_NETWORK_ISSUE,
            Severity.CRITICAL,
            "Your WiFi gateway/hotspot is not responding - the problem is on your local network.",
            [first_ext_host],
        )
    if g == ProbeState.DEGRADED:
        return make(
            Status.LOCAL_NETWORK_ISSUE,
            Severity.WARNING,
            "The link to your WiFi gateway is unhealthy (loss or high latency) - likely weak "
            "signal, interference or congestion on the local network.",
            [first_ext_host] if (down or degraded) else None,
        )

    # 2) Gateway status unknown: cannot separate local from ISP failures
    if g == ProbeState.UNKNOWN and len(down) == len(ext_keys):
        return make(
            Status.INCONCLUSIVE,
            Severity.WARNING,
            "Both public DNS servers are unreachable but the gateway could not be tested, so "
            "this could be a local or an ISP problem.",
            [first_ext_host],
        )

    # 3) Gateway fine -> look outward
    if len(down) == len(ext_keys):
        return make(
            Status.ISP_ISSUE,
            Severity.CRITICAL,
            "Your local network is fine but neither Google DNS nor Cloudflare DNS is reachable - "
            "this points to an ISP / upstream outage.",
            [pings[k].host for k in down],
        )
    if down:
        names = " and ".join(LABELS.get(k, k) for k in down)
        return make(
            Status.EXTERNAL_DNS_ISSUE,
            Severity.WARNING,
            f"{names} is unreachable while the other public DNS server works - the issue is "
            "specific to that endpoint or the route to it, not your whole connection.",
            [pings[k].host for k in down],
        )
    if degraded:
        names = ", ".join(LABELS.get(k, k) for k in degraded)
        return make(
            Status.DEGRADED_CONNECTION,
            Severity.WARNING,
            f"Internet connectivity works but is degraded (packet loss or high latency) to {names}.",
            [pings[k].host for k in degraded],
        )

    return make(Status.HEALTHY, Severity.OK, "All endpoints are reachable with healthy latency.")
