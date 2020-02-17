from abc import ABC, abstractmethod


class Closer(ABC):
    async def close(self) -> None:
        ...


class Reader(ABC):
    @abstractmethod
    async def read(self, n: int = None) -> bytes:
        ...


class Writer(ABC):
    @abstractmethod
    async def write(self, data: bytes) -> None:
        ...


class WriteCloser(Writer, Closer):
    pass


class ReadCloser(Reader, Closer):
    pass


class ReadWriter(Reader, Writer):
    pass


class ReadWriteCloser(Reader, Writer, Closer):
    pass


class MsgReader(ABC):
    @abstractmethod
    async def read_msg(self) -> bytes:
        ...

    @abstractmethod
    async def next_msg_len(self) -> int:
        ...


class MsgWriter(ABC):
    @abstractmethod
    async def write_msg(self, msg: bytes) -> None:
        ...


class MsgReadWriter(MsgReader, MsgWriter):
    pass
