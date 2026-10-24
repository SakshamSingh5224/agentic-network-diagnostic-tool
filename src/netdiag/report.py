"""Plain-text reporting (FR6). Works on the dict form of results (see tools.py)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

REMEDIATION: Dict[str, List[str]] = {
    "healthy": ["No action needed. If an app still misbehaves, the problem is likely with that app or service."],
    "local_network_issue": [
        "Move closer to the router/hotspot and check that WiFi is actually connected.",
        "Toggle WiFi off and on, or forget and rejoin the network.",
        "Restart the router (or the phone hotspot) and wait ~60 seconds.",
        "Try a wired (Ethernet) connection or another device to see whether it is just this machine.",
        "If you use a phone hotspot, check that mobile data is enabled and has signal.",
    ],
    "isp_issue": [
        "Reboot the modem/ONT and router (unplug 30 seconds), then retest.",
        "Check your ISP's status page or app for outages in your area.",
        "Try another network (e.g. a phone hotspot) to confirm the fault is with your ISP.",
        "If it persists, contact your ISP and quote the traceroute result shown in this report.",
    ],
    "external_dns_issue": [
        "Your internet works - switch your DNS resolver to the one that is still reachable "
        "(8.8.8.8 or 1.1.1.1) or to your ISP's DNS.",
        "Retest later; the issue is specific to one provider or the route to it.",
    ],
    "degraded_connection": [
        "Pause large downloads/uploads and streaming on the network and retest.",
        "Check for WiFi interference (move closer, switch 2.4 GHz <-> 5 GHz, change channel).",
        "If wired and still slow, restart the modem/router; if it persists, contact your ISP.",
    ],
    "inconclusive": [
        "Make sure `ping` is installed and allowed to run, and that you are connected to a network.",
        "Re-run with --gateway <router-ip> if gateway auto-detection failed.",
    ],
}

TITLES = {
    "healthy": "HEALTHY",
    "local_network_issue": "LOCAL NETWORK ISSUE",
    "isp_issue": "ISP / UPSTREAM ISSUE",
    "external_dns_issue": "EXTERNAL DNS ENDPOINT ISSUE",
    "degraded_connection": "DEGRADED CONNECTION",
    "inconclusive": "INCONCLUSIVE",
}


def render_report(
    diagnosis: Dict[str, Any],
    traces: Optional[List[Dict[str, Any]]] = None,
    narrative: Optional[str] = None,
) -> str:
    """Build the user-facing summary. `narrative` (from an LLM) replaces the deterministic
    explanation but the measured facts are always printed, so they can be verified."""
    status = diagnosis.get("status", "inconclusive")
    lines = [
        "=" * 60,
        f"NETWORK DIAGNOSIS: {TITLES.get(status, status).upper()}",
        "=" * 60,
        "",
        narrative.strip() if narrative else diagnosis.get("summary", ""),
        "",
        "What was measured:",
    ]
    lines += [f"  - {f}" for f in diagnosis.get("findings", [])]

    for t in traces or []:
        lines += ["", f"Traceroute to {t.get('host')}:"]
        if t.get("error"):
            lines.append(f"  - could not run: {t['error']}")
            continue
        lines += [f"  - {f}" for f in t.get("analysis", {}).get("findings", [])]

    if not narrative:
        lines += ["", "Recommended steps:"]
        lines += [f"  {i}. {s}" for i, s in enumerate(REMEDIATION.get(status, []), 1)]
    return "\n".join(lines)
