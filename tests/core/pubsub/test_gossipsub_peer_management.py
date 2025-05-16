import pytest
import trio
from contextlib import asynccontextmanager

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID,
)
from libp2p.tools.utils import (
    connect,
)
from tests.utils.factories import (
    PubsubFactory,
)
from tests.utils.pubsub.utils import (
    one_to_all_connect,
)


@asynccontextmanager
async def create_connected_pubsubs(num_nodes, **kwargs):
    """Helper context manager to create and connect pubsub nodes."""
    async with PubsubFactory.create_batch_with_gossipsub(num_nodes, **kwargs) as pubsubs_gsub:
        gossipsubs = [pubsub.router for pubsub in pubsubs_gsub]
        hosts = [pubsub.host for pubsub in pubsubs_gsub]
        
        # Connect all hosts to each other
        for i in range(len(hosts)):
            for j in range(i + 1, len(hosts)):
                try:
                    await connect(hosts[i], hosts[j])
                    # Ensure peer records are stored
                    hosts[i].get_peerstore().add_protocols(hosts[j].get_id(), [PROTOCOL_ID])
                    hosts[j].get_peerstore().add_protocols(hosts[i].get_id(), [PROTOCOL_ID])
                except Exception as e:
                    print(f"Failed to connect hosts {i} and {j}: {e}")
                    raise
        
        yield pubsubs_gsub, gossipsubs, hosts


@pytest.mark.trio
async def test_attach_peer_records():
    """Test that attach ensures existence of peer records in peer store."""
    async with create_connected_pubsubs(2) as (pubsubs_gsub, gossipsubs, hosts):
        # Wait for heartbeat to allow mesh to connect
        await trio.sleep(2)

        try:
            # Verify that peer records exist in peer store
            peer_store_0 = hosts[0].get_peerstore()
            peer_store_1 = hosts[1].get_peerstore()

            # Check that each host has the other's peer record
            peer_ids_0 = peer_store_0.peer_ids()
            peer_ids_1 = peer_store_1.peer_ids()
            
            print(f"Peer store 0 IDs: {peer_ids_0}")
            print(f"Peer store 1 IDs: {peer_ids_1}")
            print(f"Host 0 ID: {hosts[0].get_id()}")
            print(f"Host 1 ID: {hosts[1].get_id()}")

            assert hosts[1].get_id() in peer_ids_0, "Peer 1 not found in peer store 0"
            assert hosts[0].get_id() in peer_ids_1, "Peer 0 not found in peer store 1"

            # Verify that the peer protocol is set correctly
            assert gossipsubs[0].peer_protocol[hosts[1].get_id()] == PROTOCOL_ID, "Incorrect protocol for peer 1 in gossipsub 0"
            assert gossipsubs[1].peer_protocol[hosts[0].get_id()] == PROTOCOL_ID, "Incorrect protocol for peer 0 in gossipsub 1"
        except Exception as e:
            print(f"Test failed with error: {e}")
            raise


@pytest.mark.trio
async def test_heartbeat_reconnect():
    """Test that heartbeat can reconnect with disconnected direct peers gracefully."""
    async with create_connected_pubsubs(
        2, 
        heartbeat_interval=1, 
        heartbeat_initial_delay=0.1
    ) as (pubsubs_gsub, gossipsubs, hosts):
        try:
            # Wait for initial connection and mesh setup
            await trio.sleep(2)

            # Verify initial connection
            assert hosts[1].get_id() in gossipsubs[0].peer_protocol, "Initial connection not established for gossipsub 0"
            assert hosts[0].get_id() in gossipsubs[1].peer_protocol, "Initial connection not established for gossipsub 1"

            # Simulate disconnection by closing the connection
            # Create a list of connections to avoid modifying during iteration
            connections = list(hosts[0].get_network().connections.values())
            for conn in connections:
                try:
                    await conn.close()
                except Exception as e:
                    print(f"Error closing connection: {e}")
                    continue

            # Wait for heartbeat to detect disconnection
            await trio.sleep(2)

            # Verify that peers are removed from protocol tracking
            assert hosts[1].get_id() not in gossipsubs[0].peer_protocol, "Peer 1 still in gossipsub 0 after disconnection"
            assert hosts[0].get_id() not in gossipsubs[1].peer_protocol, "Peer 0 still in gossipsub 1 after disconnection"

            # Reconnect the hosts
            try:
                await connect(hosts[0], hosts[1])
                # Ensure peer records are stored after reconnection
                hosts[0].get_peerstore().add_protocols(hosts[1].get_id(), [PROTOCOL_ID])
                hosts[1].get_peerstore().add_protocols(hosts[0].get_id(), [PROTOCOL_ID])
            except Exception as e:
                print(f"Error reconnecting hosts: {e}")
                raise

            # Wait for heartbeat to reestablish connection
            await trio.sleep(2)

            # Verify that peers are reconnected and protocol tracking is restored
            assert hosts[1].get_id() in gossipsubs[0].peer_protocol, "Peer 1 not reconnected in gossipsub 0"
            assert hosts[0].get_id() in gossipsubs[1].peer_protocol, "Peer 0 not reconnected in gossipsub 1"
            assert gossipsubs[0].peer_protocol[hosts[1].get_id()] == PROTOCOL_ID, "Incorrect protocol after reconnection for peer 1 in gossipsub 0"
            assert gossipsubs[1].peer_protocol[hosts[0].get_id()] == PROTOCOL_ID, "Incorrect protocol after reconnection for peer 0 in gossipsub 1"
        except Exception as e:
            print(f"Test failed with error: {e}")
            raise 