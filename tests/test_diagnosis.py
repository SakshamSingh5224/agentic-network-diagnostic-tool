import pytest

from conftest import down, healthy, ping
from netdiag.diagnosis import diagnose
from netdiag.models import PingResult, Severity, Status

GW, G, C = "192.168.1.1", "8.8.8.8", "1.1.1.1"


def run(gw, g, c):
    p = {"google_dns": g, "cloudflare_dns": c}
    if gw is not None:
        p["gateway"] = gw
    return diagnose(p)


def test_healthy():
    d = run(healthy(GW), healthy(G), healthy(C))
    assert d.status == Status.HEALTHY and not d.needs_traceroute and d.severity == Severity.OK


def test_gateway_down_is_local_issue():
    d = run(down(GW), down(G), down(C))
    assert d.status == Status.LOCAL_NETWORK_ISSUE and d.severity == Severity.CRITICAL
    assert d.needs_traceroute and d.trace_targets == [G]


def test_gateway_high_latency_is_local_warning():
    d = run(ping(GW, avg=120), healthy(G), healthy(C))
    assert d.status == Status.LOCAL_NETWORK_ISSUE and d.severity == Severity.WARNING
    assert not d.needs_traceroute


def test_gateway_ok_both_external_down_is_isp():
    d = run(healthy(GW), down(G), down(C))
    assert d.status == Status.ISP_ISSUE and d.trace_targets == [G, C]


def test_one_external_down_is_external_dns_issue():
    d = run(healthy(GW), healthy(G), down(C))
    assert d.status == Status.EXTERNAL_DNS_ISSUE and d.trace_targets == [C]
    assert "Cloudflare" in d.summary


def test_high_latency_is_degraded():
    d = run(healthy(GW), ping(G, avg=400), healthy(C))
    assert d.status == Status.DEGRADED_CONNECTION and d.trace_targets == [G]


def test_packet_loss_is_degraded():
    d = run(healthy(GW), ping(G, received=2, loss=33.3), healthy(C))
    assert d.status == Status.DEGRADED_CONNECTION


def test_unknown_gateway_and_externals_down_is_inconclusive_but_traces():
    d = run(None, down(G), down(C))
    assert d.status == Status.INCONCLUSIVE and d.needs_traceroute


def test_unknown_gateway_externals_ok_is_healthy():
    assert run(None, healthy(G), healthy(C)).status == Status.HEALTHY


def test_ping_tool_missing_is_inconclusive_not_isp():
    broken = PingResult(host="x", error="command not found: ping")
    d = run(broken, broken, broken)
    assert d.status == Status.INCONCLUSIVE and not d.needs_traceroute


def test_findings_list_every_probe():
    d = run(healthy(GW), healthy(G), down(C))
    assert len(d.findings) == 3 and any("UNREACHABLE" in f for f in d.findings)


@pytest.mark.parametrize("status", list(Status))
def test_status_values_are_json_friendly(status):
    assert isinstance(status.value, str)
