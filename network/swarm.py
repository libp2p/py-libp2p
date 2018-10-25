from .network_interface import INetwork
from stream import Stream
import asyncio

class Swarm(INetwork):

    def __init__(self, my_peer_id, peer_store):
        self.my_peer_id = my_peer_id
        self.peer_store = peer_store
        self.stream_handlers = {}
        self.server = None

    def set_stream_handler(self, protocol_id, stream_handler):
        """
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        self.stream_handlers[protocol_id] = stream_handler
        return True

    def new_stream(self, peer_id, multi_addr):
        """
        :param peer_id: peer_id of destination
        :param multi_addr: multiaddr to connect to
        :return: stream instance
        """
        stream = Stream(peer_id, multi_addr)
        return stream

    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: true if at least one success
        """
        to_return = False
        for multi_addr in args:
            to_return = to_return or self.listen_on_multi_addr(multi_addr)
        return to_return

    def listen_on_multi_addr(self, multi_addr):
        async def handle_connection(reader, writer):
            # TODO update this protocol_id extraction
            protocol_id = multi_addr.get_protocols()[0]
            if protocol_id not in self.stream_handlers:
                # TODO better error when we don't have
                # a stream handler for this protocol
                return 0

            stream_handler = self.stream_handlers[protocol_id]
            to_return = stream_handler(reader, writer)
            await writer.drain()
            writer.close()
            return to_return

        # update to be transport agnostic
        port = multi_addr.get_protocol_value("tcp")
        loop = asyncio.get_event_loop()
        coro = asyncio.start_server(handle_connection, '127.0.0.1', port, loop=loop)
        self.server = loop.run_until_complete(coro)

    def stop_listening(self):
        if self.server is None:
            return 0
        self.server.close()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.server.wait_closed())
        loop.close()
        self.server = None
        return 0
