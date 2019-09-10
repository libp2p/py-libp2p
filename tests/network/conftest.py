import asyncio

import pytest

from tests.factories import net_stream_pair_factory


@pytest.fixture
async def net_stream_pair():
    stream_0, host_0, stream_1, host_1 = await net_stream_pair_factory()
    try:
        yield stream_0, stream_1
    finally:
        await asyncio.gather(*[host_0.close(), host_1.close()])
