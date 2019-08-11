from asyncio import StreamReader, StreamWriter
from typing import Awaitable, Callable

THandler = Callable[[StreamReader, StreamWriter], Awaitable[None]]
