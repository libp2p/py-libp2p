from asyncio import StreamReader, StreamWriter
from typing import Callable

THandler = Callable[[StreamReader, StreamWriter], None]
