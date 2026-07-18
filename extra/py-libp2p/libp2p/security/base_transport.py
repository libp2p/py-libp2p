from collections.abc import (
    Callable,
)
import secrets

from libp2p.abc import (
    ISecureTransport,
)
from libp2p.crypto.keys import (
    KeyPair,
)
from libp2p.peer.id import (
    ID,
)


def default_secure_bytes_provider(n: int) -> bytes:
    return secrets.token_bytes(n)


class BaseSecureTransport(ISecureTransport):
    """
    ``BaseSecureTransport`` is not fully instantiated from its abstract classes
    as it is only meant to be used in clases that derive from it.

    Clients can provide a strategy to get cryptographically secure bytes
    of a given length. A default implementation is provided using the
    ``secrets`` module from the standard library.
    """

    def __init__(
        self,
        local_key_pair: KeyPair,
        secure_bytes_provider: Callable[[int], bytes] = default_secure_bytes_provider,
    ) -> None:
        self.local_private_key = local_key_pair.private_key
        self.local_peer = ID.from_pubkey(local_key_pair.public_key)
        self.secure_bytes_provider = secure_bytes_provider
