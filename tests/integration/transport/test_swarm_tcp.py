import pytest
from multiaddr import Multiaddr

from libp2p.transport.tcp.tcp import TCP


class MockSwarm:
    def __init__(self):
        self.transport = TCP()
        self.listeners = []

    async def add_listener(self, maddr):
        listener = self.transport.create_listener(self.echo_handler)
        success = await listener.listen(maddr)
        if success:
            self.listeners.append(listener)
        return success, listener

    async def echo_handler(self, stream):
        while True:
            try:
                data = await stream.read(1024)
                if not data:
                    break
                await stream.write(data)
            except Exception:
                break

    async def shutdown(self):
        for listener in self.listeners:
            await listener.close()


@pytest.mark.trio
async def test_swarm_integration_flow():
    """
    Simulates Swarm -> TCPListener interaction.
    """
    swarm = MockSwarm()
    maddr = Multiaddr("/ip4/127.0.0.1/tcp/0")

    success, listener = await swarm.add_listener(maddr)
    assert success is True

    listen_addr = listener.get_addrs()[0]

    transport = TCP()
    conn = await transport.dial(listen_addr)

    test_data = b"Hello"
    await conn.write(test_data)
    read_data = await conn.read(len(test_data))
    assert read_data == test_data

    await conn.close()
    await swarm.shutdown()

    assert len(listener.listeners) == 0
