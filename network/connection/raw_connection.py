from .raw_connection_interface import IRawConnection


class RawConnection(IRawConnection):
	# pylint: disable=too-few-public-methods

    def __init__(self, ip, port, reader, writer):
        self.conn_ip = ip
        self.conn_port = port
        self.reader = reader
        self.writer = writer

    def close(self):
        self.writer.close()
