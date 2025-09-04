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

from .early_data import EarlyDataHandler, TransportEarlyDataHandler
from .patterns import (
    IPattern,
    PatternXX,
)

PROTOCOL_ID = TProtocol("/noise")


class Transport(ISecureTransport):
    libp2p_privkey: PrivateKey
    noise_privkey: PrivateKey
    local_peer: ID
    supported_muxers: list[TProtocol]
    initiator_early_data_handler: EarlyDataHandler | None
    responder_early_data_handler: EarlyDataHandler | None

    def __init__(
        self,
        libp2p_keypair: KeyPair,
        noise_privkey: PrivateKey,
        supported_muxers: list[TProtocol] | None = None,
        initiator_handler: EarlyDataHandler | None = None,
        responder_handler: EarlyDataHandler | None = None,
    ) -> None:
        self.libp2p_privkey = libp2p_keypair.private_key
        self.noise_privkey = noise_privkey
        self.local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        self.supported_muxers = supported_muxers or []

        # Create default handlers for muxer negotiation if none provided
        if initiator_handler is None and self.supported_muxers:
            initiator_handler = TransportEarlyDataHandler(self.supported_muxers)
        if responder_handler is None and self.supported_muxers:
            responder_handler = TransportEarlyDataHandler(self.supported_muxers)

        self.initiator_early_data_handler = initiator_handler
        self.responder_early_data_handler = responder_handler

    def get_pattern(self) -> IPattern:
        return PatternXX(
            self.local_peer,
            self.libp2p_privkey,
            self.noise_privkey,
            self.initiator_early_data_handler,
            self.responder_early_data_handler,
        )

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        pattern = self.get_pattern()
        return await pattern.handshake_inbound(conn)

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        pattern = self.get_pattern()
        return await pattern.handshake_outbound(conn, peer_id)
