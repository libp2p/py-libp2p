from unittest.mock import (
    Mock,
)

import pytest

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.io.abc import (
    EncryptedMsgReadWriter,
)
from libp2p.io.exceptions import (
    ConnectionClosedError,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.security.secure_session import (
    SecureSession,
)


class EmptyEOFConn(EncryptedMsgReadWriter):
    async def read_msg(self) -> bytes:
        return b""

    async def write_msg(self, msg: bytes) -> None:
        return None

    async def close(self) -> None:
        return None

    def encrypt(self, data: bytes) -> bytes:
        return data

    def decrypt(self, data: bytes) -> bytes:
        return data

    def get_remote_address(self):
        return None


@pytest.mark.trio
async def test_secure_session_eof_raises_connection_closed_error():
    session = SecureSession(
        local_peer=ID(b"local"),
        local_private_key=Mock(spec=PrivateKey),
        remote_peer=ID(b"remote"),
        remote_permanent_pubkey=Mock(spec=PublicKey),
        is_initiator=True,
        conn=EmptyEOFConn(),
    )
    with pytest.raises(ConnectionClosedError, match="Connection closed"):
        await session.read()

    with pytest.raises(ConnectionClosedError, match="Connection closed"):
        await session.read(16)
