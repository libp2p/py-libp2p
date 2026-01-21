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
    """Test extension message handling between peers."""
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
        
        # Send extension message from router0 to router1
        test_data = b"test extension data"
        await router0.emit_extension("test-ext", test_data, peer1_id)
        
        # Wait for message processing
        await trio.sleep(0.5)
        
        # Verify extension was received and handled
        assert len(received_extensions) == 1
        assert received_extensions[0][0] == test_data
        assert received_extensions[0][1] == pubsubs[0].host.get_id()


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
    """Test error handling in extension handlers."""
    error_count = 0
    
    async def failing_handler(data: bytes, sender_peer_id: ID):
        nonlocal error_count
        error_count += 1
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
        
        # Send extension message
        peer1_id = pubsubs[1].host.get_id()
        await router0.emit_extension("failing-ext", b"data", peer1_id)
        
        # Wait for processing
        await trio.sleep(0.5)
        
        # Verify handler was called but error was caught
        assert error_count == 1


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
    """Test receiving extension message from peer that doesn't support extensions."""
    from libp2p.pubsub.gossipsub import PROTOCOL_ID_V11
    
    received_count = 0
    
    async def handler(data: bytes, sender_peer_id: ID):
        nonlocal received_count
        received_count += 1
    
    # Create one v1.4 peer and one v1.1 peer
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as v14_pubsubs:
        async with PubsubFactory.create_batch_with_gossipsub(
            1, protocols=[PROTOCOL_ID_V11]
        ) as v11_pubsubs:
            v14_router = v14_pubsubs[0].router
            v11_router = v11_pubsubs[0].router
            assert isinstance(v14_router, GossipSub)
            assert isinstance(v11_router, GossipSub)
            
            # Register handler on v1.4 peer
            v14_router.register_extension_handler("test-ext", handler)
            
            # Connect peers
            await connect(v14_pubsubs[0].host, v11_pubsubs[0].host)
            await trio.sleep(0.5)
            
            # Manually set the peer protocol mapping to simulate v1.1 peer
            v11_peer_id = v11_pubsubs[0].host.get_id()
            v14_router.peer_protocol[v11_peer_id] = PROTOCOL_ID_V11
            
            # Verify the peer is recognized as not supporting extensions
            assert not v14_router.supports_protocol_feature(v11_peer_id, "extensions")
            
            # Create extension message from v1.1 peer
            extension_msg = rpc_pb2.ControlExtension()
            extension_msg.name = "test-ext"
            extension_msg.data = b"test data"
            
            # This should be ignored due to protocol version check
            await v14_router.handle_extension(extension_msg, v11_peer_id)
            await trio.sleep(0.5)
            
            # Handler should not have been called
            assert received_count == 0


@pytest.mark.trio
async def test_multiple_extension_handlers():
    """Test multiple extension handlers on the same router."""
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
        
        # Send messages to different extensions
        peer1_id = pubsubs[1].host.get_id()
        await router0.emit_extension("ext1", b"data1", peer1_id)
        await router0.emit_extension("ext2", b"data2", peer1_id)
        
        # Wait for processing
        await trio.sleep(0.5)
        
        # Verify both handlers were called
        assert len(received_messages) == 2
        assert ("handler1", b"data1") in received_messages
        assert ("handler2", b"data2") in received_messages


@pytest.mark.trio
async def test_extension_v13_compatibility():
    """Test extensions work with v1.3 protocol."""
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
        
        # Send extension message
        peer1_id = pubsubs[1].host.get_id()
        test_data = b"v1.3 extension data"
        await router0.emit_extension("v13-ext", test_data, peer1_id)
        
        # Wait for processing
        await trio.sleep(0.5)
        
        # Verify extension was handled
        assert len(received_extensions) == 1
        assert received_extensions[0][0] == test_data