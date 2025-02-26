"""
Proof of concept for migrating from async_service to anyio.

This demonstrates how the current py-libp2p async_service implementation
could be replaced with a simpler implementation using anyio.
"""

from .abc import (
    ServiceAPI,
    ManagerAPI,
    InternalManagerAPI,
)
from .base import (
    Service,
    as_service,
)
from .exceptions import (
    ServiceException,
    LifecycleError,
    DaemonTaskExit,
)
from .manager import (
    AnyIOManager,
    run_service,
    background_service,
)
from .stats import (
    Stats,
    TaskStats,
)