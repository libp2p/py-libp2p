logger.debug(
    "Routing table has insufficient peers (%d < %d), "
    "using connected peers as fallback",
    len(closest_peers),
    MIN_PEERS_THRESHOLD,
)

# Sort connected peers by distance to target and use as initial query targets
fallback_peers = sort_peer_ids_by_distance(target_key, connected_peers)[:count]

# Fallback to connected peers if routing table has insufficient peers
MIN_PEERS_THRESHOLD = 5  # Configurable minimum
if len(closest_peers) < MIN_PEERS_THRESHOLD:
    logger.debug(
        "Routing table has insufficient peers (%d < %d) for FIND_NODE response, "
        "using connected peers as fallback",
        len(closest_peers),
        MIN_PEERS_THRESHOLD,
    )
    connected_peers = self.host.get_connected_peers()
    if connected_peers:
        # Sort connected peers by distance to target and use as response
        fallback_peers = sort_peer_ids_by_distance(target_key, connected_peers)[:20]
        closest_peers = fallback_peers
        logger.debug(
            "Using %d connected peers as fallback for FIND_NODE response",
            len(closest_peers),
        )
