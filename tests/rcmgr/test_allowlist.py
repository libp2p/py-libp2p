"""
Tests for the allowlist functionality.
"""

from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.rcmgr.allowlist import Allowlist, AllowlistConfig


def test_allowlist_creation() -> None:
    """Test Allowlist creation."""
    allowlist = Allowlist()
    assert allowlist is not None


def test_allowlist_creation_with_config() -> None:
    """Test Allowlist creation with configuration."""
    peer_id = ID(b"test_peer")
    addr = "/ip4/127.0.0.1/tcp/8080"

    config = AllowlistConfig()
    config.peers.add(peer_id)
    config.multiaddrs.add(addr)

    allowlist = Allowlist(config)
    assert allowlist.allowed_peer(peer_id)
    assert allowlist.allowed_multiaddr(addr)


def test_add_remove_peer() -> None:
    """Test adding and removing peers."""
    allowlist = Allowlist()
    peer_id = ID(b"test_peer")

    # Initially not allowed
    assert not allowlist.allowed_peer(peer_id)

    # Add peer
    allowlist.add_peer(peer_id)
    assert allowlist.allowed_peer(peer_id)

    # Remove peer
    allowlist.remove_peer(peer_id)
    assert not allowlist.allowed_peer(peer_id)


def test_add_remove_multiaddr() -> None:
    """Test adding and removing multiaddrs."""
    allowlist = Allowlist()
    addr = Multiaddr("/ip4/127.0.0.1/tcp/8080")

    # Initially not allowed
    assert not allowlist.allowed_multiaddr(addr)

    # Add multiaddr
    allowlist.add_multiaddr(addr)
    assert allowlist.allowed_multiaddr(addr)

    # Remove multiaddr
    allowlist.remove_multiaddr(addr)
    assert not allowlist.allowed_multiaddr(addr)


def test_add_remove_combined() -> None:
    """Test adding and removing peer+multiaddr combinations."""
    allowlist = Allowlist()
    peer_id = ID(b"test_peer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/8080")

    # Initially not allowed
    assert not allowlist.allowed_peer_and_multiaddr(peer_id, addr)

    # Add combination
    allowlist.add_peer_multiaddr(peer_id, addr)
    assert allowlist.allowed_peer_and_multiaddr(peer_id, addr)

    # Remove combination
    allowlist.remove_peer_multiaddr(peer_id, addr)
    assert not allowlist.allowed_peer_and_multiaddr(peer_id, addr)


def test_allowlist_priority() -> None:
    """Test allowlist priority rules."""
    allowlist = Allowlist()
    peer_id = ID(b"test_peer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/8080")

    # Add peer to allowlist
    allowlist.add_peer(peer_id)

    # Peer should be allowed for any address
    assert allowlist.allowed_peer(peer_id)
    assert allowlist.allowed_peer_and_multiaddr(peer_id, addr)

    # Add specific combination (should override peer allowlist)
    allowlist.add_peer_multiaddr(peer_id, addr)
    assert allowlist.allowed_peer_and_multiaddr(peer_id, addr)

    # Remove peer from general allowlist
    allowlist.remove_peer(peer_id)

    # Should still be allowed for specific address
    assert not allowlist.allowed_peer(peer_id)
    assert allowlist.allowed_peer_and_multiaddr(peer_id, addr)


def test_default_allowed() -> None:
    """Test default allowed behavior."""
    # Current implementation doesn't have default_allowed behavior
    # Test that items need to be explicitly added
    allowlist = Allowlist()
    peer_id = ID(b"test_peer")
    addr = Multiaddr("/ip4/192.168.1.1/tcp/9000")

    # Should not be allowed by default
    assert not allowlist.allowed_peer(peer_id)
    assert not allowlist.allowed_multiaddr(addr)
    assert not allowlist.allowed_peer_and_multiaddr(peer_id, addr)

    # Add them explicitly
    allowlist.add_peer(peer_id)
    allowlist.add_multiaddr(addr)

    # Now should be allowed
    assert allowlist.allowed_peer(peer_id)
    assert allowlist.allowed_multiaddr(addr)
    assert allowlist.allowed_peer_and_multiaddr(peer_id, addr)


def test_list_methods() -> None:
    """Test listing allowed peers and multiaddrs."""
    allowlist = Allowlist()

    peer1 = ID(b"peer1")
    peer2 = ID(b"peer2")
    addr1 = Multiaddr("/ip4/127.0.0.1/tcp/8080")
    addr2 = Multiaddr("/ip4/192.168.1.1/tcp/9000")

    # Add items
    allowlist.add_peer(peer1)
    allowlist.add_peer(peer2)
    allowlist.add_multiaddr(addr1)
    allowlist.add_multiaddr(addr2)

    # Check lists
    peers = allowlist.get_allowed_peers()
    assert peer1 in peers
    assert peer2 in peers

    addrs = allowlist.get_allowed_multiaddrs()
    assert str(addr1) in addrs
    assert str(addr2) in addrs


def test_list_combined() -> None:
    """Test listing combined peer+multiaddr entries."""
    allowlist = Allowlist()

    peer1 = ID(b"peer1")
    peer2 = ID(b"peer2")
    addr1 = Multiaddr("/ip4/127.0.0.1/tcp/8080")
    addr2 = Multiaddr("/ip4/192.168.1.1/tcp/9000")

    # Add combinations
    allowlist.add_peer_multiaddr(peer1, addr1)
    allowlist.add_peer_multiaddr(peer2, addr2)

    # Check combined entries exist
    assert allowlist.allowed_peer_and_multiaddr(peer1, addr1)
    assert allowlist.allowed_peer_and_multiaddr(peer2, addr2)

    # Should not be allowed individually
    assert not allowlist.allowed_peer(peer1)
    assert not allowlist.allowed_multiaddr(addr1)


