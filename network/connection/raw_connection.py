import asyncio
from .raw_connection_interface import IRawConnection

class RawConnection(IRawConnection):

    def __init__(self, ip, port, reader, writer):
        self.conn_ip = ip
        self.conn_port = port
        self.reader = reader
        self.writer = writer

    # def __init__(self, ip, port):
    #     self.conn_ip = ip
    #     self.conn_port = port
    #     self.reader, self.writer = self.open_connection()

    # async def open_connection(self):
    #     """
    #     opens a connection on self.ip and self.port
    #     :return: a raw connection
    #     """
    #     return await asyncio.open_connection(self.conn_ip, self.conn_port)
