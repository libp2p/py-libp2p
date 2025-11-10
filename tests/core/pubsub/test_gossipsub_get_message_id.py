import pytest

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V12,
    GossipSub,
)
from libp2p.pubsub.pb import rpc_pb2
from tests.utils.factories import (
    PubsubFactory,
)


@pytest.mark.trio
async def test_gossipsub_get_message_id():
    """Test that GossipSub correctly uses the public get_message_id method."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V12]
    ) as pubsubs_gsub:
        pubsub = pubsubs_gsub[0]
        router = pubsub.router
        assert isinstance(router, GossipSub)

        # Create a test message
        test_data = b"test_message_data"
        test_from = pubsub.my_id.to_bytes()
        test_seqno = b"\x00\x00\x00\x00\x00\x00\x00\x01"

        msg = rpc_pb2.Message(
            from_id=test_from,
            data=test_data,
            seqno=test_seqno,
            topicIDs=["test_topic"],
        )

        # Get message ID using the public method
        msg_id = pubsub.get_message_id(msg)

        # Verify it's the expected format (depends on the message ID constructor)
        # For the default constructor, it should be seqno + from_id
        expected_id = test_seqno + test_from
        assert msg_id == expected_id


@pytest.mark.trio
async def test_gossipsub_idontwant_with_message_id():
    """Test that IDONTWANT messages use the public get_message_id method."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V12]
    ) as pubsubs_gsub:
        pubsub0 = pubsubs_gsub[0]
        pubsub1 = pubsubs_gsub[1]
        router0 = pubsub0.router

        assert isinstance(router0, GossipSub)

        # Create a test message
        test_data = b"test_message_data"
        test_from = pubsub0.my_id.to_bytes()
        test_seqno = b"\x00\x00\x00\x00\x00\x00\x00\x01"

        msg = rpc_pb2.Message(
            from_id=test_from,
            data=test_data,
            seqno=test_seqno,
            topicIDs=["test_topic"],
        )

        # Get message ID using the public method
        msg_id = pubsub0.get_message_id(msg)

        # Add the message ID to the don't send list for peer1
        peer1_id = pubsub1.host.get_id()
        router0.dont_send_message_ids[peer1_id] = {msg_id}

        # Verify the message won't be sent to peer1
        # Create dummy peer IDs for the test
        dummy_peer_id = pubsub0.host.get_id()
        peers_to_send = list(
            router0._get_peers_to_send(
                ["test_topic"], dummy_peer_id, dummy_peer_id, msg_id
            )
        )

        assert peer1_id not in peers_to_send


@pytest.mark.trio
async def test_custom_message_id_with_gossipsub():
    """Test that GossipSub works with a custom message ID constructor."""

    # Define a custom message ID constructor
    def custom_msg_id_constructor(msg):
        return msg.data + msg.seqno

    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V12], msg_id_constructor=custom_msg_id_constructor
    ) as pubsubs_gsub:
        pubsub = pubsubs_gsub[0]
        router = pubsub.router
        assert isinstance(router, GossipSub)

        # Create a test message
        test_data = b"test_message_data"
        test_from = pubsub.my_id.to_bytes()
        test_seqno = b"\x00\x00\x00\x00\x00\x00\x00\x01"

        msg = rpc_pb2.Message(
            from_id=test_from,
            data=test_data,
            seqno=test_seqno,
            topicIDs=["test_topic"],
        )

        # Get message ID using the public method
        msg_id = pubsub.get_message_id(msg)

        # Verify it's using our custom constructor
        expected_id = test_data + test_seqno
        assert msg_id == expected_id
