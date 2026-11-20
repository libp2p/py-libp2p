from multiaddr import Multiaddr
from prometheus_client import Counter

_TRANSPORT_NAMES = {
    "TCP": "tcp",
    "QUICTransport": "quic",
    "WebsocketTransport": "websocket",
    "WebRTCDirectTransport": "webrtc_direct",
    "WebRTCPrivateTransport": "webrtc_private",
    "CircuitV2Transport": "circuit_v2",
    "CircuitV2Listener": "circuit_v2",
}


def transport_label(
    transport: object | None = None, maddr: Multiaddr | None = None
) -> str:
    """Return a bounded prometheus label for a transport (class or multiaddr)."""
    if transport is not None:
        name = _TRANSPORT_NAMES.get(type(transport).__name__)
        if name:
            return name
        raw = type(transport).__name__.lower()
        for suffix in ("transport", "listener"):
            raw = raw.replace(suffix, "")
        return raw or "unknown"

    if maddr is not None:
        maddr_str = str(maddr)
        if "quic" in maddr_str:
            return "quic"
        if "webtransport" in maddr_str:
            return "webtransport"
        if "webrtc" in maddr_str:
            return "webrtc_direct"
        if "ws" in maddr_str:
            return "websocket"
        if "p2p-circuit" in maddr_str:
            return "circuit_v2"
        if "tcp" in maddr_str:
            return "tcp"
        return "unknown"

    return "unknown"


class TransportEvent:
    """A transport-level connection event, emitted on the host's event bus."""

    peer_id: str | None = None

    dial_out: bool = False
    conn_in: bool = False

    transport: str | None = None
    success: bool | None = None

    # Debugging details: the multiaddrs involved (remote for outbound dials,
    # local for inbound accepts).
    remote_maddr: str | None = None
    local_maddr: str | None = None


class ListenConn:
    """
    A connection-open/close lifecycle event, emitted on the host's event bus.

    Mirrors the go-libp2p connmgr metrics: connections opened/closed by
    connection type (direct, relayed, unknown).
    """

    peer_id: str | None = None

    conn_open: bool = False
    conn_close: bool = False

    connection_type: str | None = None

    # Debugging details: addresses involved (remote for outbound dials,
    # local for inbound accepts).
    remote_maddr: str | None = None
    local_maddr: str | None = None


class ListenConnMetrics:
    """Prometheus metrics for connection open/close lifecycle events."""

    conns_opened_total: Counter
    conns_closed_total: Counter

    def __init__(self) -> None:
        self.conns_opened_total = Counter(
            "connections_opened_total",
            "Connections opened, by connection type",
            labelnames=["connection_type"],
        )

        self.conns_closed_total = Counter(
            "connections_closed_total",
            "Connections closed, by connection type",
            labelnames=["connection_type"],
        )

    def record(self, event: ListenConn) -> None:
        connection_type = event.connection_type or "unknown"

        if event.conn_open:
            self.conns_opened_total.labels(connection_type=connection_type).inc()

        if event.conn_close:
            self.conns_closed_total.labels(connection_type=connection_type).inc()


class TransportMetrics:
    """Prometheus metrics for the transport layer (dial/accepted connections)."""

    dial_total: Counter
    inbound_conn_total: Counter

    def __init__(self) -> None:
        self.dial_total = Counter(
            "transport_dial_total",
            "Outbound transport dials, by transport and result",
            labelnames=["transport", "result"],
        )

        self.inbound_conn_total = Counter(
            "transport_inbound_conn_total",
            "Inbound connections accepted by listeners, by transport and result",
            labelnames=["transport", "result"],
        )

    def record(self, event: TransportEvent) -> None:
        result = "success" if event.success else "failure"
        transport = event.transport or "unknown"

        if event.dial_out:
            self.dial_total.labels(transport=transport, result=result).inc()
        elif event.conn_in:
            self.inbound_conn_total.labels(transport=transport, result=result).inc()
