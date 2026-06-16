from .config import AddParams, Config
from .peer import Peer
from .setup import (
    default_bootstrap_peers,
    new_in_memory_datastore,
    setup_libp2p,
)

__all__ = [
    "AddParams",
    "Config",
    "Peer",
    "default_bootstrap_peers",
    "new_in_memory_datastore",
    "setup_libp2p",
]

__version__ = "0.1.0"

