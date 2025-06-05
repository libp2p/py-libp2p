"""
mDNS-based peer discovery for py-libp2p.
Conforms to https://github.com/libp2p/specs/blob/master/discovery/mdns.md
Uses zeroconf for mDNS broadcast/listen. Async operations use trio.
"""
import trio
from typing import Callable, Optional
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, ServiceStateChange
from .utils import (
    stringGen
)
from libp2p.abc import (
    INetworkService
)

SERVICE_TYPE = "_p2p._udp.local."
MCAST_PORT = 5353
MCAST_ADDR = "224.0.0.251"

class MDNSDiscovery:
    def __init__(self, swarm: INetworkService):
        self.peer_id = swarm.get_peer_id()
        self.port = 8000  # Default port, can be overridden
        # self.broadcast = init.get('broadcast', True) is not False
        # self.on_peer = on_peer  # Callback: async def on_peer(peer_info)
        # self.service_name = service_name or f"{peer_id}.{SERVICE_TYPE}"
        # self.zeroconf = Zeroconf()
        # self._service_info = ServiceInfo(
        #     SERVICE_TYPE,
        #     self.service_name,
        #     addresses=[],  # Will be set on register
        #     port=self.port,
        #     properties={b'id': peer_id.encode()},
        # )
        # self._browser = None
        # self._running = False

    def main(self) -> None:
        """
        Main entry point for the mDNS discovery service.
        This method is intended to be run in an event loop.
        """
        trio.run(self.start)

    async def start(self):
        await trio.sleep(10)
        # self._running = True
        # await trio.to_thread.run_sync(self.zeroconf.register_service, self._service_info)
        # self._browser = ServiceBrowser(self.zeroconf, SERVICE_TYPE, handlers=[self._on_service_state_change])
        print(f"Starting mDNS discovery for peer {self.peer_id} on port {self.port}")

    async def stop(self):
        # self._running = False
        # await trio.to_thread.run_sync(self.zeroconf.unregister_service, self._service_info)
        # await trio.to_thread.run_sync(self.zeroconf.close)
        print(f"Stopping mDNS discovery for peer {self.peer_id}")

    def _on_service_state_change(self, zeroconf, service_type, name, state_change):
        if state_change is not ServiceStateChange.Added:
            return
        info = zeroconf.get_service_info(service_type, name)
        if not info or name == self.service_name:
            return
        peer_id = info.properties.get(b'id')
        if not peer_id:
            return
        peer_id = peer_id.decode()
        addresses = [addr for addr in info.parsed_addresses()]
        port = info.port
        peer_info = {'peer_id': peer_id, 'addresses': addresses, 'port': port}
        if self.on_peer:
            # Schedule callback in the background
            trio.lowlevel.spawn_system_task(self._call_on_peer, peer_info)

    async def _call_on_peer(self, peer_info):
        if self.on_peer:
            await self.on_peer(peer_info)

# Example usage:
# async def on_peer(peer_info):
#     print(f"Discovered peer: {peer_info['peer_id']} at {peer_info['addresses']}:{peer_info['port']}")
# mdns = MDNSDiscovery(peer_id, port, on_peer)
# await mdns.start()
# ...
# await mdns.stop()
