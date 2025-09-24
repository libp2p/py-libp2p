import pytest
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from libp2p.identity.identify_push.identify_push import (
    _update_peerstore_from_identify,
    push_identify_to_peer,
    push_identify_to_peers,
)
from libp2p.host.exceptions import (
    HostException,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from tests.utils.factories import (
    host_pair_factory,
)
from tests.utils.utils import (
    run_host_forever,
    wait_until_listening,
)


@pytest.mark.trio
async def test_push_identify_to_peer_exception_handling():
    """Test that push_identify_to_peer properly handles exceptions."""
    key_pair = create_new_key_pair()
    
    async with host_pair_factory() as (host_a, host_b):
        # Connect the hosts
        peer_info = PeerInfo(host_b.get_id(), host_b.get_addrs())
        await host_a.connect(peer_info)
        
        # Mock new_stream to raise an exception
        original_new_stream = host_a.new_stream
        
        async def mock_new_stream(*args, **kwargs):
            raise RuntimeError("Mock stream creation error")
        
        host_a.new_stream = mock_new_stream
        
        # Test that push_identify_to_peer raises HostException
        with pytest.raises(HostException, match="Failed to push identify to peer"):
            await push_identify_to_peer(host_a, host_b.get_id())
        
        # Restore original method
        host_a.new_stream = original_new_stream


@pytest.mark.trio
async def test_push_identify_to_peer_preserves_exception_chain():
    """Test that push_identify_to_peer preserves the original exception chain."""
    key_pair = create_new_key_pair()
    
    async with host_pair_factory() as (host_a, host_b):
        # Connect the hosts
        peer_info = PeerInfo(host_b.get_id(), host_b.get_addrs())
        await host_a.connect(peer_info)
        
        original_error = ConnectionError("Original connection error")
        
        # Mock new_stream to raise a specific exception
        async def mock_new_stream(*args, **kwargs):
            raise original_error
        
        host_a.new_stream = mock_new_stream
        
        # Test that the original exception is preserved in the chain
        with pytest.raises(HostException) as exc_info:
            await push_identify_to_peer(host_a, host_b.get_id())
        
        # Check that the original exception is preserved in the chain
        assert exc_info.value.__cause__ is original_error
        assert "Failed to push identify to peer" in str(exc_info.value)


@pytest.mark.trio
async def test_update_peerstore_from_identify_exception_handling():
    """Test that _update_peerstore_from_identify handles exceptions gracefully."""
    key_pair = create_new_key_pair()
    
    async with host_pair_factory() as (host_a, host_b):
        # Create a mock peerstore that raises exceptions
        class MockPeerstore:
            def add_protocols(self, peer_id, protocols):
                raise ValueError("Mock protocol error")
            
            def add_pubkey(self, peer_id, pubkey):
                raise KeyError("Mock pubkey error")
            
            def add_addr(self, peer_id, addr, ttl):
                raise RuntimeError("Mock addr error")
            
            def consume_peer_record(self, envelope, ttl):
                raise ConnectionError("Mock record error")
        
        mock_peerstore = MockPeerstore()
        
        # Create an identify message with various fields
        identify_msg = Identify()
        identify_msg.public_key = b"mock_public_key"
        identify_msg.listen_addrs.extend([b"/ip4/127.0.0.1/tcp/4001"])
        identify_msg.protocols.extend(["/test/protocol/1.0.0"])
        identify_msg.observed_addr = b"/ip4/127.0.0.1/tcp/4002"
        identify_msg.signedPeerRecord = b"mock_signed_record"
        
        # Test that the function handles exceptions gracefully
        # It should not raise any exceptions, just log errors
        await _update_peerstore_from_identify(mock_peerstore, host_b.get_id(), identify_msg)
        
        # If we get here without exceptions, the test passes


@pytest.mark.trio
async def test_push_identify_to_peers_exception_handling():
    """Test that push_identify_to_peers handles exceptions gracefully."""
    key_pair = create_new_key_pair()
    
    async with host_pair_factory() as (host_a, host_b):
        # Connect the hosts
        peer_info = PeerInfo(host_b.get_id(), host_b.get_addrs())
        await host_a.connect(peer_info)
        
        # Mock new_stream to raise an exception for one peer
        original_new_stream = host_a.new_stream
        
        async def mock_new_stream(*args, **kwargs):
            raise ConnectionError("Mock connection error")
        
        host_a.new_stream = mock_new_stream
        
        # Test that push_identify_to_peers handles exceptions gracefully
        # It should not raise any exceptions, just log errors
        await push_identify_to_peers(host_a, {host_b.get_id()})
        
        # Restore original method
        host_a.new_stream = original_new_stream
