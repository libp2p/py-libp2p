from libp2p.crypto.keys import PublicKey
from libp2p.crypto.pb import crypto_pb2
from libp2p.crypto.utils import pubkey_from_protobuf
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.transport.exceptions import HandshakeFailure
from libp2p.typing import TProtocol
from libp2p.utils import encode_fixedint_prefixed, read_fixedint_prefixed

from .pb import plaintext_pb2

# Reference: https://github.com/libp2p/go-libp2p-core/blob/master/sec/insecure/insecure.go


PLAINTEXT_PROTOCOL_ID = TProtocol("/plaintext/2.0.0")


class InsecureSession(BaseSession):
    async def run_handshake(self):
        msg = make_exchange_message(self.local_private_key.get_public_key())
        msg_bytes = msg.SerializeToString()
        encoded_msg_bytes = encode_fixedint_prefixed(msg_bytes)
        await self.write(encoded_msg_bytes)

        remote_msg_bytes = await read_fixedint_prefixed(self.conn)
        remote_msg = plaintext_pb2.Exchange()
        remote_msg.ParseFromString(remote_msg_bytes)

        # Verify if the given `pubkey` matches the given `peer_id`
        try:
            remote_pubkey = pubkey_from_protobuf(remote_msg.pubkey)
        except ValueError:
            raise HandshakeFailure(
                f"unknown `key_type` of remote_msg.pubkey={remote_msg.pubkey}"
            )
        remote_peer_id = ID(remote_msg.id)
        remote_peer_id_from_pubkey = ID.from_pubkey(remote_pubkey)
        if remote_peer_id_from_pubkey != remote_peer_id:
            raise HandshakeFailure(
                "peer id and pubkey from the remote mismatch: "
                f"remote_peer_id={remote_peer_id}, remote_pubkey={remote_pubkey}, "
                f"remote_peer_id_from_pubkey={remote_peer_id_from_pubkey}"
            )

        # Nothing is wrong. Store the `pubkey` and `peer_id` in the session.
        self.remote_permanent_pubkey = remote_pubkey
        self.remote_peer_id = ID(remote_msg.id)

        # TODO: Store `pubkey` and `peer_id` to `PeerStore`


class InsecureTransport(BaseSecureTransport):
    """
    ``InsecureTransport`` provides the "identity" upgrader for a ``IRawConnection``,
    i.e. the upgraded transport does not add any additional security.
    """

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        session = InsecureSession(self, conn, ID(b""))
        await session.run_handshake()
        return session

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        session = InsecureSession(self, conn, peer_id)
        await session.run_handshake()
        received_peer_id = session.get_remote_peer()
        if session.remote_permanent_pubkey is not None and received_peer_id != peer_id:
            raise HandshakeFailure(
                "remote peer sent unexpected peer ID. "
                f"expected={peer_id} received={received_peer_id}"
            )
        return session


def make_exchange_message(pubkey: PublicKey) -> plaintext_pb2.Exchange:
    pubkey_pb = crypto_pb2.PublicKey(
        key_type=pubkey.get_type().value, data=pubkey.to_bytes()
    )
    id_bytes = ID.from_pubkey(pubkey).to_bytes()
    return plaintext_pb2.Exchange(id=id_bytes, pubkey=pubkey_pb)
