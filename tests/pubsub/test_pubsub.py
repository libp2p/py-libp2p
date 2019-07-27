import pytest


@pytest.mark.asyncio
async def test_test(pubsubs_fsub):
    topic = "topic"
    data = b"data"
    sub = await pubsubs_fsub[0].subscribe(topic)
    await pubsubs_fsub[0].publish(topic, data)
    msg = await sub.get()
    assert msg.data == data
