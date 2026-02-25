import pytest
from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.tools.async_service import background_trio_service

GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")


async def create_tcp_host_pair():
    """Create a pair of hosts configured for TCP communication."""
    # Create key pairs
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()

    # Create security options (using plaintext for simplicity)
    def security_options(kp):
        return {
            PLAINTEXT_PROTOCOL_ID: InsecureTransport(
                local_key_pair=kp, secure_bytes_provider=None, peerstore=None
            )
        }

    # Host A (listener) - TCP transport (default)
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options(key_pair_a),
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    # Host B (dialer) - TCP transport (default)
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options(key_pair_b),
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    return host_a, host_b


@pytest.mark.trio
async def test_write_msg_stream_reset():
    """Test that Pubsub.write_msg handles StreamReset exceptions gracefully."""
    host_a, host_b = await create_tcp_host_pair()

    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        host_b.run(listen_addrs=[]),
    ):
        gossipsub_a = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=3,
            degree_low=2,
            degree_high=4,
            direct_peers=None,
            time_to_live=60,
            gossip_window=2,
            gossip_history=5,
            heartbeat_initial_delay=2.0,
            heartbeat_interval=5,
        )

        pubsub_a = Pubsub(host_a, gossipsub_a)

        gossipsub_b = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=3,
            degree_low=2,
            degree_high=4,
            direct_peers=None,
            time_to_live=60,
            gossip_window=2,
            gossip_history=5,
            heartbeat_initial_delay=2.0,
            heartbeat_interval=5,
        )
        pubsub_b = Pubsub(host_b, gossipsub_b)

        async with background_trio_service(pubsub_a):
            async with background_trio_service(gossipsub_a):
                async with background_trio_service(pubsub_b):
                    async with background_trio_service(gossipsub_b):
                        await pubsub_a.wait_until_ready()
                        await pubsub_b.wait_until_ready()
                        # Get host A's listen address
                        listen_addrs = host_a.get_addrs()
                        assert listen_addrs, "Host A should have listen addresses"

                        # Extract TCP address
                        tcp_addr = None
                        for addr in listen_addrs:
                            if "/tcp/" in str(addr) and "/ws" not in str(addr):
                                tcp_addr = addr
                                break

                        assert tcp_addr, f"No TCP address found in {listen_addrs}"

                        # Create peer info for host A
                        peer_info = info_from_p2p_addr(tcp_addr)

                        # Host B connects to host A
                        await host_b.connect(peer_info)

                        await pubsub_a.subscribe("test")
                        await pubsub_b.subscribe("test")

                        # Allow some time for subscriptions to propagate
                        await trio.sleep(1.0)

                        # Get the stream
                        peer_a_id = host_b.get_id()
                        stream = pubsub_a.peers[peer_a_id]

                        await stream.reset()

                        # Wait a moment to ensure stream is reset
                        await trio.sleep(1.0)

                        # Without StreamReset handling in Pubsub.write_msg, this will
                        # raise an exception
                        await pubsub_a.publish("test", b"crash test")
