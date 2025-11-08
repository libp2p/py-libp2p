"""
Utility functions for WebRTC private-to-private transport.
"""

import logging

from multiaddr import Multiaddr

from libp2p.peer.id import ID

from ..constants import WebRTCError

logger = logging.getLogger("libp2p.transport.webrtc.private_to_private.util")


def split_addr(ma: Multiaddr) -> tuple[Multiaddr, ID]:
    """
    Split a WebRTC multiaddr into circuit address and target peer ID.

    Following js-libp2p pattern: get all p2p components, last one is target.
    Remove /webrtc to get circuit address.

    Example:
        Input: /ip4/127.0.0.1/tcp/9000/ws/p2p/RELAY_ID/p2p-circuit/webrtc/p2p/TARGET_ID
        Output:
            (
                /ip4/127.0.0.1/tcp/9000/ws/p2p/RELAY_ID/p2p-circuit/p2p/TARGET_ID,
                TARGET_ID,
            )

    Args:
        ma: WebRTC multiaddr containing circuit relay path and target peer

    Returns:
        tuple: (circuit_addr, target_peer_id)

    Raises:
        WebRTCError: If target peer ID cannot be extracted

    """
    # Get all p2p protocol values from multiaddr
    # Parse the multiaddr string to extract all p2p values
    addr_str = str(ma)
    p2p_parts = addr_str.split("/p2p/")

    if len(p2p_parts) < 2:
        raise WebRTCError("Destination peer id was missing from multiaddr")

    # Last p2p value is the target peer
    # Extract from the last part after /p2p/
    last_p2p_part = p2p_parts[-1]
    # Remove any protocol after p2p (like /p2p-circuit, etc.)
    target_peer_str = last_p2p_part.split("/")[0]

    if not target_peer_str:
        raise WebRTCError("Cannot extract target peer ID from multiaddr")

    target_peer = ID.from_base58(target_peer_str)

    # Create circuit address by removing /webrtc protocol
    # Simple string replacement approach
    if "/webrtc" in addr_str:
        circuit_addr_str = addr_str.replace("/webrtc", "")
        circuit_addr = Multiaddr(circuit_addr_str)
    else:
        circuit_addr = ma

    logger.debug(f"Split addr: circuit={circuit_addr}, target={target_peer}")
    return circuit_addr, target_peer


def get_remote_peer(ma: Multiaddr) -> ID:
    """
    Extract remote peer ID from WebRTC multiaddr.

    Args:
        ma: Multiaddr containing p2p protocol

    Returns:
        ID: Remote peer ID

    Raises:
        WebRTCError: If peer ID cannot be extracted

    """
    p2p_values = []
    for component in ma.protocols():
        if component.name == "p2p":
            value = ma.value_for_protocol("p2p")
            if value:
                p2p_values.append(value)

    if not p2p_values:
        raise WebRTCError("Remote peerId must be present in multiaddr")

    # Return the last p2p value (target peer)
    return ID.from_base58(p2p_values[-1])


def get_relay_peer(ma: Multiaddr) -> ID:
    """
    Extract relay peer ID from a circuit relay multiaddr.
    """
    addr_str = str(ma)
    parts = addr_str.split("/p2p/")

    if len(parts) < 2:
        raise WebRTCError("Relay peer id missing from multiaddr")

    relay_part = parts[1]
    relay_peer_str = relay_part.split("/")[0]

    if not relay_peer_str:
        raise WebRTCError("Cannot extract relay peer ID from multiaddr")

    return ID.from_base58(relay_peer_str)


def extract_relay_base_addr(ma: Multiaddr) -> Multiaddr | None:
    """
    Extract the base transport address for the relay without /p2p suffix.
    """
    addr_str = str(ma)
    p2p_index = addr_str.find("/p2p/")
    if p2p_index == -1:
        return None

    base_str = addr_str[:p2p_index]
    if not base_str:
        return None

    try:
        return Multiaddr(base_str)
    except Exception:
        logger.debug("Failed to parse relay base address from %s", base_str)
        return None
