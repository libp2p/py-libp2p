"""Resource manager package exports.

Expose the small set of public symbols the rest of the codebase and tests
import from ``libp2p.rcmgr`` so callers can do e.g.::

	from libp2p.rcmgr import Direction, ResourceManager, new_resource_manager

This keeps the package import surface explicit and stable.
"""

from .metrics import Direction
from .manager import ResourceLimits, ResourceManager, new_resource_manager
from .exceptions import ResourceScopeClosed

__all__ = [
	"Direction",
	"ResourceLimits",
	"ResourceManager",
	"new_resource_manager",
	"ResourceScopeClosed",
]
