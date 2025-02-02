import trio
from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import HandshakeCompleted, ConnectionTerminated


class QuicProtocol(QuicConnectionProtocol):
    def __init__(self, host: str, port: int, configuration: QuicConfiguration):
        super().__init__(host, port, configuration)
        self.host = host
        self.port = port

    async def run(self):
        async with trio.open_nursery() as nursery:
            await nursery.start(self._connect)

    async def _connect(self, task_status=trio.TASK_STATUS_IGNORED):
        connection = await connect(self.host, self.port, configuration=self._configuration)
        task_status.started()
        try:
            async for event in connection.next_event():
                if isinstance(event, HandshakeCompleted):
                    print(f"Handshake completed with {self.host}:{self.port}")
                elif isinstance(event, ConnectionTerminated):
                    print(f"Connection terminated with {self.host}:{self.port}")
                    break
        finally:
            await connection.close()


async def main():
    configuration = QuicConfiguration(is_client=True)
    protocol = QuicProtocol("127.0.0.1", 4433, configuration)
    await protocol.run()


if __name__ == "__main__":
    trio.run(main)
