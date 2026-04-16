"""
Post-quantum Noise transport for py-libp2p.

Wraps PatternXXhfs as an ISecureTransport so it integrates with the
standard py-libp2p security negotiation stack.

Protocol ID: /noise-pq/1.0.0
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
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

from .kem import XWingKem
from .patterns_pq import PatternXXhfs

PROTOCOL_ID = TProtocol("/noise-pq/1.0.0")


class TransportPQ(ISecureTransport):
    """ISecureTransport backed by the Noise XXhfs + X-Wing handshake.

    Drop-in replacement for the classical Noise ``Transport``; pass it
    as a security option to ``BasicHost`` under the key ``PROTOCOL_ID``.
    """

    def __init__(
        self,
        libp2p_keypair: KeyPair,
        noise_privkey: PrivateKey,
    ) -> None:
        self.libp2p_privkey = libp2p_keypair.private_key
        self.noise_privkey = noise_privkey
        self.local_peer = ID.from_pubkey(libp2p_keypair.public_key)

    def get_pattern(self) -> PatternXXhfs:
        """Return a fresh PatternXXhfs for a single handshake."""
        return PatternXXhfs(
            local_peer=self.local_peer,
            libp2p_privkey=self.libp2p_privkey,
            noise_static_key=self.noise_privkey,
            kem=XWingKem(),
        )

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """Upgrade an inbound raw connection to a PQC-secured session."""
        return await self.get_pattern().handshake_inbound(conn)

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """Upgrade an outbound raw connection to a PQC-secured session."""
        return await self.get_pattern().handshake_outbound(conn, peer_id)
