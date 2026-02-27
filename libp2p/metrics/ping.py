from prometheus_client import Counter, Histogram

from libp2p.host.ping import PingEvent


class PingMetrics:
    rtt: Histogram
    failures: Counter

    def __init__(self):
        rtt = Histogram(
            "ping",
            "round-trip time sending a 'ping' and receiving a 'pong'",
            buckets=[400, 500, 600, 700, 800],
        )

        failures = Counter(
            "ping_failure",
            "FAilure while sending a ping or receiving a ping",
            labelnames=["reason", "peer_id"],
        )

        self.rtt = rtt
        self.failures = failures

    def record(self, event: PingEvent) -> None:
        match event:
            case PingEvent(peer_id=_, rtts=list() as rtts, failure_error=None):
                print(rtts)
                for rtt_us in rtts:
                    self.rtt.observe(rtt_us)

            case PingEvent(peer_id=_, rtts=None, failure_error=err):
                self.failures.labels(reason=type(err).__name__).inc()

            case _:
                raise ValueError("Invalid PingEvent state")
