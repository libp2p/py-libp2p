import pytest

from libp2p.tools.factories import HostFactory


@pytest.fixture
def security_protocol():
    return None


@pytest.fixture
def num_hosts():
    return 3


@pytest.fixture
async def hosts(num_hosts, security_protocol, nursery):
    async with HostFactory.create_batch_and_listen(
        num_hosts, security_protocol=security_protocol
    ) as _hosts:
        yield _hosts
