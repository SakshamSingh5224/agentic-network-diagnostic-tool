from netdiag.models import PingResult


def ping(host="x", sent=3, received=3, loss=0.0, avg=10.0, label=""):
    reachable = received > 0
    return PingResult(
        host=host, label=label or host, reachable=reachable, sent=sent, received=received,
        loss_pct=loss, rtt_avg_ms=avg if reachable else None,
        rtt_min_ms=avg if reachable else None, rtt_max_ms=avg if reachable else None,
    )


def healthy(host):
    return ping(host)


def down(host):
    return ping(host, received=0, loss=100.0)
