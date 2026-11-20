import logging
import socket
from typing import TYPE_CHECKING, Any

from prometheus_client import start_http_server
import trio

from libp2p.events import EventBus
from libp2p.host.ping import PingEvent
from libp2p.kad_dht.events import KadDhtEvent
from libp2p.metrics.bitswap import BitswapMetrics
from libp2p.metrics.discovery import DiscoveryMetrics
from libp2p.metrics.gossipsub import GossipsubMetrics
from libp2p.metrics.identity import IdentityMetrics
from libp2p.metrics.kad_dht import KadDhtMetrics
from libp2p.metrics.muxer import MuxerMetrics
from libp2p.metrics.ping import PingMetrics
from libp2p.metrics.relay import RelayMetrics
from libp2p.metrics.request_response import RequestResponseMetrics
from libp2p.metrics.security import SecurityMetrics
from libp2p.metrics.swarm import SwarmEvent, SwarmMetrics
from libp2p.metrics.transport import (
    ListenConn,
    ListenConnMetrics,
    TransportMetrics,
)
from libp2p.pubsub.pubsub import GossipsubEvent

if TYPE_CHECKING:
    from libp2p.metrics.rcmgr import RcMgrMetrics

logger = logging.getLogger("libp2p.metrics")


def find_available_port(start_port: int = 8000, host: str = "127.0.0.1") -> int:
    port = start_port

    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                port += 1

    raise RuntimeError("Unreachable")


class Metrics:
    """
    Prometheus collectors for all libp2p modules.

    ``Metrics()`` is a process-wide singleton: constructing it again returns
    the already-initialized instance. This keeps multi-host processes (e.g.
    tests or embedded peers) from re-registering the same family names on the
    default registry, which would raise ``ValueError: Duplicated timeseries``.
    """

    _instance: "Metrics | None" = None

    ping: PingMetrics
    gossipsub: GossipsubMetrics
    kad_dht: KadDhtMetrics
    swarm: SwarmMetrics
    bitswap: BitswapMetrics
    discovery: DiscoveryMetrics
    identity: IdentityMetrics
    relay: RelayMetrics
    transport: TransportMetrics
    muxer: MuxerMetrics
    security: SecurityMetrics
    request_response: RequestResponseMetrics
    listen_conns: ListenConnMetrics

    rcmgr: "RcMgrMetrics | None"

    def __new__(cls, *args: Any, **kwargs: Any) -> "Metrics":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, resource_manager: Any = None) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.ping = PingMetrics()
        self.gossipsub = GossipsubMetrics()
        self.kad_dht = KadDhtMetrics()
        self.swarm = SwarmMetrics()
        self.bitswap = BitswapMetrics()
        self.discovery = DiscoveryMetrics()
        self.identity = IdentityMetrics()
        self.relay = RelayMetrics()
        self.transport = TransportMetrics()
        self.muxer = MuxerMetrics()
        self.security = SecurityMetrics()
        self.request_response = RequestResponseMetrics()
        self.listen_conns = ListenConnMetrics()
        self.rcmgr = None

        if resource_manager is not None:
            self.attach_rcmgr(resource_manager)

    def attach_rcmgr(self, resource_manager: Any) -> "Metrics":
        """
        Expose the resource manager's counters on the shared Prometheus
        registry (go-libp2p-style ``libp2p_rcmgr_*`` gauges). No-op if the
        resource manager exposes no ``metrics`` summary.
        """
        from prometheus_client.registry import REGISTRY

        from libp2p.metrics.rcmgr import RcMgrMetrics

        bridge = RcMgrMetrics(resource_manager)
        try:
            REGISTRY.unregister(bridge)
        except Exception:
            pass
        try:
            REGISTRY.register(bridge)
        except Exception:
            pass
        self.rcmgr = bridge
        return self

    def attach(self, event_bus: EventBus) -> "Metrics":
        """
        Register a metrics listener on ``event_bus`` and return self.

        From this point on, every event emitted on the bus (DHT lookups,
        Bitswap block transfers, discovery events, pubsub messages, ping
        RTTs, swarm dials) is recorded into these Prometheus metrics.

        Example::

            metrics = Metrics()
            metrics.attach(host.get_event_bus())
            metrics.start_http_server()
        """
        from libp2p.metrics.listener import MetricsListener

        event_bus.register_listener(MetricsListener(self))
        return self

    def start_http_server(self, port: int | None = None) -> int:
        """
        Start the Prometheus HTTP scrape endpoint and return its port.

        Unlike :meth:`start_prometheus_server` (the legacy channel-based
        consumer), this only exposes the metrics registry over HTTP — event
        consumption is handled by :meth:`attach` instead.
        """
        port = find_available_port(port if port is not None else 8000)
        start_http_server(port)
        return port

    async def start_prometheus_server(
        self,
        metric_recv_channel: trio.MemoryReceiveChannel[Any],
    ) -> None:
        metrics = find_available_port(8000)
        prometheus = find_available_port(9000)
        grafana = find_available_port(7000)

        start_http_server(metrics)

        logger.info(f"Prometheus metrics visible at: http://localhost:{metrics}")

        logger.info(
            "To start prometheus and grafana dashboards, from another terminal: \n"
            f"PROMETHEUS_PORT={prometheus} GRAFANA_PORT={grafana} docker compose up\n"
            "\nAfter this:\n"
            f"Prometheus dashboard will be visible at: http://localhost:{prometheus}\n"
            f"Grafana dashboard will be visible at: http://localhost:{grafana}\n"
        )

        while True:
            event = await metric_recv_channel.receive()

            try:
                match event:
                    case PingEvent():
                        self.ping.record(event)
                    case GossipsubEvent():
                        self.gossipsub.record(event)
                    case KadDhtEvent():
                        self.kad_dht.record(event)
                    case SwarmEvent():
                        self.swarm.record(event)
                    case ListenConn():
                        self.listen_conns.record(event)
            except Exception:
                logger.debug("Failed to record metric event: %r", event, exc_info=True)
