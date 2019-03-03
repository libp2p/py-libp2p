import pytest

from tests.utils import cleanup
from libp2p import new_node
from libp2p.network.notifee_interface import INotifee

# pylint: disable=too-many-locals

"""
Test Notify and Notifee by ensuring that the proper events get
called, and that the stream passed into opened_stream is correct

Note: Listen event does not get hit because MyNotifee is passed
into network after network has already started listening

TODO: Add tests to ensure conn is the correct connection
TODO: Add tests for closed_stream disconnected, listen_close when those
features are implemented in swarm
"""

class MyNotifee(INotifee):
    # pylint: disable=too-many-instance-attributes, cell-var-from-loop

    def __init__(self, events, val_to_append_to_event):
        self.events = events
        self.val_to_append_to_event = val_to_append_to_event

    async def opened_stream(self, network, stream):
        self.events.append(["opened_stream" + \
            self.val_to_append_to_event, stream])

    async def closed_stream(self, network, stream):
        pass

    async def connected(self, network, conn):
        self.events.append(["connected" + self.val_to_append_to_event,\
            conn])

    async def disconnected(self, network, conn):
        pass

    async def listen(self, network, multiaddr):
        pass

    async def listen_close(self, network, multiaddr):
        pass

@pytest.mark.asyncio
async def test_one_notifier():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read()).decode()

            response = "ack:" + read_string
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)

    # Add notifee for node_a
    events = []
    node_a.get_network().notify(MyNotifee(events, "0"))

    stream = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])

    # Ensure the connected and opened_stream events were hit in MyNotifee obj
    # and that stream passed into opened_stream matches the stream created on
    # node_a
    assert events == [["connected0", stream.mplex_conn], \
        ["opened_stream0", stream]]

    messages = ["hello", "hello"]
    for message in messages:
        await stream.write(message.encode())

        response = (await stream.read()).decode()

        assert response == ("ack:" + message)

    # Success, terminate pending tasks.
    await cleanup()

@pytest.mark.asyncio
async def test_two_notifiers():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read()).decode()

            response = "ack:" + read_string
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)

    # Add notifee for node_a
    events0 = []
    node_a.get_network().notify(MyNotifee(events0, "0"))

    events1 = []
    node_a.get_network().notify(MyNotifee(events1, "1"))

    stream = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])

    # Ensure the connected and opened_stream events were hit in both Notifee objs
    # and that the stream passed into opened_stream matches the stream created on
    # node_a
    assert events0 == [["connected0", stream.mplex_conn], ["opened_stream0", stream]]
    assert events1 == [["connected1", stream.mplex_conn], ["opened_stream1", stream]]


    messages = ["hello", "hello"]
    for message in messages:
        await stream.write(message.encode())

        response = (await stream.read()).decode()

        assert response == ("ack:" + message)

    # Success, terminate pending tasks.
    await cleanup()

@pytest.mark.asyncio
async def test_ten_notifiers():
    num_notifiers = 10

    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    async def stream_handler(stream):
        while True:
            read_string = (await stream.read()).decode()

            response = "ack:" + read_string
            await stream.write(response.encode())

    node_b.set_stream_handler("/echo/1.0.0", stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)

    # Add notifee for node_a
    events_lst = []
    for i in range(num_notifiers):
        events_lst.append([])
        node_a.get_network().notify(MyNotifee(events_lst[i], str(i)))

    stream = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])

    # Ensure the connected and opened_stream events were hit in both Notifee objs
    # and that the stream passed into opened_stream matches the stream created on
    # node_a
    for i in range(num_notifiers):
        assert events_lst[i] == [["connected" + str(i), stream.mplex_conn], \
            ["opened_stream" + str(i), stream]]

    messages = ["hello", "hello"]
    for message in messages:
        await stream.write(message.encode())

        response = (await stream.read()).decode()

        assert response == ("ack:" + message)

    # Success, terminate pending tasks.
    await cleanup()
