from netdiag.config import Settings
from netdiag.models import CommandResult
from netdiag.traceroute import analyze_hops, parse_traceroute, run_traceroute

LINUX_OK = """traceroute to 8.8.8.8 (8.8.8.8), 20 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms
 2  100.64.0.1  8.5 ms
 3  72.14.1.1  12.0 ms
 4  8.8.8.8  14.2 ms
"""
LINUX_STALL = """traceroute to 8.8.8.8 (8.8.8.8), 20 hops max, 60 byte packets
 1  192.168.1.1  1.2 ms
 2  100.64.0.1  9.0 ms
 3  * 
 4  * 
 5  * 
"""
DIES_AT_GATEWAY = """traceroute to 1.1.1.1 (1.1.1.1), 20 hops max
 1  192.168.1.1  1.0 ms
 2  *
 3  *
"""
NOTHING = """traceroute to 1.1.1.1 (1.1.1.1), 20 hops max
 1  *
 2  *
"""
JUMP = """traceroute to 8.8.8.8 (8.8.8.8), 20 hops max
 1  192.168.1.1  1 ms
 2  10.1.1.1  5 ms
 3  72.14.1.1  180 ms
 4  8.8.8.8  182 ms
"""
WINDOWS = """Tracing route to dns.google [8.8.8.8]
over a maximum of 20 hops:

  1    <1 ms    <1 ms    <1 ms  192.168.1.1
  2     *        *        *     Request timed out.
  3    12 ms    11 ms    13 ms  8.8.8.8

Trace complete.
"""


def test_parse_linux():
    hops = parse_traceroute(LINUX_OK)
    assert [h.address for h in hops] == ["192.168.1.1", "100.64.0.1", "72.14.1.1", "8.8.8.8"]
    assert hops[0].rtt_ms == [1.234]


def test_parse_timeouts():
    hops = parse_traceroute(LINUX_STALL)
    assert [h.timed_out for h in hops] == [False, False, True, True, True]


def test_parse_windows():
    hops = parse_traceroute(WINDOWS)
    assert len(hops) == 3 and hops[0].rtt_ms == [0.5, 0.5, 0.5]
    assert hops[1].timed_out and hops[2].address == "8.8.8.8"


def test_parse_hop_flag():
    assert parse_traceroute(" 2  192.168.1.1  3.0 ms !H")[0].flag == "!H"


def a(text, target="8.8.8.8", dest=None):
    return analyze_hops(parse_traceroute(text), target, dest)


def test_reached():
    r = a(LINUX_OK)
    assert r["reached"] and r["total_hops"] == 4


def test_stall_after_cgnat_hop():
    r = a(LINUX_STALL)
    assert not r["reached"] and r["last_responding_hop"] == 2 and r["trailing_timeouts"] == 3
    assert any("carrier-grade" in f for f in r["findings"])


def test_dies_after_gateway():
    r = a(DIES_AT_GATEWAY, "1.1.1.1")
    assert r["last_responding_hop"] == 1 and any("gateway" in f for f in r["findings"])


def test_no_hop_responds():
    r = a(NOTHING, "1.1.1.1")
    assert r["last_responding_hop"] is None and any("No hop responded" in f for f in r["findings"])


def test_latency_jump_detected():
    r = a(JUMP)
    assert r["largest_latency_jump"] == {"from_hop": 2, "to_hop": 3, "delta_ms": 175.0}


def test_empty():
    assert not analyze_hops([], "8.8.8.8", None)["reached"]


def fake(stdout="", rc=0, error=None, timed_out=False):
    return lambda cmd, timeout: CommandResult(cmd, rc, stdout, "", timed_out, error)


def test_run_traceroute_ok_with_hostname_header():
    r = run_traceroute("dns.google", runner=fake(WINDOWS))
    assert r.destination_ip == "8.8.8.8" and r.reached


def test_run_traceroute_missing_binary_gives_hint():
    r = run_traceroute("8.8.8.8", runner=fake(rc=None, error="command not found: traceroute"))
    assert "apt install" in r.error


def test_run_traceroute_timeout_marks_partial():
    r = run_traceroute("8.8.8.8", Settings(), runner=fake(LINUX_STALL, None, "timed out", True))
    assert r.truncated and any("cut off" in f for f in r.analysis["findings"])


def test_run_traceroute_invalid_host_and_crash():
    assert "invalid host" in run_traceroute("-x", runner=fake()).error

    def boom(cmd, t):
        raise RuntimeError("bad")
    assert "bad" in run_traceroute("8.8.8.8", runner=boom).error
