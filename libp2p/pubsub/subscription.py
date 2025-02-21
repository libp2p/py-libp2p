from collections.abc import (
    AsyncIterator,
)
from types import (
    TracebackType,
)
from typing import (
    Optional,
    Type,
)

import trio

from libp2p.abc import (
    ISubscriptionAPI,
)
from libp2p.custom_types import (
    UnsubscribeFn,
)

from .pb import (
    rpc_pb2,
)


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
        self.unsubscribe_fn = unsubscribe_fn

    async def unsubscribe(self) -> None:
        await self.unsubscribe_fn()

    def __aiter__(self) -> AsyncIterator[rpc_pb2.Message]:
        return self.receive_channel.__aiter__()

    async def get(self) -> rpc_pb2.Message:
        return await self.receive_channel.receive()
