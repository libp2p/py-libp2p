import logging

from libp2p.abc import (
    IMuxedConn,
    IRawConnection,
    ISecureConn,
)
from libp2p.custom_types import (
    TMuxerOptions,
    TSecurityOptions,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.protocol_muxer.exceptions import (
    MultiselectClientError,
    MultiselectError,
)
from libp2p.protocol_muxer.multiselect import (
    DEFAULT_NEGOTIATE_TIMEOUT,
)
from libp2p.requirements import get_after_connections
from libp2p.security.exceptions import (
    HandshakeFailure,
)
from libp2p.security.security_multistream import (
    SecurityMultistream,
)
from libp2p.stream_muxer.muxer_multistream import (
    MuxerMultistream,
)
from libp2p.transport.exceptions import (
    MuxerUpgradeFailure,
    SecurityUpgradeFailure,
)

logger = logging.getLogger(__name__)


class TransportUpgrader:
    security_multistream: SecurityMultistream
    muxer_multistream: MuxerMultistream

    def __init__(
        self,
        secure_transports_by_protocol: TSecurityOptions,
        muxer_transports_by_protocol: TMuxerOptions,
        negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ):
        self.security_multistream = SecurityMultistream(secure_transports_by_protocol)
        self.muxer_multistream = MuxerMultistream(
            muxer_transports_by_protocol, negotiate_timeout
        )

    async def upgrade_security(
        self,
        raw_conn: IRawConnection,
        is_initiator: bool,
        peer_id: ID | None = None,
    ) -> ISecureConn:
        """Upgrade conn to a secured connection."""
        try:
            if is_initiator:
                if peer_id is None:
                    raise ValueError("peer_id must be provided for outbout connection")
                secure_conn = await self.security_multistream.secure_outbound(
                    raw_conn, peer_id
                )
                # Validate the authenticated peer ID matches the expected peer ID.
                authenticated_peer_id = secure_conn.get_remote_peer()
                if authenticated_peer_id != peer_id:
                    await secure_conn.close()
                    raise SecurityUpgradeFailure(
                        f"Peer ID mismatch: expected {peer_id}, "
                        f"got {authenticated_peer_id}"
                    )
                return secure_conn
            return await self.security_multistream.secure_inbound(raw_conn)
        except (MultiselectError, MultiselectClientError) as error:
            raise SecurityUpgradeFailure(
                "failed to negotiate the secure protocol"
            ) from error
        except HandshakeFailure as error:
            raise SecurityUpgradeFailure(
                "handshake failed when upgrading to secure connection"
            ) from error

    async def upgrade_connection(self, conn: ISecureConn, peer_id: ID) -> IMuxedConn:
        """Upgrade secured connection to a muxed connection.

        Before negotiating the muxer, this method verifies that the
        connection satisfies any ordering requirements declared by the
        registered muxer classes (via ``@after_connection``).
        """
        # Phase 3: verify muxer ordering requirements
        self._verify_muxer_ordering(conn)

        try:
            return await self.muxer_multistream.new_conn(conn, peer_id)
        except (MultiselectError, MultiselectClientError) as error:
            raise MuxerUpgradeFailure(
                "failed to negotiate the multiplexer protocol"
            ) from error

    # ------------------------------------------------------------------
    # Phase 3 — muxer ordering verification
    # ------------------------------------------------------------------

    def _verify_muxer_ordering(
        self, conn: ISecureConn
    ) -> None:
        """Check that *conn* satisfies the ``@after_connection`` requirements
        declared on every registered muxer class.

        If a muxer declares ``@after_connection(ISecureConn)`` the
        connection handed to it must be an ``ISecureConn`` instance.
        A mismatch is logged as a warning (non-fatal) so that existing
        code keeps working while giving operators clear diagnostics.
        """
        for protocol, muxer_class in self.muxer_multistream.transports.items():
            after = get_after_connections(muxer_class)
            if not after:
                continue
            for iface in after:
                if not isinstance(conn, iface):
                    logger.warning(
                        "Muxer %s (protocol %s) declares @after_connection(%s) "
                        "but the connection (%s) does not satisfy it",
                        muxer_class.__name__,
                        protocol,
                        iface.__name__,
                        type(conn).__name__,
                    )
