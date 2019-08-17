from dataclasses import dataclass
from typing import Optional

from libp2p.crypto.keys import PrivateKey
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID as PeerID
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.secure_conn_interface import ISecureConn

ID = "/secio/1.0.0"


@dataclass
class NegotiationContext(frozen=True):
    local_peer: PeerID
    remote_peer: Optional[PeerID]

    local_private_key: PrivateKey
    conn: IRawConnection


class SecureSession(BaseSession):
    pass


def _mk_serialized_proposal(negotiation_context: NegotiationContext) -> bytes:
    pass


async def _response_to_msg(msg) -> bytes:
    return bytes()


async def _establish_session_parameters():
    # propose parameters
    local_proposal = _mk_local_proposal(negotiation_context)
    serialized_local_proposal = _mk_serialized_proposal(local_proposal)
    serialized_remote_proposal = await _response_to_msg(serialized_local_proposal)

    remote_proposal = _parse_proposal(serialized_remote_proposal)

    # identify peer
    remote_peer = _peer_from_proposal(remote_proposal)

    # select enc params
    encryption_parameters = _select_encryption_parameters(remote_proposal)

    # exchange ephemeral pub keys
    local_ephemeral_key_pair, shared_key_generator = create_elliptic_key_pair(
        encryption_parameters
    )
    local_selection = _mk_serialized_selection(
        local_proposal, remote_proposal, local_ephemeral_key_pair.public_key
    )
    serialized_local_selection = _mk_serialized_selection(local_selection)

    local_exchange = _mk_exchange(
        local_ephemeral_key_pair.public_key, serialized_local_selection
    )
    serialized_local_exchange = _mk_serialized_exchange_msg(local_exchange)
    serialized_remote_exchange = await _response_to_msg(serialized_local_exchange)

    remote_exchange = _parse_exchange(serialized_remote_exchange)

    remote_selection = _mk_remote_selection(
        remote_exchange, local_proposal, remote_proposal
    )
    verify_exchange(remote_exchange, remote_selection, remote_proposal)

    # return all the data we need


def _mk_session_from(session_parameters):
    # use ephemeral pubkey to make a shared key
    # stretch shared key to get two keys
    # decide which side has which key
    # set up mac and cipher, based on shared key, for each side
    # make new rdr/wtr pairs using each mac/cipher gadget
    pass


async def _close_handshake(session):
    # send nonce over encrypted channel
    # verify we get our nonce back
    pass


async def _run_handshake(negotiation_context: NegotiationContext):
    """
    Attempts the initial `secio` handshake with the remote peer.

    Successfully completing this routine implies ``self``'s instance
    of this session is now ready for secure communication.
    """
    session_parameters = await _establish_session_parameters()

    session = _mk_session_from(session_parameters)

    await _close_handshake(session)

    return session


async def create_secure_session(
    transport: BaseSecureTransport, conn: IRawConnection, remote_peer: PeerID = None
) -> ISecureConn:
    negotiation_context = NegotiationContext(
        transport.local_peer, remote_peer, transport.local_private_key, conn
    )

    return await _run_handshake(negotiation_context)


class SecIOTransport(BaseSecureTransport):
    """
    ``SecIOTransport`` provides a security upgrader for a ``IRawConnection``,
    following the `secio` protocol defined in the libp2p specs.
    """

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        return await create_secure_session(self, conn)

    async def secure_outbound(
        self, conn: IRawConnection, peer_id: PeerID
    ) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        return await create_secure_session(self, conn, peer_id)
