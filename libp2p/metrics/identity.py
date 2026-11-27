from prometheus_client import Counter


class IdentityEvent:
    """An identify / identify-push event, emitted on the host's event bus."""

    peer_id: str | None = None

    identify: bool = False
    push: bool = False

    direction: str | None = None
    success: bool | None = None


class IdentityMetrics:
    """Prometheus metrics for the identify and identify-push protocols."""

    identify_total: Counter
    push_total: Counter

    def __init__(self) -> None:
        self.identify_total = Counter(
            "identity_identify_total",
            "Identify exchanges, by direction and result",
            labelnames=["direction", "result"],
        )

        self.push_total = Counter(
            "identity_push_total",
            "Identify-push exchanges, by direction and result",
            labelnames=["direction", "result"],
        )

    def record(self, event: IdentityEvent) -> None:
        direction = event.direction or "unknown"
        result = "success" if event.success else "failure"

        if event.identify:
            self.identify_total.labels(direction=direction, result=result).inc()
        elif event.push:
            self.push_total.labels(direction=direction, result=result).inc()
