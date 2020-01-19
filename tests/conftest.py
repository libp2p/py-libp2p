import pytest

from libp2p.tools.factories import HostFactory


@pytest.fixture
def is_host_secure():
    return False


@pytest.fixture
def num_hosts():
    return 3


@pytest.fixture
async def hosts(num_hosts, is_host_secure, nursery):
    async with HostFactory.create_batch_and_listen(is_host_secure, num_hosts) as _hosts:
        yield _hosts
