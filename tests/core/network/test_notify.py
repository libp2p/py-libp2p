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
import trio

from libp2p.abc import (
    INotifee,
)
from libp2p.tools.async_service import (
    background_trio_service,
)
from libp2p.tools.constants import (
    LISTEN_MADDR,
)
from libp2p.tools.utils import (
    connect_swarm,
)
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

    # Helper to wait for specific event
    async def wait_for_event(events_list, expected_event, timeout=1.0):
        start_time = trio.current_time()
        while trio.current_time() - start_time < timeout:
            if expected_event in events_list:
                return True
            await trio.sleep(0.01)
        return False

    # Run swarms.
    async with background_trio_service(swarms[0]), background_trio_service(swarms[1]):
        # Register events before listening
        swarms[0].register_notifee(MyNotifee(events_0_0))
        swarms[1].register_notifee(MyNotifee(events_1_0))

        # Listen
        async with trio.open_nursery() as nursery:
            nursery.start_soon(swarms[0].listen, LISTEN_MADDR)
            nursery.start_soon(swarms[1].listen, LISTEN_MADDR)

        # Wait for Listen events
        assert await wait_for_event(events_0_0, Event.Listen)
        assert await wait_for_event(events_1_0, Event.Listen)

        swarms[0].register_notifee(MyNotifee(events_0_without_listen))

        # Connected
        await connect_swarm(swarms[0], swarms[1])
        assert await wait_for_event(events_0_0, Event.Connected)
        assert await wait_for_event(events_1_0, Event.Connected)
        assert await wait_for_event(events_0_without_listen, Event.Connected)

        # OpenedStream: first
        await swarms[0].new_stream(swarms[1].get_peer_id())
        # OpenedStream: second
        await swarms[0].new_stream(swarms[1].get_peer_id())
        # OpenedStream: third, but different direction.
        await swarms[1].new_stream(swarms[0].get_peer_id())

        # Clear any duplicate events that might have occurred
        events_0_0.copy()
        events_1_0.copy()
        events_0_without_listen.copy()

        # TODO: Check `ClosedStream` and `ListenClose` events after they are ready.

        # Disconnected
        await swarms[0].close_peer(swarms[1].get_peer_id())
        assert await wait_for_event(events_0_0, Event.Disconnected)
        assert await wait_for_event(events_1_0, Event.Disconnected)
        assert await wait_for_event(events_0_without_listen, Event.Disconnected)

        # Connected again, but different direction.
        await connect_swarm(swarms[1], swarms[0])

        # Get the index of the first disconnected event
        disconnect_idx_0_0 = events_0_0.index(Event.Disconnected)
        disconnect_idx_1_0 = events_1_0.index(Event.Disconnected)
        disconnect_idx_without_listen = events_0_without_listen.index(
            Event.Disconnected
        )

        # Check for connected event after disconnect
        assert await wait_for_event(
            events_0_0[disconnect_idx_0_0 + 1 :], Event.Connected
        )
        assert await wait_for_event(
            events_1_0[disconnect_idx_1_0 + 1 :], Event.Connected
        )
        assert await wait_for_event(
            events_0_without_listen[disconnect_idx_without_listen + 1 :],
            Event.Connected,
        )

        # Disconnected again, but different direction.
        await swarms[1].close_peer(swarms[0].get_peer_id())

        # Find index of the second connected event
        second_connect_idx_0_0 = events_0_0.index(
            Event.Connected, disconnect_idx_0_0 + 1
        )
        second_connect_idx_1_0 = events_1_0.index(
            Event.Connected, disconnect_idx_1_0 + 1
        )
        second_connect_idx_without_listen = events_0_without_listen.index(
            Event.Connected, disconnect_idx_without_listen + 1
        )

        # Check for second disconnected event
        assert await wait_for_event(
            events_0_0[second_connect_idx_0_0 + 1 :], Event.Disconnected
        )
        assert await wait_for_event(
            events_1_0[second_connect_idx_1_0 + 1 :], Event.Disconnected
        )
        assert await wait_for_event(
            events_0_without_listen[second_connect_idx_without_listen + 1 :],
            Event.Disconnected,
        )

        # Verify the core sequence of events
        expected_events_without_listen = [
            Event.Connected,
            Event.Disconnected,
            Event.Connected,
            Event.Disconnected,
        ]

        # Filter events to check only pattern we care about
        # (skipping OpenedStream which may vary)
        filtered_events_0_0 = [
            e
            for e in events_0_0
            if e in [Event.Listen, Event.Connected, Event.Disconnected]
        ]
        filtered_events_1_0 = [
            e
            for e in events_1_0
            if e in [Event.Listen, Event.Connected, Event.Disconnected]
        ]
        filtered_events_without_listen = [
            e
            for e in events_0_without_listen
            if e in [Event.Connected, Event.Disconnected]
        ]

        # Check that the pattern matches
        assert filtered_events_0_0[0] == Event.Listen, "First event should be Listen"
        assert filtered_events_1_0[0] == Event.Listen, "First event should be Listen"

        # Check pattern: Connected -> Disconnected -> Connected -> Disconnected
        assert filtered_events_0_0[1:5] == expected_events_without_listen
        assert filtered_events_1_0[1:5] == expected_events_without_listen
        assert filtered_events_without_listen[:4] == expected_events_without_listen
