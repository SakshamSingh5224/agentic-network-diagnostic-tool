from netdiag.config import Settings
from netdiag.models import CommandResult
from netdiag.platform_utils import is_valid_host, os_family, ping_command, traceroute_command
from netdiag.probes import parse_ping_output, ping_all, ping_host

LINUX_OK = """PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=9.10 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=10.2 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=117 time=11.3 ms

--- 8.8.8.8 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 402ms
rtt min/avg/max/mdev = 9.100/10.200/11.300/0.900 ms
"""
LINUX_DOWN = """PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.

--- 8.8.8.8 ping statistics ---
3 packets transmitted, 0 received, 100% packet loss, time 2043ms
"""
LINUX_PARTIAL = """3 packets transmitted, 2 received, 33.3% packet loss, time 2003ms
rtt min/avg/max/mdev = 20.0/25.0/30.0/5.0 ms
"""
MAC_OK = """PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=58 time=12.5 ms
--- 1.1.1.1 ping statistics ---
3 packets transmitted, 3 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 12.0/13.5/15.0/1.2 ms
"""
WIN_OK = """Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=14ms TTL=117
Reply from 8.8.8.8: bytes=32 time<1ms TTL=117
Reply from 8.8.8.8: bytes=32 time=16ms TTL=117

Ping statistics for 8.8.8.8:
    Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 1ms, Maximum = 16ms, Average = 10ms
"""
WIN_UNREACHABLE = """Pinging 192.168.1.1 with 32 bytes of data:
Reply from 192.168.1.50: Destination host unreachable.
Reply from 192.168.1.50: Destination host unreachable.
Reply from 192.168.1.50: Destination host unreachable.

Ping statistics for 192.168.1.1:
    Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),
"""


def test_linux_ok():
    r = parse_ping_output(LINUX_OK)
    assert (r["sent"], r["received"], r["loss_pct"]) == (3, 3, 0.0)
    assert (r["rtt_min_ms"], r["rtt_avg_ms"], r["rtt_max_ms"]) == (9.1, 10.2, 11.3)


def test_linux_down():
    r = parse_ping_output(LINUX_DOWN)
    assert r["received"] == 0 and r["loss_pct"] == 100.0 and "rtt_avg_ms" not in r


def test_linux_partial_loss():
    assert parse_ping_output(LINUX_PARTIAL)["loss_pct"] == 33.3


def test_macos():
    r = parse_ping_output(MAC_OK)
    assert r["rtt_avg_ms"] == 13.5 and r["loss_pct"] == 0.0


def test_windows_ok():
    r = parse_ping_output(WIN_OK)
    assert (r["rtt_min_ms"], r["rtt_max_ms"], r["rtt_avg_ms"]) == (1.0, 16.0, 10.0)


def test_windows_unreachable_counts_as_loss():
    r = parse_ping_output(WIN_UNREACHABLE)
    assert r["received"] == 0 and r["loss_pct"] == 100.0


def test_summary_missing_falls_back_to_reply_lines():
    text = "64 bytes from 8.8.8.8: icmp_seq=1 ttl=1 time=10 ms\n64 bytes from 8.8.8.8: icmp_seq=2 ttl=1 time=20 ms\n"
    r = parse_ping_output(text, expected_count=3)
    assert r["received"] == 2 and r["loss_pct"] == 33.3 and r["rtt_avg_ms"] == 15.0


def test_empty_output():
    assert parse_ping_output("") == {}


# ---- ping_host: resilience (NFR2) -------------------------------------
def fake(stdout="", returncode=0, stderr="", error=None, timed_out=False):
    return lambda cmd, timeout: CommandResult(cmd, returncode, stdout, stderr, timed_out, error)


def test_ping_host_success():
    r = ping_host("8.8.8.8", "g", runner=fake(LINUX_OK))
    assert r.reachable and r.rtt_avg_ms == 10.2 and r.error is None


def test_ping_host_100_percent_loss():
    r = ping_host("8.8.8.8", runner=fake(LINUX_DOWN, returncode=1))
    assert not r.reachable and r.loss_pct == 100.0


def test_ping_host_network_unreachable_is_down_not_unknown():
    r = ping_host("8.8.8.8", runner=fake("", 2, "connect: Network is unreachable"))
    assert r.loss_pct == 100.0 and "unreachable" in r.error


def test_ping_host_command_missing_is_unknown():
    r = ping_host("8.8.8.8", runner=fake(returncode=None, error="command not found: ping"))
    assert r.loss_pct is None and r.received is None and "not found" in r.error


def test_ping_host_runner_crash_does_not_raise():
    def boom(cmd, timeout):
        raise RuntimeError("kaboom")
    r = ping_host("8.8.8.8", runner=boom)
    assert "kaboom" in r.error


def test_ping_host_timeout_with_partial_output():
    r = ping_host("8.8.8.8", runner=fake("time=10 ms\n", None, timed_out=True, error="timed out"))
    assert r.reachable and r.received == 1


def test_ping_host_rejects_option_injection():
    assert ping_host("-f", runner=fake(LINUX_OK)).error.startswith("invalid host")


def test_ping_all_runs_every_target_and_survives_failures():
    res = ping_all("192.168.1.1", runner=fake(error="x", returncode=None))
    assert set(res) == {"gateway", "google_dns", "cloudflare_dns"}


def test_ping_all_without_gateway():
    assert "gateway" not in ping_all(None, runner=fake(LINUX_OK))


# ---- platform abstraction (NFR5) --------------------------------------
def test_os_family():
    assert (os_family("Windows"), os_family("Darwin"), os_family("Linux")) == ("windows", "macos", "linux")


def test_ping_commands_per_os():
    s = Settings()
    assert ping_command("1.1.1.1", s, "windows")[:3] == ["ping", "-n", "3"]
    assert "-t" in ping_command("1.1.1.1", s, "macos")
    assert "-w" in ping_command("1.1.1.1", s, "linux")


def test_traceroute_commands_per_os():
    s = Settings()
    assert traceroute_command("1.1.1.1", s, "windows")[0] == "tracert"
    assert traceroute_command("1.1.1.1", s, "linux")[0] == "traceroute"


def test_is_valid_host():
    assert is_valid_host("8.8.8.8") and is_valid_host("dns.google")
    assert not is_valid_host("-f") and not is_valid_host("a;b") and not is_valid_host("")
