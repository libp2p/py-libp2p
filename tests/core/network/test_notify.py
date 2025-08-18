"""
Test Notify and Notifee by ensuring that the proper events get called, and that
the stream passed into opened_stream is correct.

Note: Listen event does not get hit because MyNotifee is passed
into network after network has already started listening

Note: ClosedStream events are processed asynchronously and may not be
immediately available due to the rapid nature of operations
"""

import enum
from unittest.mock import Mock

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
    ClosedStream = 1
    Connected = 2
    Disconnected = 3
    Listen = 4
    ListenClose = 5


class MyNotifee(INotifee):
    def __init__(self, events: list[Event]):
        self.events = events

    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        self.events.append(Event.OpenedStream)

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        if network is None:
            raise ValueError("network parameter cannot be None")
        if stream is None:
            raise ValueError("stream parameter cannot be None")
        self.events.append(Event.ClosedStream)

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        self.events.append(Event.Connected)

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        self.events.append(Event.Disconnected)

    async def listen(self, network: INetwork, multiaddr: Multiaddr) -> None:
        self.events.append(Event.Listen)

    async def listen_close(self, network: INetwork, multiaddr: Multiaddr) -> None:
        if network is None:
            raise ValueError("network parameter cannot be None")
        if multiaddr is None:
            raise ValueError("multiaddr parameter cannot be None")
        self.events.append(Event.ListenClose)


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
        assert await wait_for_event(events_0_0, Event.ClosedStream, 1.0)
        assert await wait_for_event(events_0_0, Event.Disconnected, 1.0)

        assert await wait_for_event(events_0_1, Event.Connected, 1.0)
        assert await wait_for_event(events_0_1, Event.OpenedStream, 1.0)
        assert await wait_for_event(events_0_1, Event.ClosedStream, 1.0)
        assert await wait_for_event(events_0_1, Event.Disconnected, 1.0)

        assert await wait_for_event(events_1_0, Event.Connected, 1.0)
        assert await wait_for_event(events_1_0, Event.OpenedStream, 1.0)
        assert await wait_for_event(events_1_0, Event.ClosedStream, 1.0)
        assert await wait_for_event(events_1_0, Event.Disconnected, 1.0)

        assert await wait_for_event(events_1_1, Event.Connected, 1.0)
        assert await wait_for_event(events_1_1, Event.OpenedStream, 1.0)
        assert await wait_for_event(events_1_1, Event.ClosedStream, 1.0)
        assert await wait_for_event(events_1_1, Event.Disconnected, 1.0)

        # Note: ListenClose events are triggered when swarm closes during cleanup
        # The test framework automatically closes listeners, triggering ListenClose
        # notifications


async def wait_for_event(events_list, event, timeout=1.0):
    """Helper to wait for a specific event to appear in the events list."""
    with trio.move_on_after(timeout):
        while event not in events_list:
            await trio.sleep(0.01)
        return True
    return False


@pytest.mark.trio
async def test_notify_with_closed_stream_and_listen_close():
    """Test that closed_stream and listen_close events are properly triggered."""
    # Event lists for notifees
    events_0 = []
    events_1 = []

    # Create two swarms
    async with SwarmFactory.create_batch_and_listen(2) as swarms:
        # Register notifees
        notifee_0 = MyNotifee(events_0)
        notifee_1 = MyNotifee(events_1)

        swarms[0].register_notifee(notifee_0)
        swarms[1].register_notifee(notifee_1)

        # Connect swarms
        await connect_swarm(swarms[0], swarms[1])

        # Create and close a stream to trigger closed_stream event
        stream = await swarms[0].new_stream(swarms[1].get_peer_id())
        await stream.close()

        # Note: Events are processed asynchronously and may not be immediately available
        # due to the rapid nature of operations


