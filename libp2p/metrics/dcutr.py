from prometheus_client import Counter


class DcutrEvent:
    peer_id: str
    success: bool
    error: Exception | None = None


class DcutrMetrics:
    events: Counter

    def __init__(self):
        self.events = Counter(
            "dcutr_events_total",
            "Events emitted by the DCUtR behaviour",
            labelnames=["event"],
        )

    def record(self, event: DcutrEvent) -> None:
        if event.success:
            label = "direct_connection_upgrade_succeeded"
        else:
            label = "direct_connection_upgrade_failed"

        self.events.labels(event=label).inc()
