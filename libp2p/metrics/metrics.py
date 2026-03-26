import socket
from typing import Any

from prometheus_client import start_http_server
import trio

from libp2p.host.ping import PingEvent
from libp2p.kad_dht.kad_dht import KadDhtEvent
from libp2p.metrics.gossipsub import GossipsubMetrics
from libp2p.metrics.kad_dht import KadDhtMetrics
from libp2p.metrics.ping import PingMetrics
from libp2p.metrics.swarm import SwarmEvent, SwarmMetrics
from libp2p.pubsub.pubsub import GossipsubEvent


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
    ping: PingMetrics
    gossipsub: GossipsubMetrics
    kad_dht: KadDhtMetrics
    swarm: SwarmMetrics

    def __init__(self) -> None:
        self.ping = PingMetrics()
        self.gossipsub = GossipsubMetrics()
        self.kad_dht = KadDhtMetrics()
        self.swarm = SwarmMetrics()

    async def start_prometheus_server(
        self,
        metric_recv_channel: trio.MemoryReceiveChannel[Any],
    ) -> None:
        metrics = find_available_port(8000)
        prometheus = find_available_port(9000)
        grafana = find_available_port(7000)

        start_http_server(metrics)

        print(f"\nPrometheus metrics visible at: http://localhost:{metrics}")

        print(
            "\nTo start prometheus and grafana dashboards, from another terminal: \n"
            f"PROMETHEUS_PORT={prometheus} GRAFANA_PORT={grafana} docker compose up\n"
            "\nAfter this:\n"
            f"Prometheus dashboard will be visible at: http://localhost:{prometheus}\n"
            f"Grafana dashboard will be visible at: http://localhost:{grafana}\n"
        )

        while True:
            event = await metric_recv_channel.receive()

            match event:
                case PingEvent():
                    self.ping.record(event)
                case GossipsubEvent():
                    self.gossipsub.record(event)
                case KadDhtEvent():
                    self.kad_dht.record(event)
                case SwarmEvent():
                    self.swarm.record(event)
