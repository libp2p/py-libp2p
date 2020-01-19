from types import TracebackType
from typing import AsyncIterator, Optional, Type

import trio

from .abc import ISubscriptionAPI
from .pb import rpc_pb2


class BaseSubscriptionAPI(ISubscriptionAPI):
    async def __aenter__(self) -> "BaseSubscriptionAPI":
        await trio.hazmat.checkpoint()
        return self

    async def __aexit__(
        self,
        exc_type: "Optional[Type[BaseException]]",
        exc_value: "Optional[BaseException]",
        traceback: "Optional[TracebackType]",
    ) -> None:
        await self.cancel()


class TrioSubscriptionAPI(BaseSubscriptionAPI):
    receive_channel: "trio.MemoryReceiveChannel[rpc_pb2.Message]"

    def __init__(
        self, receive_channel: "trio.MemoryReceiveChannel[rpc_pb2.Message]"
    ) -> None:
        self.receive_channel = receive_channel

    async def cancel(self) -> None:
        await self.receive_channel.aclose()

    def __aiter__(self) -> AsyncIterator[rpc_pb2.Message]:
        return self.receive_channel.__aiter__()

    async def get(self) -> rpc_pb2.Message:
        return await self.receive_channel.receive()
