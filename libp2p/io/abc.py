from abc import ABC, abstractmethod


class Closer(ABC):
    @abstractmethod
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


class MsgWriter(ABC):
    @abstractmethod
    async def write_msg(self, msg: bytes) -> None:
        ...


class MsgReadWriteCloser(MsgReader, MsgWriter, Closer):
    pass


class Encrypter(ABC):
    @abstractmethod
    def encrypt(self, data: bytes) -> bytes:
        ...

    @abstractmethod
    def decrypt(self, data: bytes) -> bytes:
        ...


class EncryptedMsgReadWriter(MsgReadWriteCloser, Encrypter):
    """Read/write message with encryption/decryption."""
