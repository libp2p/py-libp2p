from prometheus_client import Counter, Histogram

from libp2p.host.ping import PingEvent


class PingMetrics:
    rtt: Histogram
    failures: Counter

    def __init__(self) -> None:
        rtt = Histogram(
            "ping",
            "Round-trip time for ping/pong in milliseconds",
            buckets=[1, 5, 10, 25, 50, 100, 200, 500, 1000],  # ms, like go-libp2p
        )

        failures = Counter(
            "ping_failure",
            "Failure while sending a ping or receiving a ping",
            labelnames=["reason"],
        )

        self.rtt = rtt
        self.failures = failures

    def record(self, event: PingEvent) -> None:
        match event:
            case PingEvent(peer_id=_, rtts=list() as rtts, failure_error=None):
                for rtt_ms in rtts:
                    self.rtt.observe(rtt_ms)

            case PingEvent(peer_id=_, rtts=None, failure_error=err) if err is not None:
                self.failures.labels(reason=type(err).__name__).inc()

            case _:
                raise ValueError("Invalid PingEvent state")
