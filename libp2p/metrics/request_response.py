from prometheus_client import Counter, Histogram


class RequestResponseEvent:
    """A request/response exchange event, emitted on the host's event bus."""

    peer_id: str | None = None

    request: bool = False

    protocol: str | None = None
    direction: str | None = None
    success: bool | None = None
    duration_ms: float | None = None


class RequestResponseMetrics:
    """Prometheus metrics for the request/response protocol."""

    requests_total: Counter
    latency_ms: Histogram

    def __init__(self) -> None:
        self.requests_total = Counter(
            "request_response_requests_total",
            "Request/response exchanges, by protocol, direction and result",
            labelnames=["protocol", "direction", "result"],
        )

        self.latency_ms = Histogram(
            "request_response_latency_ms",
            "Request/response exchange duration in milliseconds",
            labelnames=["protocol", "direction"],
            buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000, 10000],
        )

    def record(self, event: RequestResponseEvent) -> None:
        if not event.request:
            return

        protocol = event.protocol or "unknown"
        direction = event.direction or "unknown"
        result = "success" if event.success else "failure"

        self.requests_total.labels(
            protocol=protocol, direction=direction, result=result
        ).inc()
        if event.duration_ms is not None:
            self.latency_ms.labels(protocol=protocol, direction=direction).observe(
                event.duration_ms
            )
