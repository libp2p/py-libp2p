"""
Test Notify and Notifee by ensuring that the proper events get called, and that
the stream passed into opened_stream is correct.

Note: Listen event does not get hit because MyNotifee is passed
into network after network has already started listening

TODO: Add tests for closed_stream, listen_close when those
features are implemented in swarm
"""
import enum

from async_service import background_trio_service
import pytest
import trio

from libp2p.network.notifee_interface import INotifee
from libp2p.tools.constants import LISTEN_MADDR
from libp2p.tools.factories import SwarmFactory
from libp2p.tools.utils import connect_swarm


class Event(enum.Enum):
    OpenedStream = 0
    ClosedStream = 1  # Not implemented
    Connected = 2
    Disconnected = 3
    Listen = 4
    ListenClose = 5  # Not implemented


class MyNotifee(INotifee):
    def __init__(self, events):
        self.events = events

    async def opened_stream(self, network, stream):
        self.events.append(Event.OpenedStream)

    async def closed_stream(self, network, stream):
        # TODO: It is not implemented yet.
        pass

    async def connected(self, network, conn):
        self.events.append(Event.Connected)

    async def disconnected(self, network, conn):
        self.events.append(Event.Disconnected)

    async def listen(self, network, _multiaddr):
        self.events.append(Event.Listen)

    async def listen_close(self, network, _multiaddr):
        # TODO: It is not implemented yet.
        pass


@pytest.mark.trio
async def test_notify(security_protocol):
    swarms = [SwarmFactory(security_protocol=security_protocol) for _ in range(2)]

    events_0_0 = []
    events_1_0 = []
    events_0_without_listen = []
    # Run swarms.
    async with background_trio_service(swarms[0]), background_trio_service(swarms[1]):
        # Register events before listening, to allow `MyNotifee` is notified with the event
        # `listen`.
        swarms[0].register_notifee(MyNotifee(events_0_0))
        swarms[1].register_notifee(MyNotifee(events_1_0))

        # Listen
        async with trio.open_nursery() as nursery:
            nursery.start_soon(swarms[0].listen, LISTEN_MADDR)
            nursery.start_soon(swarms[1].listen, LISTEN_MADDR)

        swarms[0].register_notifee(MyNotifee(events_0_without_listen))

        # Connected
        await connect_swarm(swarms[0], swarms[1])
        # OpenedStream: first
        await swarms[0].new_stream(swarms[1].get_peer_id())
        # OpenedStream: second
        await swarms[0].new_stream(swarms[1].get_peer_id())
        # OpenedStream: third, but different direction.
        await swarms[1].new_stream(swarms[0].get_peer_id())

        await trio.sleep(0.01)

        # TODO: Check `ClosedStream` and `ListenClose` events after they are ready.

        # Disconnected
        await swarms[0].close_peer(swarms[1].get_peer_id())
        await trio.sleep(0.01)

        # Connected again, but different direction.
        await connect_swarm(swarms[1], swarms[0])
        await trio.sleep(0.01)

        # Disconnected again, but different direction.
        await swarms[1].close_peer(swarms[0].get_peer_id())
        await trio.sleep(0.01)

        expected_events_without_listen = [
            Event.Connected,
            Event.OpenedStream,
            Event.OpenedStream,
            Event.OpenedStream,
            Event.Disconnected,
            Event.Connected,
            Event.Disconnected,
        ]
        expected_events = [Event.Listen] + expected_events_without_listen

        assert events_0_0 == expected_events
        assert events_1_0 == expected_events
        assert events_0_without_listen == expected_events_without_listen
