from contextlib import (
    asynccontextmanager,
)

import pytest
import trio

from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import (
    PERMANENT_ADDR_TTL,
)
from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID,
)
from libp2p.tools.utils import (
    connect,
)
from tests.utils.factories import (
    PubsubFactory,
)


@asynccontextmanager
async def create_connected_pubsubs(num_nodes, **kwargs):
    """Helper context manager to create and connect pubsub nodes."""
    async with PubsubFactory.create_batch_with_gossipsub(
        num_nodes, **kwargs
    ) as pubsubs_gsub:
        gossipsubs = [pubsub.router for pubsub in pubsubs_gsub]
        hosts = [pubsub.host for pubsub in pubsubs_gsub]

        # Connect all hosts to each other
        for i in range(len(hosts)):
            for j in range(i + 1, len(hosts)):
                try:
                    await connect(hosts[i], hosts[j])
                except Exception as e:
                    print(f"Failed to connect hosts {i} and {j}: {e}")
                    raise

        yield pubsubs_gsub, gossipsubs, hosts


@pytest.mark.trio
async def test_attach_peer_records():
    """Test that attach ensures existence of peer records in peer store."""
    # Create first host
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs_gsub_0:
        host_0 = pubsubs_gsub_0[0].host
        gsub_0 = pubsubs_gsub_0[0].router

        # Create second host with first host as direct peer
        async with PubsubFactory.create_batch_with_gossipsub(
            1, direct_peers=[PeerInfo(host_0.get_id(), host_0.get_addrs())]
        ) as pubsubs_gsub_1:
            host_1 = pubsubs_gsub_1[0].host
            gsub_1 = pubsubs_gsub_1[0].router

            # Connect the hosts
            await connect(host_0, host_1)

            # Wait for heartbeat to allow mesh to connect
            await trio.sleep(2)

            try:
                # Verify that peer records exist in peer store
                peer_store_0 = host_0.get_peerstore()
                peer_store_1 = host_1.get_peerstore()

                # Check that each host has the other's peer record
                peer_ids_0 = peer_store_0.peer_ids()
                peer_ids_1 = peer_store_1.peer_ids()

                print(f"Peer store 0 IDs: {peer_ids_0}")
                print(f"Peer store 1 IDs: {peer_ids_1}")
                print(f"Host 0 ID: {host_0.get_id()}")
                print(f"Host 1 ID: {host_1.get_id()}")

                assert host_1.get_id() in peer_ids_0, "Peer 1 not found in peer store 0"
                assert host_0.get_id() in peer_ids_1, "Peer 0 not found in peer store 1"

                # Verify that the peer protocol is set correctly
                assert (
                    gsub_0.peer_protocol[host_1.get_id()] == PROTOCOL_ID
                ), "Incorrect protocol for peer 1 in gossipsub 0"
                assert (
                    gsub_1.peer_protocol[host_0.get_id()] == PROTOCOL_ID
                ), "Incorrect protocol for peer 0 in gossipsub 1"

                # Verify direct peer status
                assert (
                    host_0.get_id() in gsub_1.direct_peers
                ), "Host 0 not marked as direct peer in gsub 1"

                # Verify peer addresses are stored with PERMANENT_ADDR_TTL
                addrs_0 = peer_store_0.get_addrs(host_1.get_id())
                addrs_1 = peer_store_1.get_addrs(host_0.get_id())

                print(f"Peer store 0 addresses for peer 1: {addrs_0}")
                print(f"Peer store 1 addresses for peer 0: {addrs_1}")

                assert (
                    len(addrs_0) > 0
                ), "No addresses stored for peer 1 in peer store 0"
                assert (
                    len(addrs_1) > 0
                ), "No addresses stored for peer 0 in peer store 1"

                # Verify addresses are stored with PERMANENT_ADDR_TTL
                for addr in addrs_0:
                    ttl = peer_store_0.get_addr_ttl(host_1.get_id(), addr)
                    assert ttl == PERMANENT_ADDR_TTL, (
                        f"Address {addr} for peer 1 not stored with "
                        f"PERMANENT_ADDR_TTL in peer store 0"
                    )

                for addr in addrs_1:
                    ttl = peer_store_1.get_addr_ttl(host_0.get_id(), addr)
                    assert ttl == PERMANENT_ADDR_TTL, (
                        f"Address {addr} for peer 0 not stored with "
                        f"PERMANENT_ADDR_TTL in peer store 1"
                    )

            except Exception as e:
                print(f"Test failed with error: {e}")
                raise


