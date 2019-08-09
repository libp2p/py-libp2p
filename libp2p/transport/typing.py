from asyncio import StreamReader, StreamWriter
from typing import Callable, Awaitable

THandler = Callable[[StreamReader, StreamWriter], Awaitable[None]]
