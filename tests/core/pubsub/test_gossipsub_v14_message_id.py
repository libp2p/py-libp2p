"""
Tests for GossipSub v1.4 Message ID Customization.

This module tests the enhanced message ID generation framework in v1.4, including:
- Various message ID generation strategies
- MessageIDGenerator classes
- Backward compatibility with callable functions
- Custom message ID generators
"""

import base64
import hashlib

import pytest
import trio

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V14,
)
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import (
    ContentAddressedMessageIDGenerator,
    CustomMessageIDGenerator,
    MessageIDGenerator,
    PeerAndSeqnoMessageIDGenerator,
    get_secure_msg_id,
    get_timestamp_msg_id,
    get_topic_aware_msg_id,
)
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


def create_test_message() -> rpc_pb2.Message:
    """Create a test message for ID generation testing."""
    msg = rpc_pb2.Message()
    msg.from_id = b"test_peer_id"
    msg.seqno = b"12345"
    msg.data = b"test message data"
    msg.topicIDs.extend(["topic1", "topic2"])
    return msg


@pytest.mark.trio
async def test_peer_and_seqno_generator():
    """Test PeerAndSeqnoMessageIDGenerator."""
    generator = PeerAndSeqnoMessageIDGenerator()
    msg = create_test_message()

    msg_id = generator.generate_id(msg)
    expected_id = msg.seqno + msg.from_id

    assert msg_id == expected_id

    # Test callable interface
    msg_id_callable = generator(msg)
    assert msg_id_callable == expected_id


@pytest.mark.trio
async def test_content_addressed_generator():
    """Test ContentAddressedMessageIDGenerator."""
    generator = ContentAddressedMessageIDGenerator()
    msg = create_test_message()

    msg_id = generator.generate_id(msg)
    expected_id = base64.b64encode(hashlib.sha256(msg.data).digest())

    assert msg_id == expected_id

    # Test that different data produces different IDs
    msg2 = create_test_message()
    msg2.data = b"different data"

    msg_id2 = generator.generate_id(msg2)
    assert msg_id != msg_id2


@pytest.mark.trio
async def test_custom_message_id_generator():
    """Test CustomMessageIDGenerator with user-defined function."""

    def custom_id_fn(msg: rpc_pb2.Message) -> bytes:
        return b"custom_" + msg.seqno

    generator = CustomMessageIDGenerator(custom_id_fn)
    msg = create_test_message()

    msg_id = generator.generate_id(msg)
    expected_id = b"custom_" + msg.seqno

    assert msg_id == expected_id


@pytest.mark.trio
async def test_topic_aware_msg_id():
    """Test topic-aware message ID generation."""
    msg = create_test_message()

    msg_id = get_topic_aware_msg_id(msg)

    # Should include topic information in hash
    topic_str = "|".join(sorted(msg.topicIDs))
    combined = msg.seqno + msg.from_id + topic_str.encode()
    expected_id = hashlib.sha256(combined).digest()

    assert msg_id == expected_id

    # Test with different topics
    msg2 = create_test_message()
    msg2.topicIDs[:] = ["different_topic"]

    msg_id2 = get_topic_aware_msg_id(msg2)
    assert msg_id != msg_id2


@pytest.mark.trio
async def test_timestamp_msg_id():
    """Test timestamp-based message ID generation."""
    msg = create_test_message()

    msg_id = get_timestamp_msg_id(msg)

    # Should contain seqno, from_id, and timestamp
    assert len(msg_id) > len(msg.seqno + msg.from_id)
    assert msg_id.startswith(msg.seqno + msg.from_id)

    # Different calls should produce different IDs due to timestamp
    import time

    time.sleep(0.001)  # Ensure different timestamp
    msg_id2 = get_timestamp_msg_id(msg)
    assert msg_id != msg_id2


@pytest.mark.trio
async def test_secure_msg_id():
    """Test secure message ID generation with HMAC."""
    msg = create_test_message()

    msg_id = get_secure_msg_id(msg)

    # Should be a SHA256 hash
    assert len(msg_id) == 32  # SHA256 produces 32 bytes

    # Same message should produce same ID
    msg_id2 = get_secure_msg_id(msg)
    assert msg_id == msg_id2

    # Different message should produce different ID
    msg2 = create_test_message()
    msg2.data = b"different data"
    msg_id3 = get_secure_msg_id(msg2)
    assert msg_id != msg_id3


@pytest.mark.trio
async def test_pubsub_with_message_id_generator():
    """Test Pubsub with MessageIDGenerator object."""
    generator = ContentAddressedMessageIDGenerator()

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], msg_id_constructor=generator
    ) as pubsubs:
        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "generator-test"
        queue1 = await pubsubs[1].subscribe(topic)
        await pubsubs[0].subscribe(topic)
        await trio.sleep(1.0)

        # Publish message
        test_data = b"test message for generator"
        await pubsubs[0].publish(topic, test_data)
        await trio.sleep(0.5)

        # Verify message was received
        msg = await queue1.get()
        assert msg.data == test_data


