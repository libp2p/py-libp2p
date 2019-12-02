import asyncio

import pytest

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.secio.transport import NONCE_SIZE, create_secure_session


class InMemoryConnection(IRawConnection):
    def __init__(self, peer, is_initiator=False):
        self.peer = peer
        self.recv_queue = asyncio.Queue()
        self.send_queue = asyncio.Queue()
        self.is_initiator = is_initiator

        self.current_msg = None
        self.current_position = 0

        self.closed = False

    async def write(self, data: bytes) -> int:
        if self.closed:
            raise Exception("InMemoryConnection is closed for writing")

        await self.send_queue.put(data)
        return len(data)

    async def read(self, n: int = -1) -> bytes:
        """
        NOTE: have to buffer the current message and juggle packets
        off the recv queue to satisfy the semantics of this function.
        """
        if self.closed:
            raise Exception("InMemoryConnection is closed for reading")

        if not self.current_msg:
            self.current_msg = await self.recv_queue.get()
            self.current_position = 0

        if n < 0:
            msg = self.current_msg
            self.current_msg = None
            return msg

        next_msg = self.current_msg[self.current_position : self.current_position + n]
        self.current_position += n
        if self.current_position == len(self.current_msg):
            self.current_msg = None
        return next_msg

    async def close(self) -> None:
        self.closed = True


async def create_pipe(local_conn, remote_conn):
    try:
        while True:
            next_msg = await local_conn.send_queue.get()
            await remote_conn.recv_queue.put(next_msg)
    except asyncio.CancelledError:
        return


@pytest.mark.asyncio
async def test_create_secure_session():
    local_nonce = b"\x01" * NONCE_SIZE
    local_key_pair = create_new_key_pair(b"a")
    local_peer = ID.from_pubkey(local_key_pair.public_key)

    remote_nonce = b"\x02" * NONCE_SIZE
    remote_key_pair = create_new_key_pair(b"b")
    remote_peer = ID.from_pubkey(remote_key_pair.public_key)

    local_conn = InMemoryConnection(local_peer, is_initiator=True)
    remote_conn = InMemoryConnection(remote_peer)

    local_pipe_task = asyncio.ensure_future(create_pipe(local_conn, remote_conn))
    remote_pipe_task = asyncio.ensure_future(create_pipe(remote_conn, local_conn))

    local_session_builder = create_secure_session(
        local_nonce, local_peer, local_key_pair.private_key, local_conn, remote_peer
    )
    remote_session_builder = create_secure_session(
        remote_nonce, remote_peer, remote_key_pair.private_key, remote_conn
    )
    local_secure_conn, remote_secure_conn = await asyncio.gather(
        local_session_builder, remote_session_builder
    )

    msg = b"abc"
    await local_secure_conn.write(msg)
    received_msg = await remote_secure_conn.read()
    assert received_msg == msg

    await asyncio.gather(local_secure_conn.close(), remote_secure_conn.close())

    local_pipe_task.cancel()
    remote_pipe_task.cancel()
    await local_pipe_task
    await remote_pipe_task
