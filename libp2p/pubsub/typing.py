from typing import Awaitable, Callable, Union

from libp2p.peer.id import ID

from .pb import rpc_pb2

SyncValidatorFn = Callable[[ID, rpc_pb2.Message], bool]
AsyncValidatorFn = Callable[[ID, rpc_pb2.Message], Awaitable[bool]]
ValidatorFn = Union[SyncValidatorFn, AsyncValidatorFn]

UnsubscribeFn = Callable[[], Awaitable[None]]
