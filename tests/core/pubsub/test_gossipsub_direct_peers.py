import pytest
import trio

from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.pubsub.gossipsub import (
    GossipSub,
)
from libp2p.tools.utils import (
    connect,
)
from tests.utils.factories import (
    PubsubFactory,
)


@pytest.mark.trio
async def test_attach_peer_records():
    """Test that attach ensures existence of peer records in peer store."""
    # Create first host
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs_gsub_0:
        host_0 = pubsubs_gsub_0[0].host

        # Create second host with first host as direct peer
        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            direct_peers=[info_from_p2p_addr(host_0.get_addrs()[0])],
        ) as pubsubs_gsub_1:
            host_1 = pubsubs_gsub_1[0].host

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

                assert host_0.get_id() in peer_ids_1, "Peer 0 not found in peer store 1"

            except Exception as e:
                print(f"Test failed with error: {e}")
                raise


@pytest.mark.trio
async def test_reject_graft():
    """Test that graft requests are rejected if the sender is a direct peer."""
    # Create first host
    async with PubsubFactory.create_batch_with_gossipsub(
        1, heartbeat_interval=1, direct_connect_interval=2
    ) as pubsubs_gsub_0:
        host_0 = pubsubs_gsub_0[0].host

        # Create second host with first host as direct peer
        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            heartbeat_interval=1,
            direct_peers=[info_from_p2p_addr(host_0.get_addrs()[0])],
            direct_connect_interval=2,
        ) as pubsubs_gsub_1:
            host_1 = pubsubs_gsub_1[0].host

            try:
                # Connect the hosts
                await connect(host_0, host_1)

                # Wait 2 seconds for heartbeat to allow mesh to connect
                await trio.sleep(1)

                topic = "test_reject_graft"

                # Gossipsub 0 and 1 joins topic
                await pubsubs_gsub_0[0].router.join(topic)
                await pubsubs_gsub_1[0].router.join(topic)

                # Pre-Graft assertions
                assert topic in pubsubs_gsub_0[0].router.mesh, (
                    "topic not in mesh for gossipsub 0"
                )
                assert topic in pubsubs_gsub_1[0].router.mesh, (
                    "topic not in mesh for gossipsub 1"
                )
                assert host_1.get_id() not in pubsubs_gsub_0[0].router.mesh[topic], (
                    "gossipsub 1 in mesh topic for gossipsub 0"
                )
                assert host_0.get_id() not in pubsubs_gsub_1[0].router.mesh[topic], (
                    "gossipsub 0 in mesh topic for gossipsub 1"
                )

                # Gossipsub 1 emits a graft request to Gossipsub 0
                router_obj = pubsubs_gsub_0[0].router
                assert isinstance(router_obj, GossipSub)
                await router_obj.emit_graft(topic, host_1.get_id())

                await trio.sleep(1)

                # Post-Graft assertions
                assert host_1.get_id() not in pubsubs_gsub_0[0].router.mesh[topic], (
                    "gossipsub 1 in mesh topic for gossipsub 0"
                )
                assert host_0.get_id() not in pubsubs_gsub_1[0].router.mesh[topic], (
                    "gossipsub 0 in mesh topic for gossipsub 1"
                )

            except Exception as e:
                print(f"Test failed with error: {e}")
                raise


@pytest.mark.trio
async def test_heartbeat_reconnect():
    """Test that heartbeat can reconnect with disconnected direct peers gracefully."""
    # Create first host
    async with PubsubFactory.create_batch_with_gossipsub(
        1, heartbeat_interval=1, direct_connect_interval=3
    ) as pubsubs_gsub_0:
        host_0 = pubsubs_gsub_0[0].host

        # Create second host with first host as direct peer
        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            heartbeat_interval=1,
            direct_peers=[info_from_p2p_addr(host_0.get_addrs()[0])],
            direct_connect_interval=3,
        ) as pubsubs_gsub_1:
            host_1 = pubsubs_gsub_1[0].host

            # Connect the hosts
            await connect(host_0, host_1)

            try:
                # Wait for initial connection and mesh setup
                await trio.sleep(1)

                # Verify initial connection
                assert host_1.get_id() in pubsubs_gsub_0[0].peers, (
                    "Initial connection not established for gossipsub 0"
                )
                assert host_0.get_id() in pubsubs_gsub_1[0].peers, (
                    "Initial connection not established for gossipsub 0"
                )

                # Simulate disconnection
                await host_0.disconnect(host_1.get_id())

                # Wait for heartbeat to detect disconnection
                await trio.sleep(1)

                # Verify that peers are removed after disconnection
                assert host_0.get_id() not in pubsubs_gsub_1[0].peers, (
                    "Peer 0 still in gossipsub 1 after disconnection"
                )

                # Wait for heartbeat to reestablish connection
                await trio.sleep(2)

                # Verify connection reestablishment
                assert host_0.get_id() in pubsubs_gsub_1[0].peers, (
                    "Reconnection not established for gossipsub 0"
                )

            except Exception as e:
                print(f"Test failed with error: {e}")
                raise
