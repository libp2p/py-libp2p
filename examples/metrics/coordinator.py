import multiaddr
import trio

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.host.ping import (
    ID as PING_ID,
    PingService,
    handle_ping,
)
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub

GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
COMMANDS = """
Available commands:
- connect <multiaddr>               - Connect to another peer
- ping <maddr> <count>              - Ping to another peer
- join <topic>                      - Subscribe to a topic
- leave <topic>                     - Unsubscribe to a topic
- publish <topic> <message>         - Publish a message
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

        # Set up Pubsub/Gossipsub
        self.gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=3,  # Number of peers to maintain in mesh
            degree_low=2,  # Lower bound for mesh peers
            degree_high=4,  # Upper bound for mesh peers
            direct_peers=None,  # Direct peers
            time_to_live=60,  # TTL for message cache in seconds
            gossip_window=2,  # Smaller window for faster gossip
            gossip_history=5,  # Keep more history
            heartbeat_initial_delay=2.0,  # Start heartbeats sooner
            heartbeat_interval=5,  # More frequent heartbeats for testing
        )
        self.pubsub = Pubsub(self.host, self.gossipsub)

        # CLI input send/receive channels
        self.input_send_channel, self.input_receive_channel = trio.open_memory_channel(
            100
        )

        self.termination_event = trio.Event()

    async def receive_loop(self, subsription):
        print("Starting receive loop")
        while not self.termination_event.is_set():
            try:
                message = await subsription.get()
                print(f"From: {ID(message.from_id).to_base58()}")
                print(f"Received: {message.data.decode('utf-8')}")
            except Exception:
                print("Error in receive loop")
                await trio.sleep(1)

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
                        print(f"Connected to {info.peer_id}")

                    if cmd == "ping" and len(parts) > 1:
                        maddr = multiaddr.Multiaddr(parts[1])
                        info = info_from_p2p_addr(maddr)

                        await self.host.connect(info)
                        await self.ping_service.ping(info.peer_id, int(parts[2]))

                    if cmd == "join" and len(parts) > 1:
                        subscription = await self.pubsub.subscribe(parts[1])
                        nursery.start_soon(self.receive_loop, subscription)
                        print(f"Subscribed to {parts[1]}")

                    if cmd == "leave" and len(parts) > 1:
                        await self.pubsub.unsubscribe(parts[1])
                        print(f"Unsubscribed to {parts[1]}")

                    if cmd == "publish" and len(parts) > 2:
                        await self.pubsub.publish(parts[1], parts[2].encode())
                        print(f"Published: {parts[2]}")

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