@pytest.mark.trio
async def test_heartbeat_reconnect():
    """Test that heartbeat can reconnect with disconnected direct peers gracefully."""
    # Create first host
    async with PubsubFactory.create_batch_with_gossipsub(
        1, heartbeat_interval=2, heartbeat_initial_delay=1
    ) as pubsubs_gsub_0:
        host_0 = pubsubs_gsub_0[0].host
        gsub_0 = pubsubs_gsub_0[0].router

        # Create second host with first host as direct peer
        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            heartbeat_interval=2,
            heartbeat_initial_delay=1,
            direct_peers=[PeerInfo(host_0.get_id(), host_0.get_addrs())],
        ) as pubsubs_gsub_1:
            host_1 = pubsubs_gsub_1[0].host
            gsub_1 = pubsubs_gsub_1[0].router

            # Connect the hosts
            await connect(host_0, host_1)

            try:
                # Wait for initial connection and mesh setup
                await trio.sleep(2)

                # Verify initial connection
                assert (
                    host_1.get_id() in gsub_0.peer_protocol
                ), "Initial connection not established for gossipsub 0"
                assert (
                    host_0.get_id() in gsub_1.peer_protocol
                ), "Initial connection not established for gossipsub 1"

                # Verify direct peer status
                assert (
                    host_0.get_id() in gsub_1.direct_peers
                ), "Host 0 not marked as direct peer in gsub 1"

                # Verify peer addresses are stored with PERMANENT_ADDR_TTL
                peer_store_0 = host_0.get_peerstore()
                peer_store_1 = host_1.get_peerstore()

                addrs_0 = peer_store_0.get_addrs(host_1.get_id())
                addrs_1 = peer_store_1.get_addrs(host_0.get_id())

                assert (
                    len(addrs_0) > 0
                ), "No addresses stored for peer 1 in peer store 0"
                assert (
                    len(addrs_1) > 0
                ), "No addresses stored for peer 0 in peer store 1"

                # Verify addresses are stored with PERMANENT_ADDR_TTL
                for addr in addrs_0:
                    ttl = peer_store_0.get_addr_ttl(host_1.get_id(), addr)
                    assert ttl == PERMANENT_ADDR_TTL, (
                        f"Address {addr} for peer 1 not stored with "
                        f"PERMANENT_ADDR_TTL in peer store 0"
                    )

                for addr in addrs_1:
                    ttl = peer_store_1.get_addr_ttl(host_0.get_id(), addr)
                    assert ttl == PERMANENT_ADDR_TTL, (
                        f"Address {addr} for peer 0 not stored with "
                        f"PERMANENT_ADDR_TTL in peer store 1"
                    )

                # Simulate disconnection by closing the connection
                # Create a list of connections to avoid modifying during iteration
                connections = list(host_0.get_network().connections.values())
                for conn in connections:
                    try:
                        await conn.close()
                    except Exception as e:
                        print(f"Error closing connection: {e}")
                        continue

                # Wait for heartbeat to detect disconnection
                await trio.sleep(2)

                # Verify that peers are removed from protocol tracking
                assert (
                    host_1.get_id() not in gsub_0.peer_protocol
                ), "Peer 1 still in gossipsub 0 after disconnection"
                assert (
                    host_0.get_id() not in gsub_1.peer_protocol
                ), "Peer 0 still in gossipsub 1 after disconnection"

                # Verify addresses are still stored with
                # PERMANENT_ADDR_TTL after disconnection
                addrs_0 = peer_store_0.get_addrs(host_1.get_id())
                addrs_1 = peer_store_1.get_addrs(host_0.get_id())

                assert (
                    len(addrs_0) > 0
                ), "No addresses stored for peer 1 in peer store 0 after disconnection"
                assert (
                    len(addrs_1) > 0
                ), "No addresses stored for peer 0 in peer store 1 after disconnection"

                for addr in addrs_0:
                    ttl = peer_store_0.get_addr_ttl(host_1.get_id(), addr)
                    assert ttl == PERMANENT_ADDR_TTL, (
                        f"Address {addr} for peer 1 not stored with "
                        f"PERMANENT_ADDR_TTL in peer store 0 after disconnection"
                    )

                for addr in addrs_1:
                    ttl = peer_store_1.get_addr_ttl(host_0.get_id(), addr)
                    assert ttl == PERMANENT_ADDR_TTL, (
                        f"Address {addr} for peer 0 not stored with "
                        f"PERMANENT_ADDR_TTL in peer store 1 after disconnection"
                    )

                # Reconnect the hosts
                try:
                    await connect(host_0, host_1)
                except Exception as e:
                    print(f"Error reconnecting hosts: {e}")
                    raise

                # Wait for heartbeat to reestablish connection
                await trio.sleep(2)

                # Verify that peers are reconnected and protocol tracking is restored
                assert (
                    host_1.get_id() in gsub_0.peer_protocol
                ), "Peer 1 not reconnected in gossipsub 0"
                assert (
                    host_0.get_id() in gsub_1.peer_protocol
                ), "Peer 0 not reconnected in gossipsub 1"
                assert (
                    gsub_0.peer_protocol[host_1.get_id()] == PROTOCOL_ID
                ), "Incorrect protocol after reconnection for peer 1 in gossipsub 0"
                assert (
                    gsub_1.peer_protocol[host_0.get_id()] == PROTOCOL_ID
                ), "Incorrect protocol after reconnection for peer 0 in gossipsub 1"

                # Verify direct peer status is maintained
                assert (
                    host_0.get_id() in gsub_1.direct_peers
                ), "Host 0 not marked as direct peer in gsub 1 after reconnection"

                # Verify addresses are still stored with
                # PERMANENT_ADDR_TTL after reconnection
                addrs_0 = peer_store_0.get_addrs(host_1.get_id())
                addrs_1 = peer_store_1.get_addrs(host_0.get_id())

                assert (
                    len(addrs_0) > 0
                ), "No addresses stored for peer 1 in peer store 0 after reconnection"
                assert (
                    len(addrs_1) > 0
                ), "No addresses stored for peer 0 in peer store 1 after reconnection"

                for addr in addrs_0:
                    ttl = peer_store_0.get_addr_ttl(host_1.get_id(), addr)
                    assert ttl == PERMANENT_ADDR_TTL, (
                        f"Address {addr} for peer 1 not stored with "
                        f"PERMANENT_ADDR_TTL in peer store 0 after reconnection"
                    )

                for addr in addrs_1:
                    ttl = peer_store_1.get_addr_ttl(host_0.get_id(), addr)
                    assert ttl == PERMANENT_ADDR_TTL, (
                        f"Address {addr} for peer 0 not stored with "
                        f"PERMANENT_ADDR_TTL in peer store 1 after reconnection"
                    )

            except Exception as e:
                print(f"Test failed with error: {e}")
                raise
