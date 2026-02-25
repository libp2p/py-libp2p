"""
Pytest configuration for WebRTC transport tests.

Marks all WebRTC tests to run serially to avoid worker crashes and resource contention
when using pytest-xdist parallel execution.

Note: pytest-xdist doesn't automatically respect the 'serial' marker.
To run WebRTC tests serially, use:
    pytest -n 1 tests/core/transport/webrtc

Or in CI, add a separate step:
    pytest -n 1 --timeout=2400 tests/core/transport/webrtc
"""

from collections.abc import AsyncIterator

import pytest
import trio

from libp2p.abc import IHost
from libp2p.tools.utils import connect
from tests.utils.factories import HostFactory


def pytest_collection_modifyitems(config, items):
    """
    Automatically mark all tests in this directory with @pytest.mark.serial
    to identify them for serial execution.

    Note: This marker doesn't prevent pytest-xdist from running in parallel.
    Run with -n 1 to execute serially.
    """
    for item in items:
        # Only mark items from this directory (webrtc tests)
        if "webrtc" in str(item.fspath):
            item.add_marker(pytest.mark.serial)


@pytest.fixture
async def nat_peer_a(relay_host: IHost) -> AsyncIterator[IHost]:
    """Create a NAT peer A that connects to the relay."""
    # Lazy import so relay_fixtures is not loaded before pytest's assertion rewriter.
    from tests.core.transport.webrtc.relay_fixtures import store_relay_addrs

    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]

        # Connect to relay
        relay_id = relay_host.get_id()
        relay_addrs = list(relay_host.get_addrs())

        if relay_addrs:
            store_relay_addrs(relay_id, relay_addrs, host.get_peerstore())

            try:
                await connect(host, relay_host)
                await trio.sleep(0.1)
            except Exception:
                pass

        yield host


@pytest.fixture
async def nat_peer_b(relay_host: IHost) -> AsyncIterator[IHost]:
    """Create a NAT peer B that connects to the relay."""
    # Lazy import so relay_fixtures is not loaded before pytest's assertion rewriter.
    from tests.core.transport.webrtc.relay_fixtures import store_relay_addrs

    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]

        # Connect to relay
        relay_id = relay_host.get_id()
        relay_addrs = list(relay_host.get_addrs())

        if relay_addrs:
            store_relay_addrs(relay_id, relay_addrs, host.get_peerstore())

            try:
                await connect(host, relay_host)
                await trio.sleep(0.1)
            except Exception:
                pass

        yield host
