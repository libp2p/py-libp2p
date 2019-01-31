from .raw_connection_interface import IRawConnection


class RawConnection(IRawConnection):

    def __init__(self, ip, port, reader, writer, initiator):
        # pylint: disable=too-many-arguments
        self.conn_ip = ip
        self.conn_port = port
        self.reader = reader
        self.writer = writer
        self._next_id = 0 if initiator else 1
        self.initiator = initiator

    async def close(self):
        self.writer.close()
        # Not disponible in current version, please untag when passing python 3.7
        #await self.writer.wait_closed()

    def is_closed(self):
        # pylint: disable=no-self-use
        """
        retrieve the status of the connection
        :return: True if down, True if up
        """
        # Not disponible in current version, please untag when passing python 3.7
        #return not self.server.is_serving()
        # Temporary solution, remove when passing python 3.7
        return False

    def next_stream_id(self):
        """
        Get next available stream id
        :return: next available stream id for the connection
        """
        next_id = self._next_id
        self._next_id += 2
        return next_id