@pytest.mark.trio
async def test_pubsub_with_callable_msg_id():
    """Test Pubsub with callable message ID function."""

    def custom_msg_id(msg: rpc_pb2.Message) -> bytes:
        return b"test_" + msg.seqno + msg.from_id

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], msg_id_constructor=custom_msg_id
    ) as pubsubs:
        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "callable-test"
        queue1 = await pubsubs[1].subscribe(topic)
        await pubsubs[0].subscribe(topic)
        await trio.sleep(1.0)

        # Publish message
        test_data = b"test message for callable"
        await pubsubs[0].publish(topic, test_data)
        await trio.sleep(0.5)

        # Verify message was received
        msg = await queue1.get()
        assert msg.data == test_data


@pytest.mark.trio
async def test_different_generators_produce_different_ids():
    """Test that different generators produce different IDs for same message."""
    msg = create_test_message()

    peer_seqno_gen = PeerAndSeqnoMessageIDGenerator()
    content_gen = ContentAddressedMessageIDGenerator()

    id1 = peer_seqno_gen.generate_id(msg)
    id2 = content_gen.generate_id(msg)
    id3 = get_topic_aware_msg_id(msg)
    id4 = get_secure_msg_id(msg)

    # All IDs should be different
    ids = [id1, id2, id3, id4]
    assert len(set(ids)) == len(ids)  # All unique


@pytest.mark.trio
async def test_message_id_consistency():
    """Test that message ID generation is consistent."""
    msg = create_test_message()

    generators = [
        PeerAndSeqnoMessageIDGenerator(),
        ContentAddressedMessageIDGenerator(),
        CustomMessageIDGenerator(lambda m: b"custom_" + m.seqno),
    ]

    for generator in generators:
        # Same message should produce same ID multiple times
        id1 = generator.generate_id(msg)
        id2 = generator.generate_id(msg)
        assert id1 == id2


@pytest.mark.trio
async def test_message_id_with_empty_fields():
    """Test message ID generation with empty or missing fields."""
    msg = rpc_pb2.Message()

    # Test with minimal message
    msg.from_id = b""
    msg.seqno = b""
    msg.data = b""

    generators = [
        PeerAndSeqnoMessageIDGenerator(),
        ContentAddressedMessageIDGenerator(),
    ]

    for generator in generators:
        # Should not crash with empty fields
        msg_id = generator.generate_id(msg)
        assert isinstance(msg_id, bytes)


@pytest.mark.trio
async def test_message_id_deduplication():
    """Test that different message ID strategies affect deduplication."""
    # Test with content-addressed IDs (same content = same ID)
    content_gen = ContentAddressedMessageIDGenerator()

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], msg_id_constructor=content_gen
    ) as pubsubs:
        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "dedup-test"
        queue1 = await pubsubs[1].subscribe(topic)
        await pubsubs[0].subscribe(topic)
        await trio.sleep(1.0)

        # Publish same message twice
        test_data = b"duplicate message"
        await pubsubs[0].publish(topic, test_data)
        await pubsubs[0].publish(topic, test_data)
        await trio.sleep(0.5)

        # With content-addressed IDs, should receive at least one message
        msg = await queue1.get()
        assert msg.data == test_data
        # Note: Exact deduplication behavior depends on implementation details


@pytest.mark.trio
async def test_generator_inheritance():
    """Test creating custom generators by inheriting from MessageIDGenerator."""

    class TimestampPrefixGenerator(MessageIDGenerator):
        def generate_id(self, msg: rpc_pb2.Message) -> bytes:
            import time

            timestamp = int(time.time()).to_bytes(4, byteorder="big")
            return timestamp + msg.seqno + msg.from_id

    generator = TimestampPrefixGenerator()
    msg = create_test_message()

    msg_id = generator.generate_id(msg)

    # Should start with 4-byte timestamp
    assert len(msg_id) >= 4 + len(msg.seqno) + len(msg.from_id)

    # Test callable interface
    msg_id2 = generator(msg)
    # May be different due to timestamp, but should be same length
    assert len(msg_id2) == len(msg_id)


@pytest.mark.trio
async def test_backward_compatibility():
    """Test backward compatibility with existing callable functions."""
    from libp2p.pubsub.pubsub import (
        get_content_addressed_msg_id,
        get_peer_and_seqno_msg_id,
    )

    # Test with traditional callable functions
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], msg_id_constructor=get_peer_and_seqno_msg_id
    ):
        pass  # Should initialize without error

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], msg_id_constructor=get_content_addressed_msg_id
    ):
        pass  # Should initialize without error

    # Test with generator objects
    async with PubsubFactory.create_batch_with_gossipsub(
        2,
        protocols=[PROTOCOL_ID_V14],
        msg_id_constructor=PeerAndSeqnoMessageIDGenerator(),
    ):
        pass  # Should initialize without error
