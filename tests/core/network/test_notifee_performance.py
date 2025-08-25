import pytest
from multiaddr import Multiaddr
import trio

from libp2p.abc import (
    INetConn,
    INetStream,
    INetwork,
    INotifee,
)
from libp2p.tools.utils import connect_swarm
from tests.utils.factories import SwarmFactory


class CountingNotifee(INotifee):
    def __init__(self, event: trio.Event) -> None:
        self._event = event

    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        pass

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        pass

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        self._event.set()

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        pass

    async def listen(self, network: INetwork, multiaddr: Multiaddr) -> None:
        pass

    async def listen_close(self, network: INetwork, multiaddr: Multiaddr) -> None:
        pass


class SlowNotifee(INotifee):
    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        pass

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        pass

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        await trio.sleep(0.5)

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        pass

    async def listen(self, network: INetwork, multiaddr: Multiaddr) -> None:
        pass

    async def listen_close(self, network: INetwork, multiaddr: Multiaddr) -> None:
        pass


@pytest.mark.trio
async def test_many_notifees_receive_connected_quickly() -> None:
    async with SwarmFactory.create_batch_and_listen(2) as swarms:
        count = 200
        events = [trio.Event() for _ in range(count)]
        for ev in events:
            swarms[0].register_notifee(CountingNotifee(ev))
        await connect_swarm(swarms[0], swarms[1])
        with trio.fail_after(1.5):
            for ev in events:
                await ev.wait()


@pytest.mark.trio
async def test_slow_notifee_does_not_block_others() -> None:
    async with SwarmFactory.create_batch_and_listen(2) as swarms:
        fast_events = [trio.Event() for _ in range(20)]
        for ev in fast_events:
            swarms[0].register_notifee(CountingNotifee(ev))
        swarms[0].register_notifee(SlowNotifee())
        await connect_swarm(swarms[0], swarms[1])
        # Fast notifees should complete quickly despite one slow notifee
        with trio.fail_after(0.3):
            for ev in fast_events:
                await ev.wait()
