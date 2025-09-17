from libp2p.abc import (
    IRawConnection,
    ISecureConn,
    ISecureTransport,
)
from libp2p.crypto.keys import (
    KeyPair,
    PrivateKey,
    PublicKey,
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
from .patterns_ik import PatternIK
from .rekey import RekeyManager, RekeyPolicy
from .webtransport import WebTransportSupport

PROTOCOL_ID = TProtocol("/noise")


class Transport(ISecureTransport):
    """Enhanced Noise transport with advanced features support."""

    libp2p_privkey: PrivateKey
    noise_privkey: PrivateKey
    local_peer: ID
    early_data: bytes | None
    with_noise_pipes: bool
    webtransport_support: WebTransportSupport
    early_data_manager: EarlyDataManager
    rekey_manager: RekeyManager
    _static_key_cache: dict[ID, PublicKey]  # Cache for IK pattern

    def __init__(
        self,
        libp2p_keypair: KeyPair,
        noise_privkey: PrivateKey,
        early_data: bytes | None = None,
        with_noise_pipes: bool = False,
        early_data_handler: EarlyDataHandler | None = None,
        rekey_policy: RekeyPolicy | None = None,
    ) -> None:
        """
        Initialize enhanced Noise transport.

        Args:
            libp2p_keypair: libp2p key pair
            noise_privkey: Noise private key
            early_data: Optional early data
            with_noise_pipes: Enable noise pipes support
            early_data_handler: Optional early data handler
            rekey_policy: Optional rekey policy

        """
        self.libp2p_privkey = libp2p_keypair.private_key
        self.noise_privkey = noise_privkey
        self.local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        self.early_data = early_data
        self.with_noise_pipes = with_noise_pipes

        # Initialize advanced features
        self.webtransport_support = WebTransportSupport()
        self.early_data_manager = EarlyDataManager(early_data_handler)
        self.rekey_manager = RekeyManager(rekey_policy)
        self._static_key_cache = {}

        if self.with_noise_pipes:
            # Noise pipes are now supported with IK pattern
            pass

    def get_pattern(self, remote_peer: ID | None = None) -> IPattern:
        """
        Get the appropriate handshake pattern for the connection.

        Args:
            remote_peer: Remote peer ID (used for IK pattern selection)

        Returns:
            IPattern: The handshake pattern to use

        """
        if self.with_noise_pipes and remote_peer is not None:
            # Check if we have a cached static key for IK pattern
            if remote_peer in self._static_key_cache:
                remote_static_key = self._static_key_cache[remote_peer]
                return PatternIK(
                    self.local_peer,
                    self.libp2p_privkey,
                    self.noise_privkey,
                    self.early_data,
                    remote_peer,
                    remote_static_key,
                )

        # Default to XX pattern
        return PatternXX(
            self.local_peer,
            self.libp2p_privkey,
            self.noise_privkey,
            self.early_data,
        )

    def cache_static_key(self, peer_id: ID, static_key: PublicKey) -> None:
        """
        Cache a static key for IK pattern optimization.

        Args:
            peer_id: Peer ID
            static_key: Static public key

        """
        self._static_key_cache[peer_id] = static_key

    def get_cached_static_key(self, peer_id: ID) -> PublicKey | None:
        """
        Get a cached static key for a peer.

        Args:
            peer_id: Peer ID

        Returns:
            Optional[PublicKey]: Cached static key if available

        """
        return self._static_key_cache.get(peer_id)

    def clear_static_key_cache(self) -> None:
        """Clear the static key cache."""
        self._static_key_cache.clear()

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
        if hasattr(pattern, "early_data") and pattern.early_data is not None:
            await self.early_data_manager.handle_early_data(pattern.early_data)

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
        pattern = self.get_pattern(peer_id)
        secure_conn = await pattern.handshake_outbound(conn, peer_id)

        # Handle early data if present
        if hasattr(pattern, "early_data") and pattern.early_data is not None:
            await self.early_data_manager.handle_early_data(pattern.early_data)

        # Cache static key if we learned it during handshake
        if isinstance(pattern, PatternXX) and hasattr(
            secure_conn, "remote_permanent_pubkey"
        ):
            self.cache_static_key(peer_id, secure_conn.remote_permanent_pubkey)

        return secure_conn
