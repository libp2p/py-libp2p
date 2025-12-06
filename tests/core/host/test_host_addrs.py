from unittest.mock import MagicMock, Mock

import pytest
from multiaddr import Multiaddr

from libp2p.host.basic_host import BasicHost
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore


@pytest.mark.trio
async def test_host_addrs_separation():
    # Setup
    mock_network = MagicMock(spec=Swarm)
    mock_network.listeners = {}
    mock_network.peerstore = Mock(spec=PeerStore)

    # Create a mock transport/listener
    mock_transport = Mock()
    transport_addr_str = "/ip4/127.0.0.1/tcp/8000"
    transport_addr = Multiaddr(transport_addr_str)
    mock_transport.get_addrs.return_value = [transport_addr]

    mock_network.listeners = {"tcp": mock_transport}

    # Mock get_peer_id on network (BasicHost delegates get_id to network.get_peer_id
    # usually? No, BasicHost.get_id() calls self._network.get_peer_id())
    peer_id_str = "QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
    peer_id = ID.from_base58(peer_id_str)
    mock_network.get_peer_id.return_value = peer_id

    # Create host
    host = BasicHost(network=mock_network)

    # Test get_transport_addrs (New method)
    transport_addrs = host.get_transport_addrs()
    assert len(transport_addrs) == 1
    assert str(transport_addrs[0]) == transport_addr_str
    assert "p2p" not in str(transport_addrs[0])

    # Test get_addrs (Old method - backward compatibility)
    addrs = host.get_addrs()
    assert len(addrs) == 1
    assert str(addrs[0]) != transport_addr_str

    # Check for either p2p or ipfs protocol (multiaddr < 0.0.12 uses /ipfs/)
    addr_str = str(addrs[0])
    assert f"/p2p/{peer_id_str}" in addr_str or f"/ipfs/{peer_id_str}" in addr_str

    # Verify full construction
    expected_suffix_p2p = f"/p2p/{peer_id_str}"
    expected_suffix_ipfs = f"/ipfs/{peer_id_str}"
    assert (
        addr_str == f"{transport_addr_str}{expected_suffix_p2p}"
        or addr_str == f"{transport_addr_str}{expected_suffix_ipfs}"
    )
