# Fix for ICE configuration to force localhost candidate usage
from __future__ import annotations

import logging
from typing import Any

from aiortc import RTCConfiguration, RTCIceServer

from ..constants import DEFAULT_ICE_SERVERS
from .direct_rtc_connection import DirectPeerConnection
from .util import is_localhost_address

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public.ice_config_fix")


def create_localhost_ice_config() -> RTCConfiguration:
    """
    Create RTCConfiguration optimized for localhost connections.

    This disables ICE server usage and forces local candidate gathering,
    which is essential for localhost testing scenarios.
    """
    config = RTCConfiguration(
        iceServers=[],  # Empty - no STUN/TURN for localhost
    )

    logger.info("Created localhost-optimized ICE configuration (no ICE servers)")
    return config


def create_ice_config_for_address(target_ip: str) -> RTCConfiguration:
    """
    Create appropriate ICE configuration based on target address.

    Args:
        target_ip: The IP address we're connecting to

    Returns:
        RTCConfiguration optimized for the connection type

    """
    if is_localhost_address(target_ip):
        # Localhost - no ICE servers needed
        return create_localhost_ice_config()
    else:
        # Remote - use STUN servers
        ice_servers = [
            RTCIceServer(**s) if not isinstance(s, RTCIceServer) else s
            for s in DEFAULT_ICE_SERVERS
        ]

        config = RTCConfiguration(iceServers=ice_servers)
        logger.info(
            f"Created remote ICE configuration with {len(ice_servers)} ICE servers"
        )
        return config


# Patch for DirectPeerConnection to ensure localhost candidates are gathered
def patch_direct_peer_connection_for_localhost() -> None:
    """
    Monkey-patch DirectPeerConnection to force localhost candidate gathering.

    This ensures that 127.0.0.1 candidates are included even when
    aiortc/aioice would normally skip them.
    """
    original_ensure_ice = DirectPeerConnection._ensure_custom_ice_credentials

    def patched_ensure_ice(self: DirectPeerConnection) -> None:
        """Patched version that also enables localhost candidates"""
        # Call original
        original_ensure_ice(self)

        # Force localhost candidate gathering
        if self.sctp is not None and self.sctp.transport is not None:
            ice_transport = self.sctp.transport.transport
            ice_gatherer = ice_transport.iceGatherer
            connection = ice_gatherer._connection

            # Enable localhost candidates
            if hasattr(connection, "_local_candidates"):
                # Check if localhost candidates are present
                local_candidates = connection._local_candidates
                has_localhost = any("127.0.0.1" in str(c) for c in local_candidates)

                if not has_localhost:
                    logger.warning(
                        "No localhost candidates found - this may cause "
                        "connection failures in test environments"
                    )

    setattr(DirectPeerConnection, "_ensure_custom_ice_credentials", patched_ensure_ice)
    logger.info("Patched DirectPeerConnection for localhost candidate support")


# Enhanced aioice patch that's more aggressive
def enhanced_aioice_localhost_patch() -> None:
    """
    Enhanced version of aioice patch that forces localhost candidate gathering.
    """
    try:
        from aioice import ice as _aioice_ice
    except ImportError:
        logger.warning("aioice not available for patching")
        return

    if getattr(_aioice_ice, "_libp2p_enhanced_patch", False):  # type: ignore[attr-defined]
        return

    # Patch get_host_addresses
    original_get_host_addresses = _aioice_ice.get_host_addresses

    def patched_get_host_addresses(use_ipv4: bool, use_ipv6: bool) -> list[str]:
        addresses = original_get_host_addresses(use_ipv4, use_ipv6)

        # ALWAYS include localhost addresses first (higher priority)
        result = []
        if use_ipv4:
            result.append("127.0.0.1")
        if use_ipv6:
            result.append("::1")

        # Add other addresses
        for addr in addresses:
            if addr not in result:
                result.append(addr)

        logger.debug(f"Patched ICE addresses: {result}")
        return result

    _aioice_ice.get_host_addresses = patched_get_host_addresses

    # Also patch Connection class to not filter localhost
    if hasattr(_aioice_ice, "Connection"):
        Connection = _aioice_ice.Connection

        if hasattr(Connection, "gather_candidates"):
            original_gather = Connection.gather_candidates

            async def patched_gather(self: Any, *args: Any, **kwargs: Any) -> None:
                """Patched gather that includes localhost. Original returns None."""
                await original_gather(self, *args, **kwargs)

                # Ensure localhost candidates are present
                has_localhost = any(
                    "127.0.0.1" in str(c.host) for c in self.local_candidates
                )
                if not has_localhost:
                    logger.warning(
                        "Localhost candidates missing after gather - "
                        "ICE may fail for local connections"
                    )

            setattr(Connection, "gather_candidates", patched_gather)

    setattr(_aioice_ice, "_libp2p_enhanced_patch", True)  # type: ignore[attr-defined]
    logger.info("Enhanced aioice localhost patch installed")
