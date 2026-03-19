from prometheus_client import Counter, Histogram

from libp2p.pubsub.pubsub import GossipsubEvent


class GossipsubMetrics:
    publish: Counter
    subopts: Counter
    control: Counter

    received: Counter
    msg_size: Histogram

    def __init__(self):
        self.received = Counter(
            "gossipsub_receiived_total",
            "Messages successfully received",
            labelnames=["peer_id"],
        )

        self.publish = Counter(
            "gossipsub_publish_total",
            "Messages to be published",
            labelnames=["peer_id"],
        )

        self.subopts = Counter(
            "gossipsub_subopts_total",
            "Messages notifying peer subscriptions",
            labelnames=["peer_id"],
        )

        self.control = Counter(
            "gossipsub_control_total",
            "Received control messages",
            labelnames=["peer_id"],
        )

        self.msg_size = Histogram(
            "gossipsub_message_bytes",
            "Message size in bytes",
            buckets=[64, 128, 256, 512, 1024, 2048, 4096],
        )

    def record(self, event: GossipsubEvent) -> None:
        self.received.labels(peer_id=event.peer_id).inc()

        if event.publish:
            self.publish.labels(peer_id=event.peer_id).inc()

        if event.subopts:
            self.subopts.labels(peer_id=event.peer_id).inc()

        if event.control:
            self.control.labels(peer_id=event.peer_id).inc()

        if event.message_size is not None:
            self.msg_size.observe(event.message_size)
