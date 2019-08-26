from dataclasses import dataclass
from typing import Optional, Tuple

import multihash

from libp2p.crypto.authenticated_encryption import (
    EncryptionParameters as AuthenticatedEncryptionParameters,
)
from libp2p.crypto.authenticated_encryption import (
    initialize_pair as initialize_pair_for_encryption,
)
from libp2p.crypto.authenticated_encryption import MacAndCipher as Encrypter
from libp2p.crypto.ecc import ECCPublicKey
from libp2p.crypto.key_exchange import create_ephemeral_key_pair
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.io.msgio import encode as encode_message
from libp2p.io.msgio import read_next_message
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID as PeerID
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.secure_conn_interface import ISecureConn

from .exceptions import (
    HandshakeFailed,
    IncompatibleChoices,
    InvalidSignatureOnExchange,
    PeerMismatchException,
    SecioException,
    SelfEncryption,
)
from .pb.spipe_pb2 import Exchange, Propose

ID = "/secio/1.0.0"

NONCE_SIZE = 16  # bytes

# NOTE: the following is only a subset of allowable parameters according to the
# `secio` specification.
DEFAULT_SUPPORTED_EXCHANGES = "P-256"
DEFAULT_SUPPORTED_CIPHERS = "AES-128"
DEFAULT_SUPPORTED_HASHES = "SHA256"


class SecureSession(BaseSession):
    def __init__(
        self,
        local_peer: PeerID,
        local_private_key: PrivateKey,
        local_encryption_parameters: AuthenticatedEncryptionParameters,
        remote_peer: PeerID,
        remote_encryption_parameters: AuthenticatedEncryptionParameters,
        conn: IRawConnection,
    ) -> None:
        super().__init__(local_peer, local_private_key, conn, remote_peer)

        self.local_encryption_parameters = local_encryption_parameters
        self.remote_encryption_parameters = remote_encryption_parameters
        self._initialize_authenticated_encryption_for_local_peer()
        self._initialize_authenticated_encryption_for_remote_peer()

    def _initialize_authenticated_encryption_for_local_peer(self) -> None:
        self.local_encrypter = Encrypter(self.local_encryption_parameters)

    def _initialize_authenticated_encryption_for_remote_peer(self) -> None:
        self.remote_encrypter = Encrypter(self.remote_encryption_parameters)

    async def read(self, n: int = -1) -> bytes:
        return await self._read_msg()

    async def _read_msg(self) -> bytes:
        # TODO do we need to serialize reads?
        msg = await read_next_message(self.conn)
        return self.remote_encrypter.decrypt_if_valid(msg)

    async def write(self, data: bytes) -> None:
        await self._write_msg(data)

    async def _write_msg(self, data: bytes) -> None:
        # TODO do we need to serialize writes?
        encrypted_data = self.local_encrypter.encrypt(data)
        tag = self.local_encrypter.authenticate(encrypted_data)
        msg = encode_message(encrypted_data + tag)
        await self.conn.write(msg)


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
            rand=self.nonce,
            public_key=self.public_key.serialize(),
            exchanges=self.exchanges,
            ciphers=self.ciphers,
            hashes=self.hashes,
        )
        return protobuf.SerializeToString()

    @classmethod
    def deserialize(cls, protobuf_bytes: bytes) -> "Proposal":
        protobuf = Propose.FromString(protobuf_bytes)

        nonce = protobuf.rand
        public_key_protobuf_bytes = protobuf.public_key
        public_key = deserialize_public_key(public_key_protobuf_bytes)
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

    def __init__(self) -> None:
        pass


@dataclass
class SessionParameters:
    local_peer: PeerID
    local_encryption_parameters: EncryptionParameters

    remote_peer: PeerID
    remote_encryption_parameters: EncryptionParameters

    # order is a comparator used to break the symmetry b/t each pair of peers
    order: int
    shared_key: bytes

    def __init__(self) -> None:
        pass


async def _response_to_msg(conn: IRawConnection, msg: bytes) -> bytes:
    await conn.write(encode_message(msg))
    return await read_next_message(conn)


def _mk_multihash_sha256(data: bytes) -> bytes:
    return multihash.digest(data, "sha2-256")


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
    raise IncompatibleChoices()


def _select_encryption_parameters(
    local_proposal: Proposal, remote_proposal: Proposal
) -> Tuple[str, str, str, int]:
    first_score = _mk_score(remote_proposal.public_key, local_proposal.nonce)
    second_score = _mk_score(local_proposal.public_key, remote_proposal.nonce)

    order = 0
    if first_score < second_score:
        order = -1
    elif second_score < first_score:
        order = 1

    if order == 0:
        raise SelfEncryption()

    return (
        _select_parameter_from_order(
            order, DEFAULT_SUPPORTED_EXCHANGES, remote_proposal.exchanges
        ),
        _select_parameter_from_order(
            order, DEFAULT_SUPPORTED_CIPHERS, remote_proposal.ciphers
        ),
        _select_parameter_from_order(
            order, DEFAULT_SUPPORTED_HASHES, remote_proposal.hashes
        ),
        order,
    )


