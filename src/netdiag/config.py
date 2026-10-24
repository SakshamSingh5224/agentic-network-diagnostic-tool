"""Central settings. All thresholds live here so behaviour is tunable in one place."""

from __future__ import annotations

from dataclasses import dataclass

# Fixed external endpoints from the MVP spec (FR1).
EXTERNAL_TARGETS = {
    "google_dns": "8.8.8.8",
    "cloudflare_dns": "1.1.1.1",
}

LABELS = {
    "gateway": "WiFi gateway",
    "google_dns": "Google DNS",
    "cloudflare_dns": "Cloudflare DNS",
}


@dataclass(frozen=True)
class Settings:
    # --- Ping (NFR1: whole ping phase must finish in < 5 s) ---
    ping_count: int = 3
    ping_reply_timeout_s: float = 1.0  # wait per reply
    probe_deadline_s: float = 4.0  # hard stop passed to ping itself
    # --- Diagnosis thresholds ---
    loss_warn_pct: float = 10.0
    latency_warn_ms_local: float = 50.0
    latency_warn_ms_external: float = 150.0
    # --- Traceroute ---
    traceroute_max_hops: int = 20
    traceroute_hop_wait_s: float = 1.0
    traceroute_timeout_s: float = 30.0
    latency_jump_ms: float = 50.0  # flag a hop-to-hop RTT increase this large
    # --- Agent ---
    max_traces: int = 1
    max_agent_steps: int = 8
    trace_log_path: str = "logs/agent_trace.jsonl"
