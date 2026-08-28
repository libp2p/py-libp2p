"""
p2p_checkpoint
==============

A minimal peer-to-peer machine-learning checkpoint sharing system.

Architecture, in one sentence:

    libp2p carries small, live control messages (who has what, and where)
    while IPFS carries the large, persistent artifact (the checkpoint itself).

See the project README for the full design write-up.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("p2p-model-checkpoint")
except PackageNotFoundError:  # pragma: no cover - local/dev checkout
    __version__ = "0.1.0-dev"

__all__ = ["__version__"]
