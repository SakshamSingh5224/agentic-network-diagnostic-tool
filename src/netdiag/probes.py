"""Phase 1 - multi-endpoint ping execution and output parsing (FR1, FR2)."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Optional

from netdiag.config import EXTERNAL_TARGETS, LABELS, Settings
from netdiag.models import CommandResult, PingResult
from netdiag.platform_utils import is_valid_host, ping_command, run_command

Runner = Callable[[list, float], CommandResult]

_COUNTS_UNIX = re.compile(r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received")
_COUNTS_WIN = re.compile(r"Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+)")
_RTT_UNIX = re.compile(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)")  # min/avg/max[/mdev]
_RTT_WIN = re.compile(r"Minimum\s*=\s*(\d+)ms,\s*Maximum\s*=\s*(\d+)ms,\s*Average\s*=\s*(\d+)ms")
_TIME = re.compile(r"time\s*[=<]\s*([\d.]+)\s*ms", re.I)


def parse_ping_output(text: str, expected_count: Optional[int] = None) -> Dict[str, object]:
    """Extract sent / received / loss / rtt from Linux, macOS or Windows ping output.

    Falls back to per-reply "time=" lines when the summary is missing (e.g. the
    process was killed on timeout). Returns {} if nothing usable was found.
    """
    out: Dict[str, object] = {}
    times = [float(t) for t in _TIME.findall(text)]

    m = _COUNTS_UNIX.search(text) or _COUNTS_WIN.search(text)
    if m:
        sent, received = int(m.group(1)), int(m.group(2))
        # Windows counts "Destination host unreachable" replies from the local stack
        # as received; genuine replies always carry a time value.
        lowered = text.lower()
        if ("unreachable" in lowered or "ttl expired" in lowered) and len(times) < received:
            received = len(times)
    elif text.strip():
        sent, received = expected_count or max(len(times), 1), len(times)
    else:
        return {}

    out["sent"], out["received"] = sent, received
    out["loss_pct"] = round(100.0 * (sent - received) / sent, 1) if sent else 100.0

    if received:
        mu, mw = _RTT_UNIX.search(text), _RTT_WIN.search(text)
        if mu:
            out["rtt_min_ms"], out["rtt_avg_ms"], out["rtt_max_ms"] = (
                float(mu.group(1)), float(mu.group(2)), float(mu.group(3)))
        elif mw:
            out["rtt_min_ms"], out["rtt_max_ms"], out["rtt_avg_ms"] = (
                float(mw.group(1)), float(mw.group(2)), float(mw.group(3)))
        elif times:
            out["rtt_min_ms"], out["rtt_max_ms"] = min(times), max(times)
            out["rtt_avg_ms"] = round(sum(times) / len(times), 3)
    return out


def ping_host(
    host: str,
    label: str = "",
    settings: Optional[Settings] = None,
    runner: Runner = run_command,
) -> PingResult:
    """Ping one host. Never raises; failures are reported inside the result."""
    s = settings or Settings()
    result = PingResult(host=host, label=label or host)
    if not is_valid_host(host):
        result.error = f"invalid host: {host!r}"
        return result

    t0 = time.perf_counter()
    try:
        res = runner(ping_command(host, s), s.probe_deadline_s + 0.5)
        result.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        result.raw_output = res.output[:2000]
        parsed = parse_ping_output(res.output, s.ping_count)

        if parsed:
            for key, value in parsed.items():
                setattr(result, key, value)
            result.reachable = bool(result.received)
            if not result.reachable and res.stderr.strip():
                result.error = res.stderr.strip().splitlines()[0][:200]
        elif res.returncode is not None:  # ran, but printed no stats (e.g. "Network is unreachable")
            result.sent, result.received, result.loss_pct = s.ping_count, 0, 100.0
            result.error = (res.output.strip().splitlines() or ["no reply"])[0][:200]
        else:  # could not run / hung with no output -> unknown, not "down"
            result.error = res.error or "no output from ping"
    except Exception as exc:  # noqa: BLE001 - NFR2: the orchestration loop must survive
        result.error = f"unexpected error: {exc}"
    return result


def ping_all(
    gateway: Optional[str],
    settings: Optional[Settings] = None,
    runner: Runner = run_command,
) -> Dict[str, PingResult]:
    """Ping gateway + Google DNS + Cloudflare DNS concurrently (FR1, NFR1)."""
    s = settings or Settings()
    targets: Dict[str, str] = {}
    if gateway:
        targets["gateway"] = gateway
    targets.update(EXTERNAL_TARGETS)

    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = {
            key: pool.submit(ping_host, host, LABELS.get(key, key), s, runner)
            for key, host in targets.items()
        }
        return {key: fut.result() for key, fut in futures.items()}
