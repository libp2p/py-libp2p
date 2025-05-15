"""
Tests for the Kademlia DHT implementation.

This module tests core functionality of the Kademlia DHT including:
- Node discovery (find_node)
- Value storage and retrieval (put_value, get_value)
- Content provider advertisement and discovery (provide, find_providers)
"""

import os
import hashlib
import uuid
import secrets
import logging
from typing import List, Tuple, cast

import pytest
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import KadDHT
from libp2p.kad_dht.utils import create_key_from_binary
from libp2p.peer.peerinfo import PeerInfo
from libp2p.tools.async_service import background_trio_service
from multiaddr import Multiaddr
from tests.utils.factories import host_pair_factory

# Configure logger
logger = logging.getLogger("test.kad_dht")

# Constants for the tests
TEST_TIMEOUT = 5  # Timeout in seconds

@pytest.fixture
async def dht_pair(security_protocol) -> Tuple[KadDHT, KadDHT]:
    """Create a pair of connected DHT nodes for testing."""
    async with host_pair_factory(security_protocol=security_protocol) as (host_a, host_b):
        # Get peer info for bootstrapping
        peer_b_info = PeerInfo(host_b.get_id(), host_b.get_addrs())
        peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())
        
        # Create DHT nodes from the hosts with bootstrap peers
        dht_a: KadDHT = KadDHT(host_a, bootstrap_peers=[peer_b_info])
        dht_b: KadDHT = KadDHT(host_b, bootstrap_peers=[peer_a_info])
        
        # Start both DHT services
        async with background_trio_service(dht_a), background_trio_service(dht_b):
            # Allow time for services to fully start and bootstrap
            await trio.sleep(0.1)
            
            # Explicitly add each node to the other's routing table to ensure connection
            # Use await since add_peer is a coroutine
            await dht_a.routing_table.add_peer(peer_b_info.peer_id)
            await dht_b.routing_table.add_peer(peer_a_info.peer_id)
            
            logger.debug("After bootstrap: Node A peers: %s", dht_a.routing_table.get_peer_ids())
            logger.debug("After bootstrap: Node B peers: %s", dht_b.routing_table.get_peer_ids())
            
            # Return the DHT pair
            yield (dht_a, dht_b)

@pytest.mark.trio
async def test_find_node(dht_pair: Tuple[KadDHT, KadDHT]):
    """Test that nodes can find each other in the DHT."""
    dht_a, dht_b = dht_pair
    
    # Node A should be able to find Node B
    with trio.fail_after(TEST_TIMEOUT):
        found_info = await dht_a.find_peer(dht_b.host.get_id())
    
    # Verify that the found peer has the correct peer ID
    assert found_info is not None, "Failed to find the target peer"
    assert found_info.peer_id == dht_b.host.get_id(), "Found incorrect peer ID"

@pytest.mark.trio
async def test_put_and_get_value(dht_pair: Tuple[KadDHT, KadDHT]):
    """Test storing and retrieving values in the DHT."""
    dht_a, dht_b = dht_pair
    
    # Generate a random key and value
    key = create_key_from_binary(os.urandom(32))
    value = f"test-value-{uuid.uuid4()}".encode()
    
    # First add the value directly to node A's store to verify storage works
    dht_a.value_store.put(key, value)
    local_value = dht_a.value_store.get(key)
    assert local_value == value, "Local value storage failed"
    
    # Store the value using the first node (this will also store locally)
    with trio.fail_after(TEST_TIMEOUT):
        await dht_a.put_value(key, value)
    
    # Log debugging information
    logger.debug("Put value with key %s...", key.hex()[:10])
    logger.debug("Node A value store: %s", dht_a.value_store.store)
    
    # Allow more time for the value to propagate
    await trio.sleep(0.1)
    
    # Try direct connection between nodes to ensure they're properly linked
    logger.debug("Node A peers: %s", dht_a.routing_table.get_peer_ids())
    logger.debug("Node B peers: %s", dht_b.routing_table.get_peer_ids())
    
    # Retrieve the value using the second node
    with trio.fail_after(TEST_TIMEOUT):
        retrieved_value = await dht_b.get_value(key)
        logger.debug("Retrieved value: %s", retrieved_value)
    
    # Verify that the retrieved value matches the original
    assert retrieved_value == value, "Retrieved value does not match the stored value"

@pytest.mark.trio
async def test_provide_and_find_providers(dht_pair: Tuple[KadDHT, KadDHT]):
    """Test advertising and finding content providers."""
    dht_a, dht_b = dht_pair
    
    # Generate a random content ID
    content = f"test-content-{uuid.uuid4()}".encode()
    content_id = hashlib.sha256(content).digest()
    
    # Store content on the first node
    dht_a.value_store.put(content_id, content)
    
    # Advertise the first node as a provider
    with trio.fail_after(TEST_TIMEOUT):
        success = await dht_a.provider_store.provide(content_id)
        assert success, "Failed to advertise as provider"
    
    # Allow time for the provider record to propagate
    await trio.sleep(0.1)
    
    # Find providers using the second node
    with trio.fail_after(TEST_TIMEOUT):
        providers = await dht_b.provider_store.find_providers(content_id)
    
    # Verify that we found the first node as a provider
    assert providers, "No providers found"
    assert any(p.peer_id == dht_a.local_peer_id for p in providers), "Expected provider not found"
    
    # Retrieve the content using the provider information
    with trio.fail_after(TEST_TIMEOUT):
        retrieved_value = await dht_b.get_value(content_id)
        assert retrieved_value == content, "Retrieved content does not match the original"