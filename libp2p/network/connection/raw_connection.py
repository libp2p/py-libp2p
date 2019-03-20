from asyncio import get_event_loop

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

    def shutdown(self):
        """
        Lunch the closing of the connection, usefull for closing multiple
        connection at once.
        :return: return True if successful
        """
        self.writer.close()

    async def wait_closed(self):
        """
        Wait until the connection is closed. Usefull for closing multiple
        connection at once. Must be used after shutdown.
        For an all in one close use close.
        """
        await self.writer.wait_close()

    def close(self):
        """
        Close and wait for the connection to be closed.
        """
        self.shutdown()
        loop = get_event_loop()
        loop.run_until_complete(self.wait_closed())
        loop.close()

    def next_stream_id(self):
        """
        Get next available stream id
        :return: next available stream id for the connection
        """
        next_id = self._next_id
        self._next_id += 2
        return next_id
