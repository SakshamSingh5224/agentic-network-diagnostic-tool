"""OS abstraction (NFR5): command building, safe execution and gateway discovery.

Everything that differs between Windows / macOS / Linux lives in this file.
Parsers are pure functions so they can be unit-tested with captured output.
"""

from __future__ import annotations

import ipaddress
import math
import platform
import re
import subprocess
from typing import List, Optional

from netdiag.config import Settings
from netdiag.models import CommandResult

_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-:]{0,251}[A-Za-z0-9])?$")


def is_valid_host(host: object) -> bool:
    """Accept hostnames / IPs only. Blocks option injection such as '-f' or 'a;b'."""
    return isinstance(host, str) and bool(_HOST_RE.match(host))


def os_family(system: Optional[str] = None) -> str:
    s = (system or platform.system()).lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    return "linux"


# ----------------------------------------------------------------- commands
def ping_command(host: str, settings: Settings, family: Optional[str] = None) -> List[str]:
    fam = family or os_family()
    count = str(settings.ping_count)
    wait_ms = str(int(settings.ping_reply_timeout_s * 1000))
    deadline = str(int(math.ceil(settings.probe_deadline_s)))
    if fam == "windows":
        return ["ping", "-n", count, "-w", wait_ms, host]
    if fam == "macos":
        return ["ping", "-c", count, "-W", wait_ms, "-t", deadline, host]
    wait_s = str(max(1, int(math.ceil(settings.ping_reply_timeout_s))))
    return ["ping", "-c", count, "-i", "0.2", "-W", wait_s, "-w", deadline, host]


def traceroute_command(host: str, settings: Settings, family: Optional[str] = None) -> List[str]:
    fam = family or os_family()
    hops = str(settings.traceroute_max_hops)
    if fam == "windows":
        wait_ms = str(int(settings.traceroute_hop_wait_s * 1000))
        return ["tracert", "-d", "-h", hops, "-w", wait_ms, host]
    wait_s = str(max(1, int(math.ceil(settings.traceroute_hop_wait_s))))
    return ["traceroute", "-n", "-m", hops, "-w", wait_s, "-q", "1", host]


# ---------------------------------------------------------------- execution
def _to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_command(cmd: List[str], timeout: float) -> CommandResult:
    """Run a command without a shell. Never raises (NFR2)."""
    try:
        cp = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=timeout, shell=False
        )
        return CommandResult(cmd, cp.returncode, cp.stdout or "", cp.stderr or "")
    except FileNotFoundError:
        return CommandResult(cmd, None, error=f"command not found: {cmd[0]}")
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            cmd,
            None,
            _to_text(exc.stdout),
            _to_text(exc.stderr),
            timed_out=True,
            error=f"timed out after {timeout:.1f}s",
        )
    except OSError as exc:
        return CommandResult(cmd, None, error=f"could not run {cmd[0]}: {exc}")


# ------------------------------------------------------------------ gateway
def _valid_ip(text: Optional[str]) -> Optional[str]:
    try:
        return str(ipaddress.ip_address((text or "").strip().split("%")[0]))
    except ValueError:
        return None


def parse_gateway_linux(text: str) -> Optional[str]:
    m = re.search(r"default via (\S+)", text)  # `ip route`
    if m:
        return _valid_ip(m.group(1))
    m = re.search(r"^0\.0\.0\.0\s+(\S+)", text, re.M)  # `route -n`
    return _valid_ip(m.group(1)) if m else None


def parse_gateway_macos(text: str) -> Optional[str]:
    m = re.search(r"gateway:\s*(\S+)", text)  # `route -n get default`
    return _valid_ip(m.group(1)) if m else None


def parse_gateway_windows(text: str) -> Optional[str]:
    best = None  # (metric, ip) - lowest metric wins
    for m in re.finditer(
        r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\S+)\s+\S+\s+(\d+)", text, re.M
    ):
        ip = _valid_ip(m.group(1))  # skips "On-link"
        if ip and (best is None or int(m.group(2)) < best[0]):
            best = (int(m.group(2)), ip)
    return best[1] if best else None


def detect_default_gateway(family: Optional[str] = None) -> Optional[str]:
    fam = family or os_family()
    if fam == "windows":
        attempts = [(["route", "print", "-4", "0.0.0.0"], parse_gateway_windows)]
    elif fam == "macos":
        attempts = [(["route", "-n", "get", "default"], parse_gateway_macos)]
    else:
        attempts = [
            (["ip", "-4", "route", "show", "default"], parse_gateway_linux),
            (["route", "-n"], parse_gateway_linux),
        ]
    for cmd, parser in attempts:
        res = run_command(cmd, timeout=3)
        if not res.error:
            gw = parser(res.stdout)
            if gw:
                return gw
    return None
