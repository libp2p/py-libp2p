from prometheus_client import start_http_server
import trio
from libp2p.host.ping import PingEvent
from libp2p.metrics.ping import PingMetrics
from libp2p.utils.address_validation import find_free_port


class Metrics:
    ping: PingMetrics

    def __init__(self):
        self.ping = PingMetrics()

    async def start_prometheus_server(
        self,
        metric_recv_channel: trio.MemoryReceiveChannel,
    ) -> None:
        
        free_port = find_free_port()
        start_http_server(free_port)
        
        print(f"Prometheus server started: http://localhost:{free_port}")

        while True:
            event = await metric_recv_channel.receive()
            
            match event:
                case PingEvent():
                    self.ping.record(event)