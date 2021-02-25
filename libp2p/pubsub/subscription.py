from types import TracebackType
from typing import AsyncIterator, Optional, Type

import trio

from .abc import ISubscriptionAPI
from .pb import rpc_pb2
from .typing import UnsubscribeFn


class BaseSubscriptionAPI(ISubscriptionAPI):
    async def __aenter__(self) -> "BaseSubscriptionAPI":
        await trio.lowlevel.checkpoint()
        return self

    async def __aexit__(
        self,
        exc_type: "Optional[Type[BaseException]]",
        exc_value: "Optional[BaseException]",
        traceback: "Optional[TracebackType]",
    ) -> None:
        await self.unsubscribe()


class TrioSubscriptionAPI(BaseSubscriptionAPI):
    receive_channel: "trio.MemoryReceiveChannel[rpc_pb2.Message]"
    unsubscribe_fn: UnsubscribeFn

    def __init__(
        self,
        receive_channel: "trio.MemoryReceiveChannel[rpc_pb2.Message]",
        unsubscribe_fn: UnsubscribeFn,
    ) -> None:
        self.receive_channel = receive_channel
        # Ignore type here since mypy complains: https://github.com/python/mypy/issues/2427
        self.unsubscribe_fn = unsubscribe_fn  # type: ignore

    async def unsubscribe(self) -> None:
        # Ignore type here since mypy complains: https://github.com/python/mypy/issues/2427
        await self.unsubscribe_fn()  # type: ignore

    def __aiter__(self) -> AsyncIterator[rpc_pb2.Message]:
        return self.receive_channel.__aiter__()

    async def get(self) -> rpc_pb2.Message:
        return await self.receive_channel.receive()
