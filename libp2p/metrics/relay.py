from dataclasses import dataclass

from prometheus_client import Counter


@dataclass(slots=True)
class RelayEvent:
    """
    Event emitted by the relay behaviour.

    Only the event type is required because the metrics layer
    simply counts occurrences of each event type.
    """

    event_type: str


class RelayEventType:
    """
    Equivalent of the Rust `EventType` enum.
    """

    RESERVATION_REQ_ACCEPTED = "ReservationReqAccepted"
    RESERVATION_REQ_ACCEPT_FAILED = "ReservationReqAcceptFailed"
    RESERVATION_REQ_DENIED = "ReservationReqDenied"
    RESERVATION_REQ_DENY_FAILED = "ReservationReqDenyFailed"
    RESERVATION_CLOSED = "ReservationClosed"
    RESERVATION_TIMED_OUT = "ReservationTimedOut"

    CIRCUIT_REQ_DENIED = "CircuitReqDenied"
    CIRCUIT_REQ_DENY_FAILED = "CircuitReqDenyFailed"
    CIRCUIT_REQ_OUTBOUND_CONNECT_FAILED = "CircuitReqOutboundConnectFailed"

    CIRCUIT_REQ_ACCEPTED = "CircuitReqAccepted"
    CIRCUIT_REQ_ACCEPT_FAILED = "CircuitReqAcceptFailed"

    CIRCUIT_CLOSED = "CircuitClosed"


class RelayMetrics:
    """
    Prometheus metrics for relay behaviour.

    Equivalent to the Rust implementation:

        Family<EventLabels, Counter>

    which becomes a Counter with labels in the Python Prometheus client.
    """

    events: Counter

    def __init__(self) -> None:
        self.events = Counter(
            "relay_events_total",
            "Events emitted by the relay NetworkBehaviour",
            labelnames=["event"],
        )

    def record(self, event: RelayEvent) -> None:
        """
        Record a relay event.
        """
        self.events.labels(event=event.event_type).inc()
