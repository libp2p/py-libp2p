from unittest.mock import (
    MagicMock,
)

import trio

from libp2p.abc import IHost


def create_mock_connections(count: int = 50) -> dict:
    connections = {}

    for i in range(1, count):
        peer_id = f"peer-{i}"
        mock_conn = MagicMock(name=f"INetConn-{i}")
        connections[peer_id] = mock_conn

    return connections


async def run_host_forever(host: IHost, addr):
    async with host.run([addr]):
        await trio.sleep_forever()


async def wait_until_listening(host, timeout=3):
    with trio.move_on_after(timeout):
        while not host.get_addrs():
            await trio.sleep(0.05)
        return
    raise RuntimeError("Timed out waiting for host to get an address")
