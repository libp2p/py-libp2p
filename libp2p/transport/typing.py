from asyncio import StreamReader, StreamWriter
from typing import NewType, Callable


THandler = Callable[[StreamReader, StreamWriter], None]
