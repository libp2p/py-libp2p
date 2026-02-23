"""
QUIC Transport implementation
"""

import copy
import logging
import ssl
from typing import TYPE_CHECKING, cast

from aioquic.quic.configuration import (
    QuicConfiguration,
)
from aioquic.quic.connection import (
    QuicConnection as NativeQUICConnection,
)
from aioquic.quic.logger import QuicLogger
import multiaddr
import trio

from libp2p.abc import (
    ITransport,
)
from libp2p.crypto.keys import (
    PrivateKey,
)
from libp2p.custom_types import TProtocol, TQUICConnHandlerFn
from libp2p.peer.id import (
    ID,
)
from libp2p.transport.quic.security import QUICTLSSecurityConfig
from libp2p.transport.quic.utils import (
    create_client_config_from_base,
    create_server_config_from_base,
    get_alpn_protocols,
    is_quic_multiaddr,
    multiaddr_to_quic_version,
    quic_multiaddr_to_endpoint,
    quic_version_to_wire_format,
)

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm
else:
    Swarm = cast(type, object)

from .config import (
    QUICTransportConfig,
)
from .connection import (
    QUICConnection,
)
from .exceptions import (
    QUICDialError,
    QUICListenError,
    QUICSecurityError,
)
from .listener import (
    QUICListener,
)
from .security import (
    QUICTLSConfigManager,
    create_quic_security_transport,
)

QUIC_V1_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_V1
QUIC_DRAFT29_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_DRAFT29

logger = logging.getLogger(__name__)


