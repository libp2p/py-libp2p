"""
Test Notify and Notifee by ensuring that the proper events get called, and that
the stream passed into opened_stream is correct.

Note: Listen event does not get hit because MyNotifee is passed
into network after network has already started listening

TODO: Add tests for closed_stream, listen_close when those
features are implemented in swarm
"""

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
from libp2p.tools.utils import connect_swarm
from tests.utils.factories import (
    SwarmFactory,
)


class Event(enum.Enum):
    OpenedStream = 0
    ClosedStream = 1  # Not implemented
    Connected = 2
    Disconnected = 3
    Listen = 4
    ListenClose = 5  # Not implemented


class MyNotifee(INotifee):
    def __init__(self, events: list[Event]):
        self.events = events

    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        self.events.append(Event.OpenedStream)

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        # TODO: It is not implemented yet.
        pass

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        self.events.append(Event.Connected)

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        self.events.append(Event.Disconnected)

    async def listen(self, network: INetwork, multiaddr: Multiaddr) -> None:
        self.events.append(Event.Listen)

    async def listen_close(self, network: INetwork, multiaddr: Multiaddr) -> None:
        # TODO: It is not implemented yet.
        pass


@pytest.mark.trio
async def test_notify(security_protocol):
    # Helper to wait for specific event
    async def wait_for_event(events_list, event, timeout=1.0):
        with trio.move_on_after(timeout):
            while event not in events_list:
                await trio.sleep(0.01)
            return True
        return False

    # Event lists for notifees
    events_0_0 = []
    events_0_1 = []
    events_1_0 = []
    events_1_1 = []

    # Create two swarms, but do not listen yet
    async with SwarmFactory.create_batch_and_listen(2) as swarms:
        # Register notifees before listening
        notifee_0_0 = MyNotifee(events_0_0)
        notifee_0_1 = MyNotifee(events_0_1)
        notifee_1_0 = MyNotifee(events_1_0)
        notifee_1_1 = MyNotifee(events_1_1)

        swarms[0].register_notifee(notifee_0_0)
        swarms[0].register_notifee(notifee_0_1)
        swarms[1].register_notifee(notifee_1_0)
        swarms[1].register_notifee(notifee_1_1)

        # Connect swarms
        await connect_swarm(swarms[0], swarms[1])

        # Create a stream
        stream = await swarms[0].new_stream(swarms[1].get_peer_id())
        await stream.close()

        # Close peer
        await swarms[0].close_peer(swarms[1].get_peer_id())

        # Wait for events
        assert await wait_for_event(events_0_0, Event.Connected, 1.0)
        assert await wait_for_event(events_0_0, Event.OpenedStream, 1.0)
        # assert await wait_for_event(
        #     events_0_0, Event.ClosedStream, 1.0
        # )  # Not implemented
        assert await wait_for_event(events_0_0, Event.Disconnected, 1.0)

        assert await wait_for_event(events_0_1, Event.Connected, 1.0)
        assert await wait_for_event(events_0_1, Event.OpenedStream, 1.0)
        # assert await wait_for_event(
        #     events_0_1, Event.ClosedStream, 1.0
        # )  # Not implemented
        assert await wait_for_event(events_0_1, Event.Disconnected, 1.0)

        assert await wait_for_event(events_1_0, Event.Connected, 1.0)
        assert await wait_for_event(events_1_0, Event.OpenedStream, 1.0)
        # assert await wait_for_event(
        #     events_1_0, Event.ClosedStream, 1.0
        # )  # Not implemented
        assert await wait_for_event(events_1_0, Event.Disconnected, 1.0)

        assert await wait_for_event(events_1_1, Event.Connected, 1.0)
        assert await wait_for_event(events_1_1, Event.OpenedStream, 1.0)
        # assert await wait_for_event(
        #     events_1_1, Event.ClosedStream, 1.0
        # )  # Not implemented
        assert await wait_for_event(events_1_1, Event.Disconnected, 1.0)
