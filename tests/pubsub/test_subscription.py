import math

import pytest
import trio

from libp2p.pubsub.pb import (
    rpc_pb2,
)
from libp2p.pubsub.subscription import (
    TrioSubscriptionAPI,
)

GET_TIMEOUT = 0.001


def make_trio_subscription():
    send_channel, receive_channel = trio.open_memory_channel(math.inf)

    async def unsubscribe_fn():
        await send_channel.aclose()

    return (
        send_channel,
        TrioSubscriptionAPI(receive_channel, unsubscribe_fn=unsubscribe_fn),
    )


def make_pubsub_msg():
    return rpc_pb2.Message()


async def send_something(send_channel):
    msg = make_pubsub_msg()
    await send_channel.send(msg)
    return msg


@pytest.mark.trio
async def test_trio_subscription_get():
    send_channel, sub = make_trio_subscription()
    data_0 = await send_something(send_channel)
    data_1 = await send_something(send_channel)
    assert data_0 == await sub.get()
    assert data_1 == await sub.get()
    # No more message
    with pytest.raises(trio.TooSlowError):
        with trio.fail_after(GET_TIMEOUT):
            await sub.get()


@pytest.mark.trio
async def test_trio_subscription_iter():
    send_channel, sub = make_trio_subscription()
    received_data = []

    async def iter_subscriptions(subscription):
        async for data in sub:
            received_data.append(data)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(iter_subscriptions, sub)
        await send_something(send_channel)
        await send_something(send_channel)
        await send_channel.aclose()

    assert len(received_data) == 2


@pytest.mark.trio
async def test_trio_subscription_unsubscribe():
    send_channel, sub = make_trio_subscription()
    await sub.unsubscribe()
    # Test: If the subscription is unsubscribed, `send_channel` should be closed.
    with pytest.raises(trio.ClosedResourceError):
        await send_something(send_channel)
    # Test: No side effect when cancelled twice.
    await sub.unsubscribe()


@pytest.mark.trio
async def test_trio_subscription_async_context_manager():
    send_channel, sub = make_trio_subscription()
    async with sub:
        # Test: `sub` is not cancelled yet, so `send_something` works fine.
        await send_something(send_channel)
    # Test: `sub` is cancelled, `send_something` fails
    with pytest.raises(trio.ClosedResourceError):
        await send_something(send_channel)
