from abc import ABC, abstractmethod

class IRawConnection(ABC):

    @abstractmethod
    async def open_connection(self):
        pass
   