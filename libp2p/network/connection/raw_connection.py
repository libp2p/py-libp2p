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
        Launch the closing of the connection, usefull for closing multiple
        connection at once.
        :return: return True if successful
        """
        self.writer.close()

    async def wait_closed(self):
        """
        Wait until the connection is closed. Usefull for closing multiple
        connection at once. Must be used after shutdown.
        For an all in one close use close.
        :return: return True if successful
        """
        if self.writer is None: return False
        await self.writer.wait_close()
        return True

    def close(self):
        """
        Close and wait for the connection to be closed.
        """
        if not self.shutdown(): return False
        loop = get_event_loop()
        loop.run_until_complete(self.wait_closed())
        loop.close()
        self.writer = None
        self.reader = None
        return True

    def is_closed(self):
        """
        :return: return True if the connection is closed.
        """
        if self.writer is None: return True
        return self.writer.is_closing()

    def next_stream_id(self):
        """
        Get next available stream id
        :return: next available stream id for the connection
        """
        next_id = self._next_id
        self._next_id += 2
        return next_id
