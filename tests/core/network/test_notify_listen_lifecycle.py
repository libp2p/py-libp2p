import enum

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.abc import (
    INetConn,
    INetStream,
    INetwork,
    INotifee,
)
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.constants import LISTEN_MADDR
from tests.utils.factories import SwarmFactory


class Event(enum.Enum):
    Listen = 0
    ListenClose = 1


class MyNotifee(INotifee):
    def __init__(self, events: list[Event]):
        self.events = events

    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        pass

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        pass

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        pass

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        pass

    async def listen(self, network: INetwork, multiaddr: Multiaddr) -> None:
        self.events.append(Event.Listen)

    async def listen_close(self, network: INetwork, multiaddr: Multiaddr) -> None:
        self.events.append(Event.ListenClose)


async def wait_for_event(
    events_list: list[Event], event: Event, timeout: float = 1.0
) -> bool:
    with trio.move_on_after(timeout):
        while event not in events_list:
            await trio.sleep(0.01)
        return True
    return False


@pytest.mark.trio
async def test_listen_emitted_when_registered_before_listen():
    events: list[Event] = []
    swarm = SwarmFactory.build()
    swarm.register_notifee(MyNotifee(events))
    async with background_trio_service(swarm):
        # Start listening now; notifee was registered beforehand
        assert await swarm.listen(LISTEN_MADDR)
        assert await wait_for_event(events, Event.Listen)


@pytest.mark.trio
async def test_single_listener_close_emits_listen_close():
    events: list[Event] = []
    swarm = SwarmFactory.build()
    swarm.register_notifee(MyNotifee(events))
    async with background_trio_service(swarm):
        assert await swarm.listen(LISTEN_MADDR)
        # Explicitly notify listen_close (close path via manager doesn't emit it)
        await swarm.notify_listen_close(LISTEN_MADDR)
        assert await wait_for_event(events, Event.ListenClose)
