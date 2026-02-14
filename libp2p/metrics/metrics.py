import socket

from prometheus_client import start_http_server
import trio

from libp2p.host.ping import PingEvent
from libp2p.metrics.ping import PingMetrics


def find_available_port(start_port: int = 8000, host: str = "127.0.0.1") -> int:
    port = start_port

    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                port += 1


class Metrics:
    ping: PingMetrics

    def __init__(self):
        self.ping = PingMetrics()

    async def start_prometheus_server(
        self,
        metric_recv_channel: trio.MemoryReceiveChannel,
    ) -> None:
        metrics = find_available_port(8000)
        prometheus_dashboard = find_available_port(9000)
        grafana_dashboard = find_available_port(7000)

        start_http_server(metrics)

        print(f"\nPrometheus metrics visible at: http://localhost:{metrics}")
        print(
            f"Prometheus dashboard visible at: http://localhost:{prometheus_dashboard}"
        )
        print(f"Grafana dashboard visible at: http://localhost:{grafana_dashboard}\n")

        print(
            "\nStart prometheus and grafana dashboard, for another terminal: \n"
            f"PROMETHEUS_PORT={prometheus_dashboard} GRAFANA_PORT={grafana_dashboard} docker compose up\n"
        )

        while True:
            event = await metric_recv_channel.receive()

            match event:
                case PingEvent():
                    self.ping.record(event)
