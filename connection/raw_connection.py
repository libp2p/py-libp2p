from .raw_connection import IRawConnection

class RawConnection(IRawConnection):

    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        
    async def open_connection(self):
    	self.reader, self.writer = await asyncio.open_connection(self.ip, self.port)
