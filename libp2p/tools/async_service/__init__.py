"""
DEPRECATED: libp2p.tools.async_service is deprecated.

This module has been replaced with libp2p.tools.anyio_service which provides a modern
AnyIO-based implementation with better structured concurrency and cross-platform
async support.

Please update your imports:
    OLD: from libp2p.tools.async_service import Service, background_trio_service
    NEW: from libp2p.tools.anyio_service import Service, background_trio_service

This legacy module will be removed in a future version.
"""

import warnings

warnings.warn(
    "libp2p.tools.async_service is deprecated. "
    "Use 'from libp2p.tools.anyio_service import ...' instead. "
    "This compatibility layer will be removed in v0.3.0.",
    DeprecationWarning,
    stacklevel=2
)

# For now, maintain compatibility by re-exporting from new module
# This will be removed once all usage has been migrated
from libp2p.tools.anyio_service import (
    DaemonTaskExit,
    LifecycleError,
    Service,
    ServiceAPI,
    TrioManager,
    as_service,
    background_trio_service,
)
