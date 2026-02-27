from prometheus_client import Counter, Histogram

from libp2p.pubsub.gossipsub import GossipsubEvent


class GossipsubMetrics:
    delivered: Counter
    dropped: Counter
    validated_fail: Counter
    msg_size: Histogram

    def __init__(self):
        self.delivered = Counter(
            "gossipsub_delivered_total",
            "Messages successfully delivered",
            labelnames=["topic"],
        )

        self.dropped = Counter(
            "gossipsub_dropped_total",
            "Messages dropped",
            labelnames=["topic", "reason"],
        )

        self.validated_fail = Counter(
            "gossipsub_validation_failed_total",
            "Messages rejected by validator",
            labelnames=["topic", "error"],
        )

        self.msg_size = Histogram(
            "gossipsub_message_bytes",
            "Message size in bytes",
            buckets=[64, 128, 256, 512, 1024, 2048, 4096],
        )

    def record(self, event: GossipsubEvent) -> None:
        if event.delivered:
            self.delivered.labels(topic=event.topic).inc()

        if event.message_size is not None:
            self.msg_size.observe(event.message_size)

        if event.dropped_reason:
            self.dropped.labels(
                topic=event.topic,
                reason=event.dropped_reason,
            ).inc()

        if event.validation_error:
            self.validated_fail.labels(
                topic=event.topic,
                error=type(event.validation_error).__name__,
            ).inc()