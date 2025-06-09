import pytest
import trio

from libp2p.abc import ISecureConn
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.security.secio.transport import (
    NONCE_SIZE,
    create_secure_session,
)
from libp2p.tools.constants import (
    MAX_READ_LEN,
)
from tests.utils.factories import (
    raw_conn_factory,
)


@pytest.mark.trio
async def test_create_secure_session(nursery):
    local_nonce = b"\x01" * NONCE_SIZE
    local_key_pair = create_new_key_pair(b"a")
    local_peer = ID.from_pubkey(local_key_pair.public_key)

    remote_nonce = b"\x02" * NONCE_SIZE
    remote_key_pair = create_new_key_pair(b"b")
    remote_peer = ID.from_pubkey(remote_key_pair.public_key)

    async with raw_conn_factory(nursery) as conns:
        local_conn, remote_conn = conns

        local_secure_conn: ISecureConn | None = None
        remote_secure_conn: ISecureConn | None = None

        async def local_create_secure_session():
            nonlocal local_secure_conn
            local_secure_conn = await create_secure_session(
                local_nonce,
                local_peer,
                local_key_pair.private_key,
                local_conn,
                remote_peer,
            )

        async def remote_create_secure_session():
            nonlocal remote_secure_conn
            remote_secure_conn = await create_secure_session(
                remote_nonce, remote_peer, remote_key_pair.private_key, remote_conn
            )

        async with trio.open_nursery() as nursery_1:
            nursery_1.start_soon(local_create_secure_session)
            nursery_1.start_soon(remote_create_secure_session)

        if local_secure_conn is None or remote_secure_conn is None:
            raise Exception("Failed to secure connection")

        msg = b"abc"
        await local_secure_conn.write(msg)
        received_msg = await remote_secure_conn.read(MAX_READ_LEN)
        assert received_msg == msg
