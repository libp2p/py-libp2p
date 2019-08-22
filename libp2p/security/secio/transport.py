from dataclasses import dataclass
from typing import Optional, Tuple

from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.io.msgio import encode as encode_message
from libp2p.io.msgio import read_next_message
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID as PeerID
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.secure_conn_interface import ISecureConn

from .pb.spipe_pb2 import Exchange, Propose

ID = "/secio/1.0.0"

NONCE_SIZE = 16  # bytes

# NOTE: the following is only a subset of allowable parameters according to the
# `secio` specification.
DEFAULT_SUPPORTED_EXCHANGES = "P-256"
DEFAULT_SUPPORTED_CIPHERS = "AES-128"
DEFAULT_SUPPORTED_HASHES = "SHA256"


class SecureSession(BaseSession):
    local_peer: PeerID
    remote_peer: PeerID
    # specialize read and write
    pass


@dataclass(frozen=True)
class Proposal:
    """
    A ``Proposal`` represents the set of session parameters one peer in a pair of
    peers attempting to negotiate a `secio` channel prefers.
    """

    nonce: bytes
    public_key: PublicKey
    exchanges: str = DEFAULT_SUPPORTED_EXCHANGES  # comma separated list
    ciphers: str = DEFAULT_SUPPORTED_CIPHERS  # comma separated list
    hashes: str = DEFAULT_SUPPORTED_HASHES  # comma separated list

    def serialize(self) -> bytes:
        protobuf = Propose(
            self.nonce,
            self.public_key.serialize(),
            self.exchanges,
            self.ciphers,
            self.hashes,
        )
        return protobuf.SerializeToString()

    @classmethod
    def deserialize(cls, protobuf_bytes: bytes) -> "Proposal":
        protobuf = Propose()
        protobuf.ParseFromString(protobuf_bytes)

        nonce = protobuf.rand
        public_key_protobuf_bytes = protobuf.public_key
        # TODO (ralexstokes) handle genericity in the deserialization
        public_key = PublicKey.deserialize(public_key_protobuf_bytes)
        exchanges = protobuf.exchanges
        ciphers = protobuf.ciphers
        hashes = protobuf.hashes

        return cls(nonce, public_key, exchanges, ciphers, hashes)

    def calculate_peer_id(self) -> PeerID:
        return PeerID.from_pubkey(self.public_key)


@dataclass
class EncryptionParameters:
    permanent_public_key: PublicKey

    curve_type: str
    cipher_type: str
    hash_type: str

    ephemeral_public_key: PublicKey
    keys: ...
    cipher: ...
    mac: ...


async def _response_to_msg(conn: IRawConnection, msg: bytes) -> bytes:
    # TODO clean up ``IRawConnection`` so that we don't have to break
    # the abstraction
    conn.writer.write(encode_message(msg))
    await conn.writer.drain()

    return await read_next_message(conn.reader)


@dataclass
class SessionParameters:
    local_peer: PeerID
    local_encryption_parameters: EncryptionParameters
    remote_peer: PeerID
    remote_encryption_parameters: EncryptionParameters


def _mk_multihash_sha256(data: bytes) -> bytes:
    pass


def _mk_score(public_key: PublicKey, nonce: bytes) -> bytes:
    return _mk_multihash_sha256(public_key.serialize() + nonce)


def _select_parameter_from_order(
    order: int, supported_parameters: str, available_parameters: str
) -> str:
    if order < 0:
        first_choices = available_parameters.split(",")
        second_choices = supported_parameters.split(",")
    elif order > 0:
        first_choices = supported_parameters.split(",")
        second_choices = available_parameters.split(",")
    else:
        return supported_parameters.split(",")[0]

    for first, second in zip(first_choices, second_choices):
        if first == second:
            return first


def _select_encryption_parameters(
    local_proposal: Proposal, remote_proposal: Proposal
) -> Tuple[str, str, str]:
    first_score = _mk_score(remote_proposal.public_key, local_proposal.nonce)
    second_score = _mk_score(local_proposal.public_key, remote_proposal.nonce)

    order = 0
    if first_score < second_score:
        order = -1
    elif second_score < first_score:
        order = 1

    # NOTE: if order is 0, "talking to self"
    # TODO(ralexstokes) nicer error handling here...
    assert order != 0

    return (
        _select_parameter_from_order(
            order, DEFAULT_SUPPORTED_EXCHANGES, remote_proposal.exchanges
        ),
        _select_encryption_parameters(
            order, DEFAULT_SUPPORTED_CIPHERS, remote_proposal.ciphers
        ),
        _select_encryption_parameters(
            order, DEFAULT_SUPPORTED_HASHES, remote_proposal.hashes
        ),
    )


async def _establish_session_parameters(
    local_peer: PeerID,
    local_private_key: PrivateKey,
    remote_peer: Optional[PeerID],
    conn: IRawConnection,
    nonce: bytes,
) -> SessionParameters:
    session_parameters = SessionParameters()
    session_parameters.local_peer = local_peer

    local_encryption_parameters = EncryptionParameters()
    session_parameters.local_encryption_parameters = local_encryption_parameters

    local_public_key = local_private_key.get_public_key()
    local_encryption_parameters.permanent_public_key = local_public_key

    local_proposal = Proposal(nonce, local_public_key)
    serialized_local_proposal = local_proposal.serialize()
    serialized_remote_proposal = await _response_to_msg(conn, serialized_local_proposal)

    remote_encryption_parameters = EncryptionParameters()
    session_parameters.remote_encryption_parameters = remote_encryption_parameters
    remote_proposal = Proposal.deserialize(serialized_remote_proposal)
    remote_encryption_parameters.permanent_public_key = remote_proposal.public_key

    remote_peer_from_proposal = remote_proposal.calculate_peer_id()
    if not remote_peer:
        remote_peer = remote_peer_from_proposal
    elif remote_peer != remote_peer_from_proposal:
        raise PeerMismatchException()
    session_parameters.remote_peer = remote_peer

    curve_param, cipher_param, hash_param = _select_encryption_parameters(
        local_proposal, remote_proposal
    )
    local_encryption_parameters.curve_type = curve_param
    local_encryption_parameters.cipher_type = cipher_param
    local_encryption_parameters.hash_type = hash_param
    remote_encryption_parameters.curve_type = curve_param
    remote_encryption_parameters.cipher_type = cipher_param
    remote_encryption_parameters.hash_type = hash_param

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


async def create_secure_session(
    transport: BaseSecureTransport, conn: IRawConnection, remote_peer: PeerID = None
) -> ISecureConn:
    """
    Attempt the initial `secio` handshake with the remote peer.
    If successful, return an object that provides secure communication to the
    ``remote_peer``.
    """
    nonce = transport.get_nonce()
    local_peer = transport.local_peer
    local_private_key = transport.local_private_key

    try:
        session_parameters = await _establish_session_parameters(
            local_peer, local_private_key, remote_peer, conn, nonce
        )
    except PeerMismatchException as e:
        conn.close()
        raise e

    session = _mk_session_from(session_parameters)

    await _close_handshake(session)

    return session


class SecIOTransport(BaseSecureTransport):
    """
    ``SecIOTransport`` provides a security upgrader for a ``IRawConnection``,
    following the `secio` protocol defined in the libp2p specs.
    """

    def get_nonce(self) -> bytes:
        return self.secure_bytes_provider(NONCE_SIZE)

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
