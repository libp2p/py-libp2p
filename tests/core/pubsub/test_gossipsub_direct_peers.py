import logging

import pytest

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
from tests.utils.pubsub.wait import (
    wait_for,
)

logger = logging.getLogger(__name__)


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

            # Wait for direct-connect heartbeat to establish the pubsub peer
            await pubsubs_gsub_1[0].wait_for_peer(host_0.get_id(), timeout=10)

            try:
                # Verify that peer records exist in peer store
                peer_store_0 = host_0.get_peerstore()
                peer_store_1 = host_1.get_peerstore()

                # Check that each host has the other's peer record
                peer_ids_0 = peer_store_0.peer_ids()
                peer_ids_1 = peer_store_1.peer_ids()

                logger.debug("Peer store 0 IDs: %s", peer_ids_0)
                logger.debug("Peer store 1 IDs: %s", peer_ids_1)
                logger.debug("Host 0 ID: %s", host_0.get_id())
                logger.debug("Host 1 ID: %s", host_1.get_id())

                assert host_0.get_id() in peer_ids_1, "Peer 0 not found in peer store 1"

            except Exception as e:
                logger.error("Test failed with error: %s", e)
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

                # Wait for pubsub streams to be established
                await pubsubs_gsub_0[0].wait_for_peer(host_1.get_id(), timeout=10)
                await pubsubs_gsub_1[0].wait_for_peer(host_0.get_id(), timeout=10)

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

                # Gossipsub 0 emits a graft request to Gossipsub 1 (direct peer of 1)
                router_obj = pubsubs_gsub_0[0].router
                assert isinstance(router_obj, GossipSub)
                await router_obj.emit_graft(topic, host_1.get_id())

                # Wait until PRUNE from the direct-peer reject is handled (backoff set)
                def _prune_backoff_recorded() -> bool:
                    assert isinstance(router_obj, GossipSub)
                    return host_1.get_id() in router_obj.back_off.get(topic, {})

                await wait_for(
                    _prune_backoff_recorded,
                    timeout=10,
                    fail_msg=(
                        "PRUNE backoff not recorded after direct-peer GRAFT reject"
                    ),
                )

                # Post-Graft assertions
                assert host_1.get_id() not in pubsubs_gsub_0[0].router.mesh[topic], (
                    "gossipsub 1 in mesh topic for gossipsub 0"
                )
                assert host_0.get_id() not in pubsubs_gsub_1[0].router.mesh[topic], (
                    "gossipsub 0 in mesh topic for gossipsub 1"
                )

            except Exception as e:
                logger.error("Test failed with error: %s", e)
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
                # Wait for initial pubsub peer streams
                await pubsubs_gsub_0[0].wait_for_peer(host_1.get_id(), timeout=10)
                await pubsubs_gsub_1[0].wait_for_peer(host_0.get_id(), timeout=10)

                # Verify initial connection
                assert host_1.get_id() in pubsubs_gsub_0[0].peers, (
                    "Initial connection not established for gossipsub 0"
                )
                assert host_0.get_id() in pubsubs_gsub_1[0].peers, (
                    "Initial connection not established for gossipsub 1"
                )

                # Simulate disconnection
                await host_0.disconnect(host_1.get_id())

                # Wait for disconnect to remove the peer from pubsub
                await wait_for(
                    lambda: host_0.get_id() not in pubsubs_gsub_1[0].peers,
                    timeout=10,
                    fail_msg="Peer 0 still in gossipsub 1 after disconnection",
                )

                # Wait for direct-connect heartbeat to reestablish connection
                await pubsubs_gsub_1[0].wait_for_peer(host_0.get_id(), timeout=15)

                # Verify connection reestablishment
                assert host_0.get_id() in pubsubs_gsub_1[0].peers, (
                    "Reconnection not established for gossipsub 0"
                )

            except Exception as e:
                logger.error("Test failed with error: %s", e)
                raise
