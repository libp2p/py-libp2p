"""
Tests for GossipSub v1.4 Extensions Framework.

This module tests the extensions control message framework introduced in v1.3
and enhanced in v1.4, including:
- Extension registration and handling
- Extension message emission and reception
- Error handling and validation
"""

import pytest
import trio

from libp2p.peer.id import ID
from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V13,
    PROTOCOL_ID_V14,
    GossipSub,
)
from libp2p.pubsub.pb import rpc_pb2
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_extension_registration():
    """Test extension handler registration and unregistration."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Test registration
        async def test_handler(data: bytes, sender_peer_id: ID):
            pass

        router.register_extension_handler("test-extension", test_handler)
        assert "test-extension" in router.extension_handlers
        assert router.extension_handlers["test-extension"] == test_handler

        # Test unregistration
        router.unregister_extension_handler("test-extension")
        assert "test-extension" not in router.extension_handlers

        # Test unregistering non-existent extension (should not raise)
        router.unregister_extension_handler("non-existent")


@pytest.mark.trio
async def test_extension_message_handling():
    """
    Test extension handler registration and that emit_extension completes.

    In GossipSub v1.3 wire format, extension data is only sent in the first
    hello (control.extensions); there is no wire format for arbitrary
    extension name/data. So emit_extension is a no-op and handlers are not
    invoked for custom data. This test verifies registration and that
    emit_extension completes without raising.
    """
    received_extensions = []

    async def extension_handler(data: bytes, sender_peer_id: ID):
        received_extensions.append((data, sender_peer_id))

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router0 = pubsubs[0].router
        router1 = pubsubs[1].router
        assert isinstance(router0, GossipSub)
        assert isinstance(router1, GossipSub)

        # Register extension handler on router1
        router1.register_extension_handler("test-ext", extension_handler)

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Get peer IDs
        peer1_id = pubsubs[1].host.get_id()

        # emit_extension is a no-op (v1.3 does not send arbitrary extension
        # name/data); it should complete without raising.
        test_data = b"test extension data"
        await router0.emit_extension("test-ext", test_data, peer1_id)

        # Wait for message processing
        await trio.sleep(0.5)

        # No extension data is delivered over the wire (only hello carries
        # control.extensions), so the handler is never called.
        assert len(received_extensions) == 0


@pytest.mark.trio
async def test_extension_message_to_unsupported_peer():
    """Test sending extension message to peer that doesn't support extensions."""
    from libp2p.pubsub.gossipsub import PROTOCOL_ID_V11

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14, PROTOCOL_ID_V11]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Connect peers (one v1.4, one v1.1)
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Try to send extension to v1.1 peer (should be ignored)
        peer1_id = pubsubs[1].host.get_id()

        # This should not raise an error, but should log a warning
        await router.emit_extension("test-ext", b"data", peer1_id)


@pytest.mark.trio
async def test_extension_handler_error_handling():
    """
    Test that emit_extension completes when a failing handler is registered.

    emit_extension is a no-op (v1.3 does not send arbitrary extension data),
    so the handler is never invoked. We verify emit_extension does not raise
    and the handler is not called.
    """
    error_count = [0]  # Use list to make it mutable

    async def failing_handler(data: bytes, sender_peer_id: ID):
        error_count[0] += 1
        raise ValueError("Handler error")

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router0 = pubsubs[0].router
        router1 = pubsubs[1].router
        assert isinstance(router0, GossipSub)
        assert isinstance(router1, GossipSub)

        # Register failing handler
        router1.register_extension_handler("failing-ext", failing_handler)

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # emit_extension is a no-op; should complete without raising
        peer1_id = pubsubs[1].host.get_id()
        await router0.emit_extension("failing-ext", b"data", peer1_id)

        # Wait for processing
        await trio.sleep(0.5)

        # Handler is never called (no extension data is sent over the wire)
        assert error_count[0] == 0


