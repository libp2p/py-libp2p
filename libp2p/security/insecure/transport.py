from libp2p.crypto.exceptions import MissingDeserializerError
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.pb import crypto_pb2
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.io.abc import ReadWriteCloser
from libp2p.io.msgio import VarIntLengthMsgReadWriter
from libp2p.network.connection.exceptions import RawConnError
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.exceptions import HandshakeFailure
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.typing import TProtocol

from .pb import plaintext_pb2

# Reference: https://github.com/libp2p/go-libp2p-core/blob/master/sec/insecure/insecure.go


PLAINTEXT_PROTOCOL_ID = TProtocol("/plaintext/2.0.0")


class PlaintextHandshakeReadWriter(VarIntLengthMsgReadWriter):
    max_msg_size = 1 << 16


class InsecureSession(BaseSession):
    def __init__(
        self,
        *,
        local_peer: ID,
        local_private_key: PrivateKey,
        remote_peer: ID,
        remote_permanent_pubkey: PublicKey,
        is_initiator: bool,
        conn: ReadWriteCloser,
    ) -> None:
        super().__init__(
            local_peer=local_peer,
            local_private_key=local_private_key,
            remote_peer=remote_peer,
            remote_permanent_pubkey=remote_permanent_pubkey,
            is_initiator=is_initiator,
        )
        self.conn = conn

    async def write(self, data: bytes) -> None:
        await self.conn.write(data)

    async def read(self, n: int = None) -> bytes:
        return await self.conn.read(n)

    async def close(self) -> None:
        await self.conn.close()


async def run_handshake(
    local_peer: ID,
    local_private_key: PrivateKey,
    conn: IRawConnection,
    is_initiator: bool,
    remote_peer_id: ID,
) -> ISecureConn:
    """Raise `HandshakeFailure` when handshake failed."""
    msg = make_exchange_message(local_private_key.get_public_key())
    msg_bytes = msg.SerializeToString()
    read_writer = PlaintextHandshakeReadWriter(conn)
    try:
        await read_writer.write_msg(msg_bytes)
    except RawConnError as e:
        raise HandshakeFailure("connection closed") from e

    try:
        remote_msg_bytes = await read_writer.read_msg()
    except RawConnError as e:
        raise HandshakeFailure("connection closed") from e
    remote_msg = plaintext_pb2.Exchange()
    remote_msg.ParseFromString(remote_msg_bytes)
    received_peer_id = ID(remote_msg.id)

    # Verify if the receive `ID` matches the one we originally initialize the session.
    # We only need to check it when we are the initiator, because only in that condition
    # we possibly knows the `ID` of the remote.
    if is_initiator and remote_peer_id != received_peer_id:
        raise HandshakeFailure(
            "remote peer sent unexpected peer ID. "
            f"expected={remote_peer_id} received={received_peer_id}"
        )

    # Verify if the given `pubkey` matches the given `peer_id`
    try:
        received_pubkey = deserialize_public_key(remote_msg.pubkey.SerializeToString())
    except ValueError as e:
        raise HandshakeFailure(
            f"unknown `key_type` of remote_msg.pubkey={remote_msg.pubkey}"
        ) from e
    except MissingDeserializerError as error:
        raise HandshakeFailure() from error
    peer_id_from_received_pubkey = ID.from_pubkey(received_pubkey)
    if peer_id_from_received_pubkey != received_peer_id:
        raise HandshakeFailure(
            "peer id and pubkey from the remote mismatch: "
            f"received_peer_id={received_peer_id}, remote_pubkey={received_pubkey}, "
            f"peer_id_from_received_pubkey={peer_id_from_received_pubkey}"
        )

    secure_conn = InsecureSession(
        local_peer=local_peer,
        local_private_key=local_private_key,
        remote_peer=received_peer_id,
        remote_permanent_pubkey=received_pubkey,
        is_initiator=is_initiator,
        conn=conn,
    )

    # TODO: Store `pubkey` and `peer_id` to `PeerStore`

    return secure_conn


class InsecureTransport(BaseSecureTransport):
    """``InsecureTransport`` provides the "identity" upgrader for a
    ``IRawConnection``, i.e. the upgraded transport does not add any additional
    security."""

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing
        node via conn, for an inbound connection (i.e. we are not the
        initiator)

        :return: secure connection object (that implements secure_conn_interface)
        """
        return await run_handshake(
            self.local_peer, self.local_private_key, conn, False, None
        )

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing
        node via conn, for an inbound connection (i.e. we are the initiator)

        :return: secure connection object (that implements secure_conn_interface)
        """
        return await run_handshake(
            self.local_peer, self.local_private_key, conn, True, peer_id
        )


def make_exchange_message(pubkey: PublicKey) -> plaintext_pb2.Exchange:
    pubkey_pb = crypto_pb2.PublicKey(
        key_type=pubkey.get_type().value, data=pubkey.to_bytes()
    )
    id_bytes = ID.from_pubkey(pubkey).to_bytes()
    return plaintext_pb2.Exchange(id=id_bytes, pubkey=pubkey_pb)
