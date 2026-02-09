import multiaddr
import trio

from libp2p import new_host
from libp2p.host.ping import (
    ID as PING_ID,
    PingService,
    handle_ping,
)
from libp2p.peer.peerinfo import info_from_p2p_addr

COMMANDS = """
Available commands:
- connect <multiaddr>               - Connect to another peer
- ping <maddr> <count>              - Ping to another peer
- local                             - List local multiaddr
- help                              - List the existing commands
- exit                              - Shut down
"""


class Node:
    def __init__(self, listen_addrs: list[multiaddr.Multiaddr]):
        # Create a libp2p-host
        self.host = new_host(listen_addrs=listen_addrs, enable_metrics=True)

        # Setup PING service
        self.host.set_stream_handler(PING_ID, handle_ping)
        self.ping_service = PingService(self.host)

        # CLI input send/receive channels
        self.input_send_channel, self.input_receive_channel = trio.open_memory_channel(
            100
        )

        self.termination_event = trio.Event()

    async def command_executor(self, nursery):
        print("Starting command executor loop...")

        async with self.input_receive_channel:
            async for parts in self.input_receive_channel:
                try:
                    if not parts:
                        continue
                    cmd = parts[0].lower()

                    if cmd == "connect" and len(parts) > 1:
                        maddr = multiaddr.Multiaddr(parts[1])
                        info = info_from_p2p_addr(maddr)

                        await self.host.connect(info)
                        print("Connected to {info.peer_id}")

                    if cmd == "ping" and len(parts) > 1:
                        maddr = multiaddr.Multiaddr(parts[1])
                        info = info_from_p2p_addr(maddr)

                        await self.host.connect(info)
                        await self.ping_service.ping(info.peer_id, int(parts[2]))

                        # Then the rtts will be fed to the prometheus-metrics

                    if cmd == "local":
                        maddr = self.host.get_addrs()[0]
                        print(maddr)

                    if cmd == "help":
                        print(COMMANDS)

                    if cmd == "exit":
                        print("Exiting...")
                        self.termination_event.set()
                        nursery.cancel_scope.cancel()  # Stops all tasks
                        raise KeyboardInterrupt

                except Exception as e:
                    print(f"Error executing command {parts}: {e}")
