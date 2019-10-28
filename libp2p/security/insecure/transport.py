from typing import Optional

from libp2p.crypto.exceptions import MissingDeserializerError
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.pb import crypto_pb2
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.io.abc import ReadWriteCloser
from libp2p.network.connection.exceptions import RawConnError
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.exceptions import HandshakeFailure
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.typing import TProtocol
from libp2p.utils import encode_fixedint_prefixed, read_fixedint_prefixed

from .pb import plaintext_pb2

# Reference: https://github.com/libp2p/go-libp2p-core/blob/master/sec/insecure/insecure.go


PLAINTEXT_PROTOCOL_ID = TProtocol("/plaintext/2.0.0")


class InsecureSession(BaseSession):
    def __init__(
        self,
        local_peer: ID,
        local_private_key: PrivateKey,
        conn: ReadWriteCloser,
        is_initiator: bool,
        peer_id: Optional[ID] = None,
    ) -> None:
        super().__init__(local_peer, local_private_key, is_initiator, peer_id)
        self.conn = conn

    async def write(self, data: bytes) -> int:
        await self.conn.write(data)
        return len(data)

    async def read(self, n: int = -1) -> bytes:
        return await self.conn.read(n)

    async def close(self) -> None:
        await self.conn.close()

    async def run_handshake(self) -> None:
        """Raise `HandshakeFailure` when handshake failed."""
        msg = make_exchange_message(self.local_private_key.get_public_key())
        msg_bytes = msg.SerializeToString()
        encoded_msg_bytes = encode_fixedint_prefixed(msg_bytes)
        try:
            await self.write(encoded_msg_bytes)
        except RawConnError:
            raise HandshakeFailure("connection closed")

        try:
            remote_msg_bytes = await read_fixedint_prefixed(self.conn)
        except RawConnError:
            raise HandshakeFailure("connection closed")
        remote_msg = plaintext_pb2.Exchange()
        remote_msg.ParseFromString(remote_msg_bytes)
        received_peer_id = ID(remote_msg.id)

        # Verify if the receive `ID` matches the one we originally initialize the session.
        # We only need to check it when we are the initiator, because only in that condition
        # we possibly knows the `ID` of the remote.
        if self.is_initiator and self.remote_peer_id != received_peer_id:
            raise HandshakeFailure(
                "remote peer sent unexpected peer ID. "
                f"expected={self.remote_peer_id} received={received_peer_id}"
            )

        # Verify if the given `pubkey` matches the given `peer_id`
        try:
            received_pubkey = deserialize_public_key(
                remote_msg.pubkey.SerializeToString()
            )
        except ValueError:
            raise HandshakeFailure(
                f"unknown `key_type` of remote_msg.pubkey={remote_msg.pubkey}"
            )
        except MissingDeserializerError as error:
            raise HandshakeFailure(error)
        peer_id_from_received_pubkey = ID.from_pubkey(received_pubkey)
        if peer_id_from_received_pubkey != received_peer_id:
            raise HandshakeFailure(
                "peer id and pubkey from the remote mismatch: "
                f"received_peer_id={received_peer_id}, remote_pubkey={received_pubkey}, "
                f"peer_id_from_received_pubkey={peer_id_from_received_pubkey}"
            )

        # Nothing is wrong. Store the `pubkey` and `peer_id` in the session.
        self.remote_permanent_pubkey = received_pubkey
        # Only need to set peer's id when we don't know it before,
        # i.e. we are not the connection initiator.
        if not self.is_initiator:
            self.remote_peer_id = received_peer_id

        # TODO: Store `pubkey` and `peer_id` to `PeerStore`


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
        session = InsecureSession(self.local_peer, self.local_private_key, conn, False)
        await session.run_handshake()
        return session

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing
        node via conn, for an inbound connection (i.e. we are the initiator)

        :return: secure connection object (that implements secure_conn_interface)
        """
        session = InsecureSession(
            self.local_peer, self.local_private_key, conn, True, peer_id
        )
        await session.run_handshake()
        return session


def make_exchange_message(pubkey: PublicKey) -> plaintext_pb2.Exchange:
    pubkey_pb = crypto_pb2.PublicKey(
        key_type=pubkey.get_type().value, data=pubkey.to_bytes()
    )
    id_bytes = ID.from_pubkey(pubkey).to_bytes()
    return plaintext_pb2.Exchange(id=id_bytes, pubkey=pubkey_pb)
