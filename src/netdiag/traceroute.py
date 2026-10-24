"""Traceroute execution, parsing and deterministic hop analysis (FR3)."""

from __future__ import annotations

import ipaddress
import re
import time
from typing import Any, Callable, Dict, List, Optional

from netdiag.config import Settings
from netdiag.models import CommandResult, Hop, TracerouteResult
from netdiag.platform_utils import is_valid_host, run_command, traceroute_command

Runner = Callable[[list, float], CommandResult]

_HOP_LINE = re.compile(r"^\s*(\d+)\s+(.*)$")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_RTT = re.compile(r"(<?\d+(?:\.\d+)?)\s*ms")
_FLAG = re.compile(r"(![A-Z0-9]?)")
_DEST = re.compile(r"(?:traceroute to \S+ \(([^)]+)\)|Tracing route to .*?\[([^\]]+)\])")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def parse_traceroute(text: str) -> List[Hop]:
    hops: List[Hop] = []
    for line in text.splitlines():
        m = _HOP_LINE.match(line)
        if not m:
            continue
        index, rest = int(m.group(1)), m.group(2)
        rtts = [0.5 if r.startswith("<") else float(r) for r in _RTT.findall(rest)]
        ips = _IPV4.findall(rest)
        flag = _FLAG.search(rest)
        hops.append(
            Hop(
                index=index,
                address=ips[0] if ips else None,
                rtt_ms=rtts,
                timed_out=not ips and not rtts,
                flag=flag.group(1) if flag else None,
            )
        )
    return hops


def _classify_address(addr: str) -> str:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return "unknown"
    if ip in _CGNAT:
        return "carrier-grade NAT (ISP-internal)"
    if ip.is_private:
        return "private (your local network / ISP-internal)"
    return "public (ISP or transit network)"


def analyze_hops(
    hops: List[Hop], target: str, destination_ip: Optional[str], settings: Optional[Settings] = None
) -> Dict[str, Any]:
    """Deterministic interpretation of a hop list: where does the path stop, where does latency jump."""
    s = settings or Settings()
    findings: List[str] = []
    if not hops:
        return {"reached": False, "total_hops": 0, "findings": ["Traceroute produced no hops."]}

    dest = destination_ip or (target if _IPV4.fullmatch(target) else None)
    responding = [h for h in hops if h.address]
    last_resp = responding[-1] if responding else None
    reached = bool(last_resp and dest and last_resp.address == dest and hops[-1] is last_resp)

    trailing = 0
    for h in reversed(hops):
        if h.timed_out:
            trailing += 1
        else:
            break

    jump = None
    prev: Optional[Hop] = None
    for h in hops:
        if h.best_rtt is None:
            continue
        if prev is not None and h.best_rtt - prev.best_rtt >= s.latency_jump_ms:
            delta = round(h.best_rtt - prev.best_rtt, 1)
            if jump is None or delta > jump["delta_ms"]:
                jump = {"from_hop": prev.index, "to_hop": h.index, "delta_ms": delta}
        prev = h

    flagged = next((h for h in hops if h.flag in ("!H", "!N", "!X", "!P")), None)

    if reached:
        findings.append(f"Destination {target} was reached in {hops[-1].index} hops.")
    elif last_resp is None:
        findings.append(
            "No hop responded at all - traffic is being dropped before the first router "
            "(local link down, or this host blocks traceroute probes)."
        )
    elif last_resp.index == 1:
        findings.append(
            f"The path dies right after hop 1 ({last_resp.address}, your gateway): the router is "
            "reachable but nothing beyond it - suspect the modem/ONT, WAN link or ISP."
        )
    else:
        kind = _classify_address(last_resp.address)
        findings.append(
            f"The path stops responding after hop {last_resp.index} ({last_resp.address}, {kind}); "
            f"{trailing} trailing hop(s) timed out."
        )
        findings.append(
            "Caveat: some routers silently ignore traceroute probes, so trailing timeouts alone "
            "are only meaningful if pings to the destination also fail."
        )
    if flagged:
        findings.append(f"Hop {flagged.index} ({flagged.address}) reported {flagged.flag} (unreachable).")
    if jump:
        findings.append(
            f"Largest latency increase: +{jump['delta_ms']} ms between hop {jump['from_hop']} and "
            f"hop {jump['to_hop']} - congestion or a long-haul link is likely there."
        )

    return {
        "reached": reached,
        "total_hops": hops[-1].index,
        "first_hop": hops[0].address,
        "last_responding_hop": last_resp.index if last_resp else None,
        "last_responding_address": last_resp.address if last_resp else None,
        "trailing_timeouts": trailing,
        "largest_latency_jump": jump,
        "findings": findings,
    }


def run_traceroute(
    host: str, settings: Optional[Settings] = None, runner: Runner = run_command
) -> TracerouteResult:
    """Run + parse + analyse a traceroute. Never raises (NFR2)."""
    s = settings or Settings()
    result = TracerouteResult(host=host)
    if not is_valid_host(host):
        result.error = f"invalid host: {host!r}"
        return result

    t0 = time.perf_counter()
    try:
        res = runner(traceroute_command(host, s), s.traceroute_timeout_s)
        result.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        result.raw_output = res.output[:4000]
        result.truncated = res.timed_out
        if res.error and not res.stdout.strip():
            hint = " (install it, e.g. `sudo apt install traceroute`)" if "not found" in res.error else ""
            result.error = res.error + hint
            return result
        m = _DEST.search(res.output)
        result.destination_ip = (m.group(1) or m.group(2)) if m else None
        result.hops = parse_traceroute(res.stdout)
        result.analysis = analyze_hops(result.hops, host, result.destination_ip, s)
        result.reached = bool(result.analysis.get("reached"))
        if res.timed_out:
            result.analysis.setdefault("findings", []).append(
                f"Traceroute was cut off after {s.traceroute_timeout_s:.0f}s; results are partial."
            )
    except Exception as exc:  # noqa: BLE001
        result.error = f"unexpected error: {exc}"
    return result
