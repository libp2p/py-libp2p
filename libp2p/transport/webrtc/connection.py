import logging
from typing import (
    Any,
)

from aiortc import (
    RTCDataChannel,
)
import trio
from trio import (
    MemoryReceiveChannel,
    MemorySendChannel,
)

from libp2p.abc import (
    IRawConnection,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.stream_muxer.mplex.mplex import (
    Mplex,
)

logger = logging.getLogger("webrtc")
logging.basicConfig(level=logging.INFO)


class WebRTCRawConnection(IRawConnection):
    def __init__(self, peer_id: ID, channel: RTCDataChannel):
        self.peer_id = peer_id
        self.channel = channel
        self.send_channel: MemorySendChannel[Any]
        self.receive_channel: MemoryReceiveChannel[Any]
        self.send_channel, self.receive_channel = trio.open_memory_channel(50)

        @channel.on("message")
        def on_message(message: Any) -> None:
            self.send_channel.send_nowait(message)

        self.mplex = Mplex(self, self.peer_id)

    def _send_func(self, data: bytes) -> None:
        self.channel.send(data)

    async def _recv_func(self) -> bytes:
        return await self.receive_channel.receive()

    async def open_stream(self) -> Any:
        return await self.mplex.open_stream()

    async def accept_stream(self) -> Any:
        return await self.mplex.accept_stream()

    async def read(self, n: int = -1) -> bytes:
        return await self.receive_channel.receive()

    async def write(self, data: bytes) -> None:
        self.channel.send(data)

    def get_remote_address(self) -> tuple[str, int] | None:
        return self.get_remote_address()

    async def close(self) -> None:
        self.channel.close()
        await self.send_channel.aclose()
        await self.receive_channel.aclose()
        await self.mplex.close()

    def get_local_peer(self) -> ID:
        return self.get_local_peer()

    def get_local_private_key(self) -> Any:
        return self.get_local_private_key()

    def get_remote_peer(self) -> ID:
        return self.get_remote_peer()

    def get_remote_public_key(self) -> Any:
        return self.get_remote_public_key()
