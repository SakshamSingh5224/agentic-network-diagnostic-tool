from netdiag.platform_utils import parse_gateway_linux, parse_gateway_macos, parse_gateway_windows


def test_linux_ip_route():
    assert parse_gateway_linux("default via 192.168.1.1 dev wlan0 proto dhcp metric 600") == "192.168.1.1"


def test_linux_route_n():
    assert parse_gateway_linux("0.0.0.0         10.0.0.1        0.0.0.0         UG    0 0 0 eth0") == "10.0.0.1"


def test_macos():
    assert parse_gateway_macos("   route to: default\n    gateway: 172.20.10.1\n  interface: en0") == "172.20.10.1"


def test_windows_picks_lowest_metric_and_skips_on_link():
    text = """
          0.0.0.0          0.0.0.0     192.168.0.1    192.168.0.20     45
          0.0.0.0          0.0.0.0     10.0.0.1       10.0.0.5         25
          0.0.0.0          0.0.0.0     On-link        10.0.0.9         5
"""
    assert parse_gateway_windows(text) == "10.0.0.1"


def test_no_gateway():
    assert parse_gateway_linux("") is None and parse_gateway_windows("") is None
