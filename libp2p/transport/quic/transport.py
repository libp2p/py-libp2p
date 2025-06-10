"""
QUIC Transport implementation for py-libp2p.
Uses aioquic's sans-IO core with trio for native async support.
Based on aioquic library with interface consistency to go-libp2p and js-libp2p.
"""

import copy
import logging

from aioquic.quic.configuration import (
    QuicConfiguration,
)
from aioquic.quic.connection import (
    QuicConnection,
)
import multiaddr
import trio

from libp2p.abc import (
    IListener,
    IRawConnection,
    ITransport,
)
from libp2p.crypto.keys import (
    PrivateKey,
)
from libp2p.custom_types import THandler, TProtocol
from libp2p.peer.id import (
    ID,
)
from libp2p.transport.quic.utils import (
    is_quic_multiaddr,
    multiaddr_to_quic_version,
    quic_multiaddr_to_endpoint,
)

from .config import (
    QUICTransportConfig,
)
from .connection import (
    QUICConnection,
)
from .exceptions import (
    QUICDialError,
    QUICListenError,
)
from .listener import (
    QUICListener,
)

QUIC_V1_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_V1
QUIC_DRAFT29_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_DRAFT29

logger = logging.getLogger(__name__)


class QUICTransport(ITransport):
    """
    QUIC Transport implementation following libp2p transport interface.

    Uses aioquic's sans-IO core with trio for native async support.
    Supports both QUIC v1 (RFC 9000) and draft-29 for compatibility with
    go-libp2p and js-libp2p implementations.
    """

    def __init__(
        self, private_key: PrivateKey, config: QUICTransportConfig | None = None
    ):
        """
        Initialize QUIC transport.

        Args:
            private_key: libp2p private key for identity and TLS cert generation
            config: QUIC transport configuration options

        """
        self._private_key = private_key
        self._peer_id = ID.from_pubkey(private_key.get_public_key())
        self._config = config or QUICTransportConfig()

        # Connection management
        self._connections: dict[str, QUICConnection] = {}
        self._listeners: list[QUICListener] = []

        # QUIC configurations for different versions
        self._quic_configs: dict[TProtocol, QuicConfiguration] = {}
        self._setup_quic_configurations()

        # Resource management
        self._closed = False
        self._nursery_manager = trio.CapacityLimiter(1)

        logger.info(f"Initialized QUIC transport for peer {self._peer_id}")

    def _setup_quic_configurations(self) -> None:
        """Setup QUIC configurations for supported protocol versions."""
        # Base configuration
        base_config = QuicConfiguration(
            is_client=False,
            alpn_protocols=["libp2p"],
            verify_mode=self._config.verify_mode,
            max_datagram_frame_size=self._config.max_datagram_size,
            idle_timeout=self._config.idle_timeout,
        )

        # Add TLS certificate generated from libp2p private key
        # self._setup_tls_configuration(base_config)

        # QUIC v1 (RFC 9000) configuration
        quic_v1_config = copy.deepcopy(base_config)
        quic_v1_config.supported_versions = [0x00000001]  # QUIC v1
        self._quic_configs[QUIC_V1_PROTOCOL] = quic_v1_config

        # QUIC draft-29 configuration for compatibility
        if self._config.enable_draft29:
            draft29_config = copy.deepcopy(base_config)
            draft29_config.supported_versions = [0xFF00001D]  # draft-29
            self._quic_configs[QUIC_DRAFT29_PROTOCOL] = draft29_config

    # TODO: SETUP TLS LISTENER
    # def _setup_tls_configuration(self, config: QuicConfiguration) -> None:
    #     """
    #     Setup TLS configuration with libp2p identity integration.
    #     Similar to go-libp2p's certificate generation approach.
    #     """
    #     from .security import (
    #         generate_libp2p_tls_config,
    #     )

    #     # Generate TLS certificate with embedded libp2p peer ID
    #     # This follows the libp2p TLS spec for peer identity verification
    #     tls_config = generate_libp2p_tls_config(self._private_key, self._peer_id)

    #     config.load_cert_chain(certfile=tls_config.cert_file, keyfile=tls_config.key_file)
    #     if tls_config.ca_file:
    #         config.load_verify_locations(tls_config.ca_file)

    async def dial(
        self, maddr: multiaddr.Multiaddr, peer_id: ID | None = None
    ) -> IRawConnection:
        """
        Dial a remote peer using QUIC transport.

        Args:
            maddr: Multiaddr of the remote peer (e.g., /ip4/1.2.3.4/udp/4001/quic-v1)
            peer_id: Expected peer ID for verification

        Returns:
            Raw connection interface to the remote peer

        Raises:
            QUICDialError: If dialing fails

        """
        if self._closed:
            raise QUICDialError("Transport is closed")

        if not is_quic_multiaddr(maddr):
            raise QUICDialError(f"Invalid QUIC multiaddr: {maddr}")

        try:
            # Extract connection details from multiaddr
            host, port = quic_multiaddr_to_endpoint(maddr)
            quic_version = multiaddr_to_quic_version(maddr)

            # Get appropriate QUIC configuration
            config = self._quic_configs.get(quic_version)
            if not config:
                raise QUICDialError(f"Unsupported QUIC version: {quic_version}")

            # Create client configuration
            client_config = copy.deepcopy(config)
            client_config.is_client = True

            logger.debug(
                f"Dialing QUIC connection to {host}:{port} (version: {quic_version})"
            )

            # Create QUIC connection using aioquic's sans-IO core
            quic_connection = QuicConnection(configuration=client_config)

            # Create trio-based QUIC connection wrapper
            connection = QUICConnection(
                quic_connection=quic_connection,
                remote_addr=(host, port),
                peer_id=peer_id,
                local_peer_id=self._peer_id,
                is_initiator=True,
                maddr=maddr,
                transport=self,
            )

            # Establish connection using trio
            # We need a nursery for this - in real usage, this would be provided
            # by the caller or we'd use a transport-level nursery
            async with trio.open_nursery() as nursery:
                await connection.connect(nursery)

            # Store connection for management
            conn_id = f"{host}:{port}:{peer_id}"
            self._connections[conn_id] = connection

            # Perform libp2p handshake verification
            # await connection.verify_peer_identity()

            logger.info(f"Successfully dialed QUIC connection to {peer_id}")
            return connection

        except Exception as e:
            logger.error(f"Failed to dial QUIC connection to {maddr}: {e}")
            raise QUICDialError(f"Dial failed: {e}") from e

    def create_listener(self, handler_function: THandler) -> IListener:
        """
        Create a QUIC listener.

        Args:
            handler_function: Function to handle new connections

        Returns:
            QUIC listener instance

        Raises:
            QUICListenError: If transport is closed

        """
        if self._closed:
            raise QUICListenError("Transport is closed")

        listener = QUICListener(
            transport=self,
            handler_function=handler_function,
            quic_configs=self._quic_configs,
            config=self._config,
        )

        self._listeners.append(listener)
        logger.debug("Created QUIC listener")
        return listener

    def can_dial(self, maddr: multiaddr.Multiaddr) -> bool:
        """
        Check if this transport can dial the given multiaddr.

        Args:
            maddr: Multiaddr to check

        Returns:
            True if this transport can dial the address

        """
        return is_quic_multiaddr(maddr)

    def protocols(self) -> list[TProtocol]:
        """
        Get supported protocol identifiers.

        Returns:
            List of supported protocol strings

        """
        protocols = [QUIC_V1_PROTOCOL]
        if self._config.enable_draft29:
            protocols.append(QUIC_DRAFT29_PROTOCOL)
        return protocols

    def listen_order(self) -> int:
        """
        Get the listen order priority for this transport.
        Matches go-libp2p's ListenOrder = 1 for QUIC.

        Returns:
            Priority order for listening (lower = higher priority)

        """
        return 1

    async def close(self) -> None:
        """Close the transport and cleanup resources."""
        if self._closed:
            return

        self._closed = True
        logger.info("Closing QUIC transport")

        # Close all active connections and listeners concurrently using trio nursery
        async with trio.open_nursery() as nursery:
            # Close all connections
            for connection in self._connections.values():
                nursery.start_soon(connection.close)

            # Close all listeners
            for listener in self._listeners:
                nursery.start_soon(listener.close)

        self._connections.clear()
        self._listeners.clear()

        logger.info("QUIC transport closed")

    def get_stats(self) -> dict:
        """Get transport statistics."""
        stats = {
            "active_connections": len(self._connections),
            "active_listeners": len(self._listeners),
            "supported_protocols": self.protocols(),
        }

        # Aggregate listener stats
        listener_stats = {}
        for i, listener in enumerate(self._listeners):
            listener_stats[f"listener_{i}"] = listener.get_stats()

        if listener_stats:
            # TODO: Fix type of listener_stats
            # type: ignore
            stats["listeners"] = listener_stats

        return stats

    def __str__(self) -> str:
        """String representation of the transport."""
        return f"QUICTransport(peer_id={self._peer_id}, protocols={self.protocols()})"


def new_transport(
    private_key: PrivateKey, config: QUICTransportConfig | None = None, **kwargs
) -> QUICTransport:
    """
    Factory function to create a new QUIC transport.
    Follows the naming convention from go-libp2p (NewTransport).

    Args:
        private_key: libp2p private key
        config: Transport configuration
        **kwargs: Additional configuration options

    Returns:
        New QUIC transport instance

    """
    if config is None:
        config = QUICTransportConfig(**kwargs)

    return QUICTransport(private_key, config)


# Type aliases for consistency with go-libp2p
NewTransport = new_transport  # go-libp2p style naming
