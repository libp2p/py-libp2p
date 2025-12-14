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

import pytest


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
