import pytest


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_gossipsub(pubsubs_gsub, p2pds):
    pass
