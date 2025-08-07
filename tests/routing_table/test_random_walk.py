"""
Basic tests for the Random Walk module.
"""

import secrets
import pytest
from contextlib import asynccontextmanager
from typing import List

from libp2p.routing_table.random_walk import RandomWalk
from libp2p.routing_table.exceptions import RandomWalkError
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


class MockHost:
    """Mock host for testing."""
    
    def __init__(self):
        self.connections = {}
    
    async def connect(self, peer_info: PeerInfo):
        """Mock connect that always succeeds."""
        pass


def test_random_peer_id_generation():
    """Test that random peer ID generation works correctly."""
    # Create a mock host and random walk instance
    mock_host = MockHost()
    local_peer_id = ID(b"test_peer_id")
    
    @asynccontextmanager
    async def mock_query_function(target_key: str):
        yield []
    
    random_walk = RandomWalk(
        host=mock_host,
        local_peer_id=local_peer_id,
        query_function=mock_query_function
    )
    
    # Generate multiple random peer IDs
    peer_ids = [random_walk.generate_random_peer_id() for _ in range(10)]
    
    # Check that all IDs are different
    assert len(set(peer_ids)) == 10, "All generated peer IDs should be unique"
    
    # Check that each ID is 64 characters (32 bytes in hex)
    for peer_id in peer_ids:
        assert len(peer_id) == 64, f"Peer ID should be 64 chars, got {len(peer_id)}"
        # Check that it's valid hex
        bytes.fromhex(peer_id)


if __name__ == "__main__":
    # Run the basic test
    test_random_peer_id_generation()
    print("✓ Random peer ID generation test passed!")
