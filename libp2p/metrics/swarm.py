from prometheus_client import Counter


class SwarmEvent:
    peer_id: str | None = None

    conn_incoming: bool = False
    conn_incoming_error: bool = False
    dial_attempt: bool = False
    dial_attempt_error: bool = False


class SwarmMetrics:
    """
    Prometheus metrics for libp2p swarm events.
    Mirrors the Rust libp2p metrics implementation.
    """

    conn_incoming: Counter
    conn_incoming_error: Counter
    dial_attempt: Counter
    dial_attempt_error: Counter

    def __init__(self) -> None:
        self.conn_incoming = Counter(
            "swarm_incoming_conn",
            "Incoming connection received by libp2p-swarm",
            labelnames=["peer_id"],
        )

        self.conn_incoming_error = Counter(
            "swarm_incoming_conn_error",
            "Incoming connection failure in libp2p-swarm",
            labelnames=["peer_id"],
        )

        self.dial_attempt = Counter(
            "swarm_dial_attempt",
            "Dial attempts made by libp2p-swarm",
            labelnames=["peer_id"],
        )

        self.dial_attempt_error = Counter(
            "swarm_dial_attempt_error",
            "Outgoing connection failure in libp2p-swarm",
            labelnames=["peer_id"],
        )

    def record(self, event: SwarmEvent) -> None:
        if event.conn_incoming:
            self.conn_incoming.labels(peer_id=event.peer_id).inc()

        if event.conn_incoming_error:
            self.conn_incoming_error.labels(peer_id=event.peer_id).inc()

        if event.dial_attempt:
            self.dial_attempt.labels(peer_id=event.peer_id).inc()

        if event.dial_attempt_error:
            self.dial_attempt_error.labels(peer_id=event.peer_id).inc()
