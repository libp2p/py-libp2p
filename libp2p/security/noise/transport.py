"""
Enhanced Noise transport implementation.

This module provides an enhanced Noise transport with support for advanced
features including early data, WebTransport integration, and rekey management.
The transport uses the XX handshake pattern for mutual authentication and
forward secrecy.
"""

from libp2p.abc import (
    IRawConnection,
    ISecureConn,
    ISecureTransport,
)
from libp2p.crypto.keys import (
    KeyPair,
    PrivateKey,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)

from .early_data import EarlyDataHandler, EarlyDataManager
from .patterns import (
    IPattern,
    PatternXX,
)
from .rekey import RekeyManager, RekeyPolicy
from .webtransport import WebTransportSupport

PROTOCOL_ID = TProtocol("/noise")


class Transport(ISecureTransport):
    """Enhanced Noise transport with advanced features support."""

    libp2p_privkey: PrivateKey
    noise_privkey: PrivateKey
    local_peer: ID
    early_data: bytes | None
    webtransport_support: WebTransportSupport
    early_data_manager: EarlyDataManager
    rekey_manager: RekeyManager

    def __init__(
        self,
        libp2p_keypair: KeyPair,
        noise_privkey: PrivateKey,
        early_data: bytes | None = None,
        early_data_handler: EarlyDataHandler | None = None,
        rekey_policy: RekeyPolicy | None = None,
    ) -> None:
        """
        Initialize enhanced Noise transport.

        Args:
            libp2p_keypair: libp2p key pair
            noise_privkey: Noise private key
            early_data: Optional early data
            early_data_handler: Optional early data handler
            rekey_policy: Optional rekey policy

        """
        self.libp2p_privkey = libp2p_keypair.private_key
        self.noise_privkey = noise_privkey
        self.local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        self.early_data = early_data

        # Initialize advanced features
        self.webtransport_support = WebTransportSupport()
        self.early_data_manager = EarlyDataManager(early_data_handler)
        self.rekey_manager = RekeyManager(rekey_policy)
        self._static_key_cache: dict[ID, bytes] = {}

    def get_pattern(self) -> IPattern:
        """
        Get the handshake pattern for the connection.

        Returns:
            IPattern: The XX handshake pattern

        """
        # Always use XX pattern (IK pattern has been deprecated)
        return PatternXX(
            self.local_peer,
            self.libp2p_privkey,
            self.noise_privkey,
            self.early_data,
        )

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Perform inbound secure connection.

        Args:
            conn: Raw connection

        Returns:
            ISecureConn: Secure connection

        """
        pattern = self.get_pattern()
        secure_conn = await pattern.handshake_inbound(conn)

        # Handle early data if present
        early_data = getattr(pattern, "early_data", None)
        if early_data is not None:
            await self.early_data_manager.handle_early_data(early_data)

        return secure_conn

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Perform outbound secure connection.

        Args:
            conn: Raw connection
            peer_id: Remote peer ID

        Returns:
            ISecureConn: Secure connection

        """
        pattern = self.get_pattern()
        secure_conn = await pattern.handshake_outbound(conn, peer_id)

        # Handle early data if present
        early_data = getattr(pattern, "early_data", None)
        if early_data is not None:
            await self.early_data_manager.handle_early_data(early_data)

        return secure_conn

    def cache_static_key(self, peer_id: ID, static_key: bytes) -> None:
        """
        Cache a static key for a peer.

        Args:
            peer_id: The peer ID
            static_key: The static key to cache

        """
        self._static_key_cache[peer_id] = static_key

    def get_cached_static_key(self, peer_id: ID) -> bytes | None:
        """
        Get cached static key for a peer.

        Args:
            peer_id: The peer ID

        Returns:
            The cached static key or None if not found

        """
        return self._static_key_cache.get(peer_id)

    def clear_static_key_cache(self) -> None:
        """Clear the static key cache."""
        self._static_key_cache.clear()
