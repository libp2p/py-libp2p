from abc import ABC, abstractmethod



class IRawConnection(ABC):
    """
    A Raw Connection provides a Reader and a Writer
    """

    @abstractmethod
    async def write(self, data: bytes) -> None:
        pass

    @abstractmethod
    async def read(self) -> bytes:
        pass
