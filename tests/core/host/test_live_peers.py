import pytest
import trio

from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from tests.utils.factories import (
    HostFactory,
)


@pytest.mark.trio
async def test_live_peers_basic(security_protocol):
    """Test basic live peers functionality."""
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        host_a, host_b = hosts

        # Initially no live peers
        assert len(host_a.get_live_peers()) == 0
        assert len(host_b.get_live_peers()) == 0

        # Connect the hosts
        addr = host_b.get_addrs()[0]
        info = info_from_p2p_addr(addr)
        await host_a.connect(info)

        # Both should show each other as live peers
        assert host_b.get_id() in host_a.get_live_peers()
        assert host_a.get_id() in host_b.get_live_peers()


@pytest.mark.trio
async def test_live_peers_disconnect(security_protocol):
    """
    Test that disconnected peers are removed from live peers but remain in peerstore.
    """
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        host_a, host_b = hosts

        # Store peer IDs first for clarity
        peer_a_id = host_a.get_id()
        peer_b_id = host_b.get_id()

        # Initially no connections
        assert len(host_a.get_connected_peers()) == 0
        assert len(host_b.get_connected_peers()) == 0

        # Connect the hosts
        addr = host_b.get_addrs()[0]
        info = info_from_p2p_addr(addr)
        await host_a.connect(info)

        # Add a small delay to allow connection setup to complete
        await trio.sleep(0.1)

        # Verify connection state using get_connected_peers()
        assert len(host_a.get_connected_peers()) == 1
        assert len(host_b.get_connected_peers()) == 1
        assert peer_b_id in host_a.get_connected_peers()
        assert peer_a_id in host_b.get_connected_peers()

        # Store the connected peers for later comparison
        connected_peers_a = set(host_a.get_connected_peers())
        connected_peers_b = set(host_b.get_connected_peers())

        # Disconnect host_a from host_b
        await host_a.disconnect(peer_b_id)
        await trio.sleep(0.1)

        # Verify peers are no longer in live peers
        assert peer_b_id not in host_a.get_live_peers()
        assert peer_a_id not in host_b.get_live_peers()

        # But verify they remain in the peerstore by checking against original sets
        assert peer_b_id in connected_peers_a
        assert peer_a_id in connected_peers_b


@pytest.mark.trio
async def test_live_peers_multiple_connections(security_protocol):
    """Test live peers with multiple connections."""
    async with HostFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as hosts:
        host_a, host_b, host_c = hosts

        # Connect host_a to both host_b and host_c
        for peer in [host_b, host_c]:
            addr = peer.get_addrs()[0]
            info = info_from_p2p_addr(addr)
            await host_a.connect(info)

        # Verify host_a sees both peers as live
        live_peers = host_a.get_live_peers()
        assert len(live_peers) == 2
        assert host_b.get_id() in live_peers
        assert host_c.get_id() in live_peers

        # Verify host_b and host_c each see host_a as live
        assert host_a.get_id() in host_b.get_live_peers()
        assert host_a.get_id() in host_c.get_live_peers()

        # Disconnect one peer
        await host_a.disconnect(host_b.get_id())

        # Verify only host_c remains as live peer for host_a
        live_peers = host_a.get_live_peers()
        assert len(live_peers) == 1
        assert host_c.get_id() in live_peers


@pytest.mark.trio
async def test_live_peers_reconnect(security_protocol):
    """Test that peers can be reconnected and appear as live again."""
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        host_a, host_b = hosts

        # Initial connection
        addr = host_b.get_addrs()[0]
        info = info_from_p2p_addr(addr)
        await host_a.connect(info)

        # Verify connection
        assert host_b.get_id() in host_a.get_live_peers()

        # Disconnect
        await host_a.disconnect(host_b.get_id())
        assert host_b.get_id() not in host_a.get_live_peers()

        # Reconnect
        await host_a.connect(info)

        # Verify reconnection
        assert host_b.get_id() in host_a.get_live_peers()


@pytest.mark.trio
async def test_live_peers_unexpected_drop(security_protocol):
    """
    Test that live peers are updated correctly when connections drop unexpectedly.
    """
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        host_a, host_b = hosts

        # Store peer IDs
        peer_a_id = host_a.get_id()
        peer_b_id = host_b.get_id()

        # Initial connection
        addr = host_b.get_addrs()[0]
        info = info_from_p2p_addr(addr)
        await host_a.connect(info)

        # Verify initial connection
        assert peer_b_id in host_a.get_live_peers()
        assert peer_a_id in host_b.get_live_peers()

        # Simulate unexpected connection drop by directly closing the connection
        conn = host_a.get_network().connections[peer_b_id]
        await conn.muxed_conn.close()

        # Allow for connection cleanup
        await trio.sleep(0.1)

        # Verify peers are no longer in live peers
        assert peer_b_id not in host_a.get_live_peers()
        assert peer_a_id not in host_b.get_live_peers()

        # Verify we can reconnect after unexpected drop
        await host_a.connect(info)

        # Verify reconnection successful
        assert peer_b_id in host_a.get_live_peers()
        assert peer_a_id in host_b.get_live_peers()
