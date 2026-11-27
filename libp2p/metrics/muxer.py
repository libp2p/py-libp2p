from prometheus_client import Counter

_MUXER_NAMES = {
    "Mplex": "mplex",
    "Yamux": "yamux",
}


def muxer_label(muxed_conn: object | None = None, fallback: str = "unknown") -> str:
    """Return a bounded prometheus label for a muxed connection type."""
    if muxed_conn is not None:
        return _MUXER_NAMES.get(type(muxed_conn).__name__, fallback)
    return fallback


class MuxerEvent:
    """A stream-muxer event, emitted on the host's event bus."""

    peer_id: str | None = None

    muxer_conn: bool = False
    muxer_upgrade_failure: bool = False
    stream_open: bool = False
    stream_close: bool = False

    muxer: str | None = None
    direction: str | None = None
    success: bool | None = None

    # Debugging details: full negotiated muxer protocol id (e.g.
    # /yamux/1.0.0) and the addresses involved (remote for outbound dials,
    # local for inbound).
    protocol_id: str | None = None
    remote_maddr: str | None = None
    local_maddr: str | None = None


class MuxerMetrics:
    """Prometheus metrics for stream muxers (yamux/mplex) and muxed streams."""

    conns_total: Counter
    upgrade_failure_total: Counter
    streams_open_total: Counter
    streams_closed_total: Counter

    def __init__(self) -> None:
        self.conns_total = Counter(
            "muxer_conns_total",
            "Muxed connections created, by muxer and direction",
            labelnames=["muxer", "direction"],
        )

        self.upgrade_failure_total = Counter(
            "muxer_upgrade_failure_total",
            "Muxer negotiation/upgrade failures",
            labelnames=["direction"],
        )

        self.streams_open_total = Counter(
            "muxer_streams_open_total",
            "Muxed streams opened, by direction",
            labelnames=["direction"],
        )

        self.streams_closed_total = Counter(
            "muxer_streams_closed_total",
            "Muxed streams closed, by direction",
            labelnames=["direction"],
        )

    def record(self, event: MuxerEvent) -> None:
        direction = event.direction or "unknown"

        if event.muxer_conn:
            self.conns_total.labels(
                muxer=event.muxer or "unknown", direction=direction
            ).inc()

        if event.muxer_upgrade_failure:
            self.upgrade_failure_total.labels(direction=direction).inc()

        if event.stream_open:
            self.streams_open_total.labels(direction=direction).inc()

        if event.stream_close:
            self.streams_closed_total.labels(direction=direction).inc()
