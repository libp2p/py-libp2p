import pytest

from tests.utils.factories import (
    HostFactory,
)

# Register the pytest-trio plugin
pytest_plugins = ["pytest_trio"]


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


# Explicitly configure pytest to use trio for async tests
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """
    Add the 'trio' marker to async tests if they don't already have an async marker.
    """
    for item in items:
        if isinstance(item, pytest.Function) and asyncio_or_trio_test(item):
            # If it's an async test but
            # doesn't have any async marker yet, add trio marker
            if not any(
                marker.name in ["trio", "asyncio"] for marker in item.own_markers
            ):
                item.add_marker(pytest.mark.trio)


def asyncio_or_trio_test(item):
    """Check if a test item is an async test function."""
    if not hasattr(item.obj, "__code__"):
        return False
    return item.obj.__code__.co_flags & 0x80  # 0x80 is the flag for coroutine functions
