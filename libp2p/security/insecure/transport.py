from libp2p.crypto.keys import PublicKey
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.transport.exceptions import SecurityUpgradeFailure
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

        msg_bytes_other_side = await read_fixedint_prefixed(self.conn)
        msg_other_side = plaintext_pb2.Exchange()
        msg_other_side.ParseFromString(msg_bytes_other_side)

        # TODO: Verify public key with peer id
        # TODO: Store public key
        self.remote_peer_id = ID(msg_other_side.id)


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
        # TODO: Check if `remote_public_key is not None`. If so, check if `session.remote_peer`
        received_peer_id = session.get_remote_peer()
        if received_peer_id != peer_id:
            raise SecurityUpgradeFailure(
                "remote peer sent unexpected peer ID. "
                f"expected={peer_id} received={received_peer_id}"
            )
        return session


def make_exchange_message(pubkey: PublicKey) -> plaintext_pb2.Exchange:
    pubkey_pb = pubkey.serialize_to_protobuf()
    id_bytes = ID.from_pubkey(pubkey).to_bytes()
    return plaintext_pb2.Exchange(id=id_bytes, pubkey=pubkey_pb)
