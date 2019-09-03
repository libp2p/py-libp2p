import asyncio

import pytest

from .configs import LISTEN_MADDR
from .factories import HostFactory


@pytest.fixture
def is_host_secure():
    return False


@pytest.fixture
def num_hosts():
    return 3


@pytest.fixture
async def hosts(num_hosts, is_host_secure):
    _hosts = HostFactory.create_batch(num_hosts, is_secure=is_host_secure)
    await asyncio.gather(
        *[_host.get_network().listen(LISTEN_MADDR) for _host in _hosts]
    )
    try:
        yield _hosts
    finally:
        # TODO: It's possible that `close` raises exceptions currently,
        #   due to the connection reset things. Though we don't care much about that when
        #   cleaning up the tasks, it is probably better to handle the exceptions properly.
        await asyncio.gather(
            *[_host.close() for _host in _hosts], return_exceptions=True
        )