async def _establish_session_parameters(
    local_peer: PeerID,
    local_private_key: PrivateKey,
    remote_peer: Optional[PeerID],
    conn: IRawConnection,
    nonce: bytes,
) -> Tuple[SessionParameters, bytes]:
    # establish shared encryption parameters
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

    curve_param, cipher_param, hash_param, order = _select_encryption_parameters(
        local_proposal, remote_proposal
    )
    local_encryption_parameters.curve_type = curve_param
    local_encryption_parameters.cipher_type = cipher_param
    local_encryption_parameters.hash_type = hash_param
    remote_encryption_parameters.curve_type = curve_param
    remote_encryption_parameters.cipher_type = cipher_param
    remote_encryption_parameters.hash_type = hash_param
    session_parameters.order = order

    # exchange ephemeral pub keys
    local_ephemeral_public_key, shared_key_generator = create_ephemeral_key_pair(
        curve_param
    )
    local_encryption_parameters.ephemeral_public_key = local_ephemeral_public_key
    local_selection = (
        serialized_local_proposal
        + serialized_remote_proposal
        + local_ephemeral_public_key.to_bytes()
    )
    exchange_signature = local_private_key.sign(local_selection)
    local_exchange = Exchange(
        ephemeral_public_key=local_ephemeral_public_key.to_bytes(),
        signature=exchange_signature,
    )

    serialized_local_exchange = local_exchange.SerializeToString()
    serialized_remote_exchange = await _response_to_msg(conn, serialized_local_exchange)

    remote_exchange = Exchange()
    remote_exchange.ParseFromString(serialized_remote_exchange)

    remote_ephemeral_public_key_bytes = remote_exchange.ephemeral_public_key
    remote_ephemeral_public_key = ECCPublicKey.from_bytes(
        remote_ephemeral_public_key_bytes
    )
    remote_encryption_parameters.ephemeral_public_key = remote_ephemeral_public_key
    remote_selection = (
        serialized_remote_proposal
        + serialized_local_proposal
        + remote_ephemeral_public_key_bytes
    )
    valid_signature = remote_encryption_parameters.permanent_public_key.verify(
        remote_selection, remote_exchange.signature
    )
    if not valid_signature:
        raise InvalidSignatureOnExchange()

    shared_key = shared_key_generator(remote_ephemeral_public_key_bytes)
    session_parameters.shared_key = shared_key

    return session_parameters, remote_proposal.nonce


def _mk_session_from(
    local_private_key: PrivateKey,
    session_parameters: SessionParameters,
    conn: IRawConnection,
) -> SecureSession:
    key_set1, key_set2 = initialize_pair_for_encryption(
        session_parameters.local_encryption_parameters.cipher_type,
        session_parameters.local_encryption_parameters.hash_type,
        session_parameters.shared_key,
    )

    if session_parameters.order < 0:
        key_set1, key_set2 = key_set2, key_set1

    session = SecureSession(
        session_parameters.local_peer,
        local_private_key,
        key_set1,
        session_parameters.remote_peer,
        key_set2,
        conn,
    )
    return session


async def _finish_handshake(session: ISecureConn, remote_nonce: bytes) -> bytes:
    await session.write(remote_nonce)
    return await session.read()


async def create_secure_session(
    local_nonce: bytes,
    local_peer: PeerID,
    local_private_key: PrivateKey,
    conn: IRawConnection,
    remote_peer: PeerID = None,
) -> ISecureConn:
    """
    Attempt the initial `secio` handshake with the remote peer.
    If successful, return an object that provides secure communication to the
    ``remote_peer``.
    """
    try:
        session_parameters, remote_nonce = await _establish_session_parameters(
            local_peer, local_private_key, remote_peer, conn, local_nonce
        )
    except SecioException as e:
        await conn.close()
        raise e

    session = _mk_session_from(local_private_key, session_parameters, conn)

    received_nonce = await _finish_handshake(session, remote_nonce)
    if received_nonce != local_nonce:
        await conn.close()
        raise HandshakeFailed()

    return session


class Transport(BaseSecureTransport):
    """
    ``Transport`` provides a security upgrader for a ``IRawConnection``,
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
        local_nonce = self.get_nonce()
        local_peer = self.local_peer
        local_private_key = self.local_private_key

        return await create_secure_session(
            local_nonce, local_peer, local_private_key, conn
        )

    async def secure_outbound(
        self, conn: IRawConnection, peer_id: PeerID
    ) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        local_nonce = self.get_nonce()
        local_peer = self.local_peer
        local_private_key = self.local_private_key

        return await create_secure_session(
            local_nonce, local_peer, local_private_key, conn, peer_id
        )