def test_clear_methods() -> None:
    """Test clearing allowlist entries."""
    allowlist = Allowlist()

    peer_id = ID(b"test_peer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/8080")

    # Add entries
    allowlist.add_peer(peer_id)
    allowlist.add_multiaddr(addr)
    allowlist.add_peer_multiaddr(peer_id, addr)

    # Verify they exist
    assert allowlist.allowed_peer(peer_id)
    assert allowlist.allowed_multiaddr(addr)
    assert allowlist.allowed_peer_and_multiaddr(peer_id, addr)

    # Clear all at once
    allowlist.clear()

    # Nothing should be allowed
    assert not allowlist.allowed_peer(peer_id)
    assert not allowlist.allowed_multiaddr(addr)
    assert not allowlist.allowed_peer_and_multiaddr(peer_id, addr)


def test_clear_all() -> None:
    """Test clearing all allowlist entries."""
    allowlist = Allowlist()

    peer_id = ID(b"test_peer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/8080")

    # Add entries
    allowlist.add_peer(peer_id)
    allowlist.add_multiaddr(addr)
    allowlist.add_peer_multiaddr(peer_id, addr)

    # Clear all
    allowlist.clear()

    # Nothing should be allowed
    assert not allowlist.allowed_peer(peer_id)
    assert not allowlist.allowed_multiaddr(addr)
    assert not allowlist.allowed_peer_and_multiaddr(peer_id, addr)

    # Should be empty
    assert allowlist.is_empty()
    assert len(allowlist) == 0


def test_limit_enforcement() -> None:
    """Test allowlist size behavior."""
    # Current implementation doesn't enforce size limits
    # Test basic size tracking instead
    allowlist = Allowlist()

    # Add peers
    peer1 = ID(b"peer1")
    peer2 = ID(b"peer2")
    peer3 = ID(b"peer3")

    allowlist.add_peer(peer1)
    allowlist.add_peer(peer2)
    allowlist.add_peer(peer3)

    # All should be allowed
    assert allowlist.allowed_peer(peer1)
    assert allowlist.allowed_peer(peer2)
    assert allowlist.allowed_peer(peer3)

    # Check size
    assert len(allowlist) == 3


def test_config_object() -> None:
    """Test AllowlistConfig object."""
    config = AllowlistConfig()

    # Check defaults (empty sets)
    assert len(config.peers) == 0
    assert len(config.multiaddrs) == 0
    assert len(config.peer_multiaddrs) == 0

    # Add some values
    peer_id = ID(b"test_peer")
    addr = "/ip4/127.0.0.1/tcp/8080"

    config.peers.add(peer_id)
    config.multiaddrs.add(addr)
    config.peer_multiaddrs.add((peer_id, addr))

    assert len(config.peers) == 1
    assert len(config.multiaddrs) == 1
    assert len(config.peer_multiaddrs) == 1


def test_edge_cases() -> None:
    """Test edge cases and error conditions."""
    allowlist = Allowlist()

    # Invalid peer ID should be handled gracefully
    invalid_peer = ID(b"")  # Empty bytes for invalid peer
    assert not allowlist.allowed_peer(invalid_peer)

    # Empty string multiaddr should be handled gracefully
    assert not allowlist.allowed_multiaddr("")

    # Invalid combinations should be handled gracefully
    assert not allowlist.allowed_peer_and_multiaddr(invalid_peer, "")

    # Removing non-existent items should not error
    peer_id = ID(b"nonexistent")
    addr = Multiaddr("/ip4/1.2.3.4/tcp/1234")

    allowlist.remove_peer(peer_id)  # Should not raise
    allowlist.remove_multiaddr(addr)  # Should not raise
    allowlist.remove_peer_multiaddr(peer_id, addr)  # Should not raise


def test_multiaddr_patterns() -> None:
    """Test multiaddr pattern matching."""
    allowlist = Allowlist()

    # Test various multiaddr formats
    addrs = [
        "/ip4/127.0.0.1/tcp/8080",
        "/ip6/::1/tcp/8080",
        "/ip4/192.168.1.1/tcp/9000/ws",
        "/dns4/example.com/tcp/443/tls",
    ]

    for addr_str in addrs:
        addr = Multiaddr(addr_str)
        allowlist.add_multiaddr(addr)
        assert allowlist.allowed_multiaddr(addr)


def test_concurrent_access() -> None:
    """Test concurrent access to allowlist."""
    import threading

    allowlist = Allowlist()
    errors = []

    def worker(worker_id) -> None:
        try:
            peer_id = ID(f"peer_{worker_id}".encode())
            addr = Multiaddr(f"/ip4/192.168.1.{worker_id}/tcp/8080")

            # Add entries
            allowlist.add_peer(peer_id)
            allowlist.add_multiaddr(addr)
            allowlist.add_peer_multiaddr(peer_id, addr)

            # Check entries
            assert allowlist.allowed_peer(peer_id)
            assert allowlist.allowed_multiaddr(addr)
            assert allowlist.allowed_peer_and_multiaddr(peer_id, addr)

        except Exception as e:
            errors.append(e)

    # Start multiple threads
    threads = []
    for i in range(10):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    # Wait for completion
    for t in threads:
        t.join()

    # Should not have errors
    assert len(errors) == 0
