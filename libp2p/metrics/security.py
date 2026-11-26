from prometheus_client import Counter, Histogram


def security_protocol_label(protocol: str | None) -> str:
    """
    Return a bounded prometheus label from a negotiated protocol id.

    ``/noise`` -> ``noise``, ``/tls/1.0.0`` -> ``tls``,
    ``/plaintext/2.0.0`` -> ``plaintext``, ``/secio/1.0.0`` -> ``secio``.
    """
    if not protocol:
        return "unknown"
    parts = protocol.strip("/").split("/")
    name = parts[0] if parts else "unknown"
    if name == "tls" or name.startswith("tls"):
        return "tls"
    return name or "unknown"


def security_label_from_error(error: BaseException | None) -> str:
    """Best-effort security-protocol label from an exception cause chain."""
    seen: set[int] = set()

    while error is not None and id(error) not in seen:
        seen.add(id(error))
        class_name = type(error).__name__.lower()
        if "noise" in class_name:
            return "noise"
        if "tls" in class_name:
            return "tls"
        if "secio" in class_name:
            return "secio"
        if "plaintext" in class_name:
            return "plaintext"
        error = error.__cause__

    return "unknown"


class SecurityEvent:
    """A security handshake event, emitted on the host's event bus."""

    peer_id: str | None = None

    handshake: bool = False

    protocol: str | None = None
    protocol_id: str | None = None
    direction: str | None = None
    success: bool | None = None
    duration_ms: float | None = None

    # Debugging details: full negotiated protocol id (e.g. /noise), and the
    # addresses involved (remote for outbound dials, local for inbound).
    remote_maddr: str | None = None
    local_maddr: str | None = None


class SecurityMetrics:
    """Prometheus metrics for security transport handshakes (noise/tls/...)."""

    handshake_total: Counter
    handshake_duration_ms: Histogram

    def __init__(self) -> None:
        self.handshake_total = Counter(
            "security_handshake_total",
            "Security handshakes, by protocol, direction and result",
            labelnames=["protocol", "direction", "result"],
        )

        self.handshake_duration_ms = Histogram(
            "security_handshake_duration_ms",
            "Security handshake duration in milliseconds",
            labelnames=["protocol", "direction"],
            buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
        )

    def record(self, event: SecurityEvent) -> None:
        if not event.handshake:
            return

        protocol = event.protocol or "unknown"
        direction = event.direction or "unknown"
        result = "success" if event.success else "failure"

        self.handshake_total.labels(
            protocol=protocol, direction=direction, result=result
        ).inc()
        if event.duration_ms is not None:
            self.handshake_duration_ms.labels(
                protocol=protocol, direction=direction
            ).observe(event.duration_ms)
