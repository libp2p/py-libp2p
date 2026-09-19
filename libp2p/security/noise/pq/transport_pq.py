"""
Post-quantum Noise transport for py-libp2p.

Wraps PatternXXhfs as an ISecureTransport so it integrates with the
standard py-libp2p security negotiation stack.

Protocol ID: /noise-mlkem768-hfs/0.2.0 (what this implementation ships; see
libp2p/security/noise/pq/kem.py on libp2p/specs#727's open id question)
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

from .kem import IKem
from .kem_backends import make_fast_kem
from .patterns_pq import PatternXXhfs

PROTOCOL_ID = TProtocol("/noise-mlkem768-hfs/0.2.0")


class TransportPQ(ISecureTransport):
    """
    ISecureTransport backed by the Noise XXhfs + ML-KEM-768 handshake.

    Drop-in replacement for the classical Noise ``Transport``; pass it
    as a security option to ``BasicHost`` under the key ``PROTOCOL_ID``.
    """

    def __init__(
        self,
        libp2p_keypair: KeyPair,
        noise_privkey: PrivateKey,
        kem: IKem | None = None,
    ) -> None:
        """
        ``kem`` pins the ML-KEM-768 backend; the default asks
        ``make_fast_kem()``.

        The KEM is resolved here rather than per connection. Backend selection
        probes ``cryptography`` for ML-KEM support, so doing it in
        ``get_pattern()`` charged every inbound connection for a probe before
        the peer had authenticated anything. Resolving once also means a host
        with no working backend at all fails at construction instead of on its
        first connection.
        """
        self.libp2p_privkey = libp2p_keypair.private_key
        self.noise_privkey = noise_privkey
        self.local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        self.kem: IKem = kem if kem is not None else make_fast_kem()

    def get_pattern(self) -> PatternXXhfs:
        """
        Return a fresh PatternXXhfs for a single handshake.

        The pattern is per handshake; the KEM behind it is shared, because an
        ``IKem`` holds no per-handshake state (every key lives in the
        keypair that ``keygen()`` returns).
        """
        return PatternXXhfs(
            local_peer=self.local_peer,
            libp2p_privkey=self.libp2p_privkey,
            noise_static_key=self.noise_privkey,
            kem=self.kem,
        )

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """Upgrade an inbound raw connection to a PQC-secured session."""
        return await self.get_pattern().handshake_inbound(conn)

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """Upgrade an outbound raw connection to a PQC-secured session."""
        return await self.get_pattern().handshake_outbound(conn, peer_id)
