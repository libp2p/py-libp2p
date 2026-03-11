import time

from prometheus_client import Counter, Histogram


class SwarmMetrics:
    """
    Prometheus metrics for libp2p swarm events.
    Mirrors the Rust libp2p metrics implementation.
    """

    def __init__(self):
        # ---------------------------
        # incoming connections
        # ---------------------------

        self.connections_incoming = Counter(
            "swarm_connections_incoming_total",
            "Number of incoming connections per address stack",
            ["protocols"],
        )

        self.connections_incoming_error = Counter(
            "swarm_connections_incoming_error_total",
            "Number of incoming connection errors",
            ["error", "protocols"],
        )

        # ---------------------------
        # connection lifecycle
        # ---------------------------

        self.connections_established = Counter(
            "swarm_connections_established_total",
            "Number of connections established",
            ["role", "protocols"],
        )

        self.connections_establishment_duration = Histogram(
            "swarm_connections_establishment_duration_seconds",
            "Time taken to establish connection",
            ["role", "protocols"],
            buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10),
        )

        self.connections_duration = Histogram(
            "swarm_connections_duration_seconds",
            "Time a connection was alive",
            ["role", "protocols", "cause"],
            buckets=(0.01, 0.1, 1, 5, 10, 30, 60, 300, 600),
        )

        # ---------------------------
        # listening addresses
        # ---------------------------

        self.new_listen_addr = Counter(
            "swarm_new_listen_addr_total",
            "Number of new listen addresses",
            ["protocols"],
        )

        self.expired_listen_addr = Counter(
            "swarm_expired_listen_addr_total",
            "Number of expired listen addresses",
            ["protocols"],
        )

        # ---------------------------
        # external addresses
        # ---------------------------

        self.external_addr_candidates = Counter(
            "swarm_external_addr_candidates_total",
            "Number of new external address candidates",
            ["protocols"],
        )

        self.external_addr_confirmed = Counter(
            "swarm_external_addr_confirmed_total",
            "Number of confirmed external addresses",
            ["protocols"],
        )

        self.external_addr_expired = Counter(
            "swarm_external_addr_expired_total",
            "Number of expired external addresses",
            ["protocols"],
        )

        # ---------------------------
        # listener lifecycle
        # ---------------------------

        self.listener_closed = Counter(
            "swarm_listener_closed_total",
            "Number of listeners closed",
            ["protocols"],
        )

        self.listener_error = Counter(
            "swarm_listener_error_total",
            "Number of listener errors",
        )

        # ---------------------------
        # dialing
        # ---------------------------

        self.dial_attempt = Counter(
            "swarm_dial_attempt_total",
            "Number of dial attempts",
        )

        self.outgoing_connection_error = Counter(
            "swarm_outgoing_connection_error_total",
            "Outgoing connection errors",
            ["peer", "error"],
        )

        # ---------------------------
        # connection tracking
        # ---------------------------

        self.connections = {}

    # -------------------------------------------------

    def record(self, event):
        """
        Record a SwarmEvent-like object.
        """
        etype = event["type"]

        if etype == "ConnectionEstablished":
            role = event["role"]
            protocols = event["protocols"]
            conn_id = event["connection_id"]
            duration = event.get("established_in", 0)

            self.connections_established.labels(
                role=role,
                protocols=protocols,
            ).inc()

            self.connections_establishment_duration.labels(
                role=role,
                protocols=protocols,
            ).observe(duration)

            self.connections[conn_id] = time.time()

        elif etype == "ConnectionClosed":
            conn_id = event["connection_id"]
            role = event["role"]
            protocols = event["protocols"]
            cause = event.get("cause", "None")

            if conn_id in self.connections:
                elapsed = time.time() - self.connections.pop(conn_id)

                self.connections_duration.labels(
                    role=role,
                    protocols=protocols,
                    cause=cause,
                ).observe(elapsed)

        elif etype == "IncomingConnection":
            self.connections_incoming.labels(protocols=event["protocols"]).inc()

        elif etype == "IncomingConnectionError":
            self.connections_incoming_error.labels(
                error=event["error"],
                protocols=event["protocols"],
            ).inc()

        elif etype == "OutgoingConnectionError":
            self.outgoing_connection_error.labels(
                peer=event["peer"],
                error=event["error"],
            ).inc()

        elif etype == "NewListenAddr":
            self.new_listen_addr.labels(protocols=event["protocols"]).inc()

        elif etype == "ExpiredListenAddr":
            self.expired_listen_addr.labels(protocols=event["protocols"]).inc()

        elif etype == "ListenerClosed":
            self.listener_closed.labels(protocols=event["protocols"]).inc()

        elif etype == "ListenerError":
            self.listener_error.inc()

        elif etype == "Dialing":
            self.dial_attempt.inc()

        elif etype == "NewExternalAddrCandidate":
            self.external_addr_candidates.labels(protocols=event["protocols"]).inc()

        elif etype == "ExternalAddrConfirmed":
            self.external_addr_confirmed.labels(protocols=event["protocols"]).inc()

        elif etype == "ExternalAddrExpired":
            self.external_addr_expired.labels(protocols=event["protocols"]).inc()
