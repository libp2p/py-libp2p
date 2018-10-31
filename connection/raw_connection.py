import asyncio
from .raw_connection_interface import IRawConnection

class RawConnection(IRawConnection):

    def __init__(self, ip, port):
        self.conn_ip = ip
        self.conn_port = port
        self.reader = None
        self.writer = None

    async def open_connection(self):
        self.reader, self.writer = \
            await asyncio.open_connection(self.conn_ip, self.conn_port)
