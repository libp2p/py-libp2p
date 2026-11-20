"""
Event-bus listener that records events into the Prometheus metrics.

``MetricsListener`` is the bridge between the INotifee-style event bus and
the per-module Prometheus collectors: register it on a host's event bus
(``host.get_event_bus().register_listener(MetricsListener())``, or use
``Metrics.attach(event_bus)``) and every module event is recorded.
"""

from typing import Any

from libp2p.bitswap.events import BitswapEvent
from libp2p.discovery.events.events import DiscoveryEvent
from libp2p.events import IEventListener
from libp2p.host.ping import PingEvent
from libp2p.kad_dht.events import KadDhtEvent
from libp2p.metrics.identity import IdentityEvent
from libp2p.metrics.metrics import Metrics
from libp2p.metrics.muxer import MuxerEvent
from libp2p.metrics.relay import RelayEvent
from libp2p.metrics.request_response import RequestResponseEvent
from libp2p.metrics.security import SecurityEvent
from libp2p.metrics.swarm import SwarmEvent
from libp2p.metrics.transport import (
    ListenConn,
    TransportEvent,
)
from libp2p.pubsub.pubsub import GossipsubEvent


class MetricsListener(IEventListener):
    """
    Fan out bus events to the per-module Prometheus metric collectors.

    Fast and non-blocking (prometheus counter increments), so it is safe
    to register on any host's event bus.
    """

    def __init__(self, metrics: Metrics | None = None) -> None:
        self.metrics = metrics if metrics is not None else Metrics()

    def handle_event(self, event: Any) -> None:
        match event:
            case PingEvent():
                self.metrics.ping.record(event)
            case GossipsubEvent():
                self.metrics.gossipsub.record(event)
            case KadDhtEvent():
                self.metrics.kad_dht.record(event)
            case SwarmEvent():
                self.metrics.swarm.record(event)
            case BitswapEvent():
                self.metrics.bitswap.record(event)
            case DiscoveryEvent():
                self.metrics.discovery.record(event)
            case IdentityEvent():
                self.metrics.identity.record(event)
            case RelayEvent():
                self.metrics.relay.record(event)
            case TransportEvent():
                self.metrics.transport.record(event)
            case ListenConn():
                self.metrics.listen_conns.record(event)
            case MuxerEvent():
                self.metrics.muxer.record(event)
            case SecurityEvent():
                self.metrics.security.record(event)
            case RequestResponseEvent():
                self.metrics.request_response.record(event)
