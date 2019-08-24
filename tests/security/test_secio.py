import asyncio

import pytest

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.secio.transport import NONCE_SIZE, create_secure_session


class InMemoryConnection(IRawConnection):
    def __init__(self, peer, initiator=False):
        self.peer = peer
        self.recv_queue = asyncio.Queue()
        self.send_queue = asyncio.Queue()
        self.initiator = initiator

        self.current_msg = None
        self.current_position = 0

        self.closed = False
        self.stream_counter = 0

    @property
    def writer(self):
        return self

    @property
    def reader(self):
        return self

    async def write(self, data: bytes) -> None:
        if self.closed:
            raise Exception("InMemoryConnection is closed for writing")

        await self.send_queue.put(data)

    async def drain(self):
        return

    async def readexactly(self, n):
        return await self.read(n)

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

    def close(self) -> None:
        self.closed = True

    def next_stream_id(self) -> int:
        self.stream_counter += 1
        return self.stream_counter


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

    local_conn = InMemoryConnection(local_peer, initiator=True)
    remote_conn = InMemoryConnection(remote_peer)

    local_pipe_task = asyncio.create_task(create_pipe(local_conn, remote_conn))
    remote_pipe_task = asyncio.create_task(create_pipe(remote_conn, local_conn))

    local_session_builder = create_secure_session(
        local_nonce, local_peer, local_key_pair.private_key, local_conn, remote_peer
    )
    remote_session_builder = create_secure_session(
        remote_nonce, remote_peer, remote_key_pair.private_key, remote_conn
    )
    local_secure_conn, remote_secure_conn = await asyncio.gather(
        local_session_builder, remote_session_builder
    )

    local_pipe_task.cancel()
    remote_pipe_task.cancel()
    await local_pipe_task
    await remote_pipe_task

    assert local_secure_conn
    assert remote_secure_conn


if __name__ == "__main__":
    asyncio.run(test_create_secure_session())
