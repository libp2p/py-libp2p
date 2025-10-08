@pytest.mark.trio
async def test_find_closest_peers_network_fallback_to_connected_peers(
    self, peer_routing, mock_host
):
    """Test network search falls back to connected peers with insufficient routing table peers."""
    target_key = b"target_key"

    # Create some connected peers
    connected_peers = [create_valid_peer_id(f"connected{i}") for i in range(3)]
    mock_host.get_connected_peers.return_value = connected_peers

    # Mock routing table to return insufficient peers (less than MIN_PEERS_THRESHOLD=5)
    insufficient_peers = [create_valid_peer_id("insufficient")]
    with patch.object(
        peer_routing.routing_table,
        "find_local_closest_peers",
        return_value=insufficient_peers,
    ):
        # Mock _query_peer_for_closest to return empty results
        with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
            with patch(
                "libp2p.kad_dht.peer_routing.sort_peer_ids_by_distance",
                return_value=connected_peers,
            ) as mock_sort:
                result = await peer_routing.find_closest_peers_network(target_key)

                # Should use connected peers as fallback
                mock_sort.assert_called_once_with(target_key, connected_peers)
                assert result == connected_peers

@pytest.mark.trio
async def test_find_closest_peers_network_no_fallback_when_sufficient_peers(
    self, peer_routing, mock_host
):
    """Test network search doesn't fall back when routing table has sufficient peers."""
    target_key = b"target_key"

    # Create some connected peers
    connected_peers = [create_valid_peer_id(f"connected{i}") for i in range(3)]
    mock_host.get_connected_peers.return_value = connected_peers

    # Mock routing table to return sufficient peers (more than MIN_PEERS_THRESHOLD=5)
    sufficient_peers = [create_valid_peer_id(f"sufficient{i}") for i in range(6)]
    with patch.object(
        peer_routing.routing_table,
        "find_local_closest_peers",
        return_value=sufficient_peers,
    ):
        # Mock _query_peer_for_closest to return empty results
        with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
            with patch(
                "libp2p.kad_dht.peer_routing.sort_peer_ids_by_distance",
                return_value=sufficient_peers,
            ) as mock_sort:
                result = await peer_routing.find_closest_peers_network(target_key)

                # Should not use connected peers as fallback
                assert result == sufficient_peers

@pytest.mark.trio
async def test_find_closest_peers_network_fallback_with_no_connected_peers(
    self, peer_routing, mock_host
):
    """Test network search handles case when no connected peers exist for fallback."""
    target_key = b"target_key"

    # Mock no connected peers
    mock_host.get_connected_peers.return_value = []

    # Mock routing table to return insufficient peers
    insufficient_peers = [create_valid_peer_id("insufficient")]
    with patch.object(
        peer_routing.routing_table,
        "find_local_closest_peers",
        return_value=insufficient_peers,
    ):
        # Mock _query_peer_for_closest to return empty results
        with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
            with patch(
                "libp2p.kad_dht.peer_routing.sort_peer_ids_by_distance",
                return_value=insufficient_peers,
            ) as mock_sort:
                result = await peer_routing.find_closest_peers_network(target_key)

                # Should use the insufficient peers from routing table
                assert result == insufficient_peers