class QUICTransport(ITransport):
    """
    QUIC Stream implementation following libp2p IMuxedStream interface.
    """

    def __init__(
        self, private_key: PrivateKey, config: QUICTransportConfig | None = None
    ) -> None:
        """
        Initialize QUIC transport with security integration.

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

        # Security manager for TLS integration
        self._security_manager = create_quic_security_transport(
            self._private_key, self._peer_id
        )

        # QUIC configurations for different versions
        self._quic_configs: dict[TProtocol, QuicConfiguration] = {}
        self._setup_quic_configurations()

        # Resource management
        self._closed = False
        self._nursery_manager = trio.CapacityLimiter(1)
        self._background_nursery: trio.Nursery | None = None

        self._swarm: Swarm | None = None

        logger.debug(
            f"Initialized QUIC transport with security for peer {self._peer_id}"
        )

    def set_background_nursery(self, nursery: trio.Nursery) -> None:
        """Set the nursery to use for background tasks (called by swarm)."""
        self._background_nursery = nursery
        logger.debug("Transport background nursery set")

    def set_swarm(self, swarm: "Swarm") -> None:
        """Set the swarm for adding incoming connections."""
        self._swarm = swarm

    def _setup_quic_configurations(self) -> None:
        """Setup QUIC configurations."""
        try:
            # Get TLS configuration from security manager
            server_tls_config = self._security_manager.create_server_config()
            client_tls_config = self._security_manager.create_client_config()

            # Base server configuration
            base_server_config = QuicConfiguration(
                is_client=False,
                alpn_protocols=get_alpn_protocols(),
                verify_mode=self._config.verify_mode,
                max_datagram_frame_size=self._config.max_datagram_size,
                idle_timeout=self._config.idle_timeout,
            )

            # Base client configuration
            base_client_config = QuicConfiguration(
                is_client=True,
                alpn_protocols=get_alpn_protocols(),
                verify_mode=self._config.verify_mode,
                max_datagram_frame_size=self._config.max_datagram_size,
                idle_timeout=self._config.idle_timeout,
            )

            # Apply TLS configuration
            self._apply_tls_configuration(base_server_config, server_tls_config)
            self._apply_tls_configuration(base_client_config, client_tls_config)

            # QUIC v1 (RFC 9000) configurations
            if self._config.enable_v1:
                quic_v1_server_config = create_server_config_from_base(
                    base_server_config, self._security_manager, self._config
                )
                quic_v1_server_config.supported_versions = [
                    quic_version_to_wire_format(QUIC_V1_PROTOCOL)
                ]

                quic_v1_client_config = create_client_config_from_base(
                    base_client_config, self._security_manager, self._config
                )
                quic_v1_client_config.supported_versions = [
                    quic_version_to_wire_format(QUIC_V1_PROTOCOL)
                ]

                # Store both server and client configs for v1
                self._quic_configs[TProtocol(f"{QUIC_V1_PROTOCOL}_server")] = (
                    quic_v1_server_config
                )
                self._quic_configs[TProtocol(f"{QUIC_V1_PROTOCOL}_client")] = (
                    quic_v1_client_config
                )

            # QUIC draft-29 configurations for compatibility
            if self._config.enable_draft29:
                draft29_server_config: QuicConfiguration = copy.copy(base_server_config)
                draft29_server_config.supported_versions = [
                    quic_version_to_wire_format(QUIC_DRAFT29_PROTOCOL)
                ]

                draft29_client_config = copy.copy(base_client_config)
                draft29_client_config.supported_versions = [
                    quic_version_to_wire_format(QUIC_DRAFT29_PROTOCOL)
                ]

                self._quic_configs[TProtocol(f"{QUIC_DRAFT29_PROTOCOL}_server")] = (
                    draft29_server_config
                )
                self._quic_configs[TProtocol(f"{QUIC_DRAFT29_PROTOCOL}_client")] = (
                    draft29_client_config
                )

            logger.debug("QUIC configurations initialized with libp2p TLS security")

        except Exception as e:
            raise QUICSecurityError(
                f"Failed to setup QUIC TLS configurations: {e}"
            ) from e

    def _apply_tls_configuration(
        self, config: QuicConfiguration, tls_config: QUICTLSSecurityConfig
    ) -> None:
        """
        Apply TLS configuration to a QUIC configuration using aioquic's actual API.

        Args:
            config: QuicConfiguration to update
            tls_config: TLS configuration dictionary from security manager

        """
        try:
            config.certificate = tls_config.certificate
            config.private_key = tls_config.private_key
            config.certificate_chain = tls_config.certificate_chain
            config.alpn_protocols = tls_config.alpn_protocols
            config.verify_mode = ssl.CERT_NONE

            logger.debug("Successfully applied TLS configuration to QUIC config")

        except Exception as e:
            raise QUICSecurityError(f"Failed to apply TLS configuration: {e}") from e

    async def dial(
        self,
        maddr: multiaddr.Multiaddr,
    ) -> QUICConnection:
        """
        Dial a remote peer using QUIC transport with security verification.

        Args:
            maddr: Multiaddr of the remote peer (e.g., /ip4/1.2.3.4/udp/4001/quic-v1)
            peer_id: Expected peer ID for verification
            nursery: Nursery to execute the background tasks

        Returns:
            Raw connection interface to the remote peer

        Raises:
            QUICDialError: If dialing fails
            QUICSecurityError: If security verification fails

        """
        if self._closed:
            raise QUICDialError("Transport is closed")

        if not is_quic_multiaddr(maddr):
            raise QUICDialError(f"Invalid QUIC multiaddr: {maddr}")

        try:
            # Extract connection details from multiaddr
            host, port = quic_multiaddr_to_endpoint(maddr)
            remote_peer_id = maddr.get_peer_id()
            if remote_peer_id is not None:
                remote_peer_id = ID.from_string(remote_peer_id)

            if remote_peer_id is None:
                logger.error("Unable to derive peer id from multiaddr")
                raise QUICDialError("Unable to derive peer id from multiaddr")
            quic_version = multiaddr_to_quic_version(maddr)

            # Get appropriate QUIC client configuration
            config_key = TProtocol(f"{quic_version}_client")
            logger.debug("config_key", config_key, self._quic_configs.keys())
            config = self._quic_configs.get(config_key)
            if not config:
                raise QUICDialError(f"Unsupported QUIC version: {quic_version}")

            config.is_client = True
            config.quic_logger = QuicLogger()

            # Ensure client certificate is properly set for mutual authentication
            if not config.certificate or not config.private_key:
                logger.warning(
                    "Client config missing certificate - applying TLS config"
                )
                client_tls_config = self._security_manager.create_client_config()
                self._apply_tls_configuration(config, client_tls_config)

            # Debug log to verify certificate is present
            logger.info(
                f"Dialing QUIC connection to {host}:{port} (version: {{quic_version}})"
            )

            logger.debug("Starting QUIC Connection")
            # Create QUIC connection using aioquic's sans-IO core
            native_quic_connection = NativeQUICConnection(configuration=config)

            # Create trio-based QUIC connection wrapper with security
            connection = QUICConnection(
                quic_connection=native_quic_connection,
                remote_addr=(host, port),
                remote_peer_id=remote_peer_id,
                local_peer_id=self._peer_id,
                is_initiator=True,
                maddr=maddr,
                transport=self,
                security_manager=self._security_manager,
            )
            logger.debug("QUIC Connection Created")

            if self._background_nursery is None:
                logger.error("No nursery set to execute background tasks")
                raise QUICDialError("No nursery found to execute tasks")

            await connection.connect(self._background_nursery)

            # Store connection for management
            conn_id = f"{host}:{port}"
            self._connections[conn_id] = connection

            return connection

        except Exception as e:
            logger.error(f"Failed to dial QUIC connection to {maddr}: {e}")
            raise QUICDialError(f"Dial failed: {e}") from e

    async def _verify_peer_identity(
        self, connection: QUICConnection, expected_peer_id: ID
    ) -> None:
        """
        Verify remote peer identity after TLS handshake.

        Args:
            connection: The established QUIC connection
            expected_peer_id: Expected peer ID

        Raises:
            QUICSecurityError: If peer verification fails

        """
        try:
            # Get peer certificate from the connection
            peer_certificate = await connection.get_peer_certificate()

            if not peer_certificate:
                raise QUICSecurityError("No peer certificate available")

            # Verify peer identity using security manager
            verified_peer_id = self._security_manager.verify_peer_identity(
                peer_certificate, expected_peer_id
            )

            if verified_peer_id != expected_peer_id:
                raise QUICSecurityError(
                    "Peer ID verification failed: expected "
                    f"{expected_peer_id}, got {verified_peer_id}"
                )

            logger.debug(f"Peer identity verified: {verified_peer_id}")
            logger.debug(f"Peer identity verified: {verified_peer_id}")

        except Exception as e:
            raise QUICSecurityError(f"Peer identity verification failed: {e}") from e

    def create_listener(self, handler_function: TQUICConnHandlerFn) -> QUICListener:
        """
        Create a QUIC listener with integrated security.

        Args:
            handler_function: Function to handle new connections

        Returns:
            QUIC listener instance

        Raises:
            QUICListenError: If transport is closed

        """
        if self._closed:
            raise QUICListenError("Transport is closed")

        # Get server configurations for the listener
        server_configs = {
            version: config
            for version, config in self._quic_configs.items()
            if version.endswith("_server")
        }

        listener = QUICListener(
            transport=self,
            handler_function=handler_function,
            quic_configs=server_configs,
            config=self._config,
            security_manager=self._security_manager,
        )

        self._listeners.append(listener)
        logger.debug("Created QUIC listener with security")
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
        logger.debug("Closing QUIC transport")

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

        logger.debug("QUIC transport closed")

    async def _cleanup_terminated_connection(
        self, connection: "QUICConnection"
    ) -> None:
        """Clean up a terminated connection from all listeners."""
        try:
            for listener in self._listeners:
                await listener._remove_connection_by_object(connection)
            logger.debug(
                "✅ TRANSPORT: Cleaned up terminated connection from all listeners"
            )
        except Exception as e:
            logger.error(f"❌ TRANSPORT: Error cleaning up terminated connection: {e}")

    def get_stats(self) -> dict[str, int | list[str] | object]:
        """Get transport statistics including security info."""
        return {
            "active_connections": len(self._connections),
            "active_listeners": len(self._listeners),
            "supported_protocols": self.protocols(),
            "local_peer_id": str(self._peer_id),
            "security_enabled": True,
            "tls_configured": True,
        }

    def get_security_manager(self) -> QUICTLSConfigManager:
        """
        Get the security manager for this transport.

        Returns:
            The QUIC TLS configuration manager

        """
        return self._security_manager

    def get_listener_socket(self) -> trio.socket.SocketType | None:
        """Get the socket from the first active listener."""
        for listener in self._listeners:
            if listener.is_listening() and listener._socket:
                return listener._socket
        return None
