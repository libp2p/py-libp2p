from .identify_push import (
    ID_PUSH,
    identify_push_handler_for,
    push_identify_to_peer,
    push_identify_to_peers,
)
from libp2p.identity.update import (
    update_peerstore_from_identify,
)

# Backward compatibility alias
_update_peerstore_from_identify = update_peerstore_from_identify

__all__ = [
    "ID_PUSH",
    "identify_push_handler_for",
    "push_identify_to_peer",
    "push_identify_to_peers",
    "update_peerstore_from_identify",
    "_update_peerstore_from_identify",
]
