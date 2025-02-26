"""
Proof of concept for migrating from async_service to anyio.

This demonstrates how the current py-libp2p async_service implementation
could be replaced with a simpler implementation using anyio.
"""

from .abc import (
    InternalManagerAPI,
    ManagerAPI,
    ServiceAPI,
)
from .base import (
    Service,
    as_service,
)
from .exceptions import (
    DaemonTaskExit,
    LifecycleError,
    ServiceException,
)
from .manager import (
    AnyIOManager,
    background_service,
    run_service,
)
from .stats import (
    Stats,
    TaskStats,
)