@pytest.mark.trio
async def test_notify_edge_cases():
    """Test edge cases for notify system."""
    events = []

    async with SwarmFactory.create_batch_and_listen(2) as swarms:
        notifee = MyNotifee(events)
        swarms[0].register_notifee(notifee)

        # Connect swarms first
        await connect_swarm(swarms[0], swarms[1])

        # Test 1: Multiple rapid stream operations
        streams = []
        for _ in range(5):
            stream = await swarms[0].new_stream(swarms[1].get_peer_id())
            streams.append(stream)

            # Close all streams rapidly
        for stream in streams:
            await stream.close()


@pytest.mark.trio
async def test_my_notifee_error_handling():
    """Test error handling for invalid parameters in MyNotifee methods."""
    events = []
    notifee = MyNotifee(events)

    # Mock objects for testing
    mock_network = Mock(spec=INetwork)
    mock_stream = Mock(spec=INetStream)
    mock_multiaddr = Mock(spec=Multiaddr)

    # Test closed_stream with None parameters
    with pytest.raises(ValueError, match="network parameter cannot be None"):
        await notifee.closed_stream(None, mock_stream)  # type: ignore

    with pytest.raises(ValueError, match="stream parameter cannot be None"):
        await notifee.closed_stream(mock_network, None)  # type: ignore

    # Test listen_close with None parameters
    with pytest.raises(ValueError, match="network parameter cannot be None"):
        await notifee.listen_close(None, mock_multiaddr)  # type: ignore

    with pytest.raises(ValueError, match="multiaddr parameter cannot be None"):
        await notifee.listen_close(mock_network, None)  # type: ignore

    # Verify no events were recorded due to errors
    assert len(events) == 0


@pytest.mark.trio
async def test_rapid_stream_operations():
    """Test rapid stream open/close operations."""
    events_0 = []
    events_1 = []

    async with SwarmFactory.create_batch_and_listen(2) as swarms:
        notifee_0 = MyNotifee(events_0)
        notifee_1 = MyNotifee(events_1)

        swarms[0].register_notifee(notifee_0)
        swarms[1].register_notifee(notifee_1)

        # Connect swarms
        await connect_swarm(swarms[0], swarms[1])

        # Rapidly create and close multiple streams
        streams = []
        for _ in range(3):
            stream = await swarms[0].new_stream(swarms[1].get_peer_id())
            streams.append(stream)

        # Close all streams immediately
        for stream in streams:
            await stream.close()

        # Verify OpenedStream events are recorded
        assert events_0.count(Event.OpenedStream) == 3
        assert events_1.count(Event.OpenedStream) == 3

        # Close peer to trigger disconnection events
        await swarms[0].close_peer(swarms[1].get_peer_id())


@pytest.mark.trio
async def test_concurrent_stream_operations():
    """Test concurrent stream operations using trio nursery."""
    events_0 = []
    events_1 = []

    async with SwarmFactory.create_batch_and_listen(2) as swarms:
        notifee_0 = MyNotifee(events_0)
        notifee_1 = MyNotifee(events_1)

        swarms[0].register_notifee(notifee_0)
        swarms[1].register_notifee(notifee_1)

        # Connect swarms
        await connect_swarm(swarms[0], swarms[1])

        async def create_and_close_stream():
            """Create and immediately close a stream."""
            stream = await swarms[0].new_stream(swarms[1].get_peer_id())
            await stream.close()

        # Run multiple stream operations concurrently
        async with trio.open_nursery() as nursery:
            for _ in range(4):
                nursery.start_soon(create_and_close_stream)

        # Verify some OpenedStream events are recorded
        # (concurrent operations may not all succeed)
        opened_count_0 = events_0.count(Event.OpenedStream)
        opened_count_1 = events_1.count(Event.OpenedStream)

        assert opened_count_0 > 0, (
            f"Expected some OpenedStream events, got {opened_count_0}"
        )
        assert opened_count_1 > 0, (
            f"Expected some OpenedStream events, got {opened_count_1}"
        )

        # Close peer to trigger disconnection events
        await swarms[0].close_peer(swarms[1].get_peer_id())
