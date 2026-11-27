from prometheus_client import Counter


class RelayEvent:
    """A circuit-relay v2 event, emitted on the host's event bus."""

    peer_id: str | None = None

    hop_connect: bool = False
    reservation: bool = False
    bytes_forwarded: bool = False

    side: str | None = None  # relay | client
    action: str | None = None  # granted | refreshed | failed | expired
    success: bool | None = None
    amount: int | None = None


class RelayMetrics:
    """Prometheus metrics for the circuit relay v2 protocol."""

    hop_total: Counter
    reservation_total: Counter
    data_forwarded_bytes: Counter

    def __init__(self) -> None:
        self.hop_total = Counter(
            "relay_hop_total",
            "Relay hop connections, by side and result",
            labelnames=["side", "result"],
        )

        self.reservation_total = Counter(
            "relay_reservation_total",
            "Relay reservations, by side and action",
            labelnames=["side", "action"],
        )

        self.data_forwarded_bytes = Counter(
            "relay_data_forwarded_bytes",
            "Bytes forwarded through relayed circuits",
        )

    def record(self, event: RelayEvent) -> None:
        if event.hop_connect:
            result = "success" if event.success else "failure"
            self.hop_total.labels(side=event.side or "unknown", result=result).inc()

        if event.reservation:
            self.reservation_total.labels(
                side=event.side or "unknown", action=event.action or "unknown"
            ).inc()

        if event.bytes_forwarded and event.amount is not None:
            self.data_forwarded_bytes.inc(event.amount)