@pytest.mark.trio
async def test_unregistered_extension_handling():
    """Test handling of unregistered extensions."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router0 = pubsubs[0].router
        router1 = pubsubs[1].router
        assert isinstance(router0, GossipSub)
        assert isinstance(router1, GossipSub)

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Send extension message for unregistered extension
        peer1_id = pubsubs[1].host.get_id()

        # This should not raise an error, just log a debug message
        await router0.emit_extension("unregistered-ext", b"data", peer1_id)
        await trio.sleep(0.5)


@pytest.mark.trio
async def test_extension_message_from_unsupported_peer():
    """Extension data from a v1.1 peer is not processed; only v1.3+ are handled."""
    from libp2p.pubsub.gossipsub import PROTOCOL_ID_V11

    # Create one v1.4 peer and one v1.1 peer
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as v14_pubsubs:
        async with PubsubFactory.create_batch_with_gossipsub(
            1, protocols=[PROTOCOL_ID_V11]
        ) as v11_pubsubs:
            v14_router = v14_pubsubs[0].router
            assert isinstance(v14_router, GossipSub)

            await connect(v14_pubsubs[0].host, v11_pubsubs[0].host)
            await trio.sleep(0.5)

            # Simulate v1.1 peer: router thinks this peer speaks v1.1 only
            v11_peer_id = v11_pubsubs[0].host.get_id()
            v14_router.peer_protocol[v11_peer_id] = PROTOCOL_ID_V11

            assert not v14_router.supports_protocol_feature(v11_peer_id, "extensions")

            # Build an RPC that would carry control.extensions (as a v1.3 peer would)
            rpc = rpc_pb2.RPC()
            rpc.control.CopyFrom(rpc_pb2.ControlMessage())
            rpc.control.extensions.CopyFrom(
                rpc_pb2.ControlExtensions(topicObservation=True)
            )

            # handle_rpc must not process extensions for v1.1 peers
            await v14_router.handle_rpc(rpc, v11_peer_id)

            # v1.1 peer's extensions must not be recorded (we skip extensions_state
            # when sender does not support v1.3+)
            assert v14_router.extensions_state.get_peer_extensions(v11_peer_id) is None


@pytest.mark.trio
async def test_multiple_extension_handlers():
    """
    Test multiple extension handlers registered and emit_extension completes.

    emit_extension is a no-op (v1.3 does not send arbitrary extension data),
    so handlers are never invoked. We verify both handlers can be registered
    and emit_extension for each completes without raising.
    """
    received_messages = []

    async def handler1(data: bytes, sender_peer_id: ID):
        received_messages.append(("handler1", data))

    async def handler2(data: bytes, sender_peer_id: ID):
        received_messages.append(("handler2", data))

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router0 = pubsubs[0].router
        router1 = pubsubs[1].router
        assert isinstance(router0, GossipSub)
        assert isinstance(router1, GossipSub)

        # Register multiple handlers
        router1.register_extension_handler("ext1", handler1)
        router1.register_extension_handler("ext2", handler2)

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # emit_extension is a no-op for both; should complete without raising
        peer1_id = pubsubs[1].host.get_id()
        await router0.emit_extension("ext1", b"data1", peer1_id)
        await router0.emit_extension("ext2", b"data2", peer1_id)

        # Wait for processing
        await trio.sleep(0.5)

        # No extension data is delivered, so neither handler is called
        assert len(received_messages) == 0


@pytest.mark.trio
async def test_extension_v13_compatibility():
    """
    Test extension registration and emit_extension with v1.3 protocol.

    Same as v1.4: emit_extension is a no-op (v1.3 wire format only sends
    extensions in the first hello). We verify registration and that
    emit_extension completes without raising.
    """
    received_extensions = []

    async def extension_handler(data: bytes, sender_peer_id: ID):
        received_extensions.append((data, sender_peer_id))

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V13]
    ) as pubsubs:
        router0 = pubsubs[0].router
        router1 = pubsubs[1].router
        assert isinstance(router0, GossipSub)
        assert isinstance(router1, GossipSub)

        # Register extension handler
        router1.register_extension_handler("v13-ext", extension_handler)

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # emit_extension is a no-op; should complete without raising
        peer1_id = pubsubs[1].host.get_id()
        test_data = b"v1.3 extension data"
        await router0.emit_extension("v13-ext", test_data, peer1_id)

        # Wait for processing
        await trio.sleep(0.5)

        # No extension data is delivered over the wire
        assert len(received_extensions) == 0
