from libp2p.abc import (
    ISecureConn,
)
from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.peer.id import (
    ID,
)


class BaseSession(ISecureConn):
    """
    ``BaseSession`` is not fully instantiated from its abstract classes as
    it is only meant to be used in clases that derive from it.
    """

    local_peer: ID
    local_private_key: PrivateKey
    remote_peer: ID
    remote_permanent_pubkey: PublicKey

    def __init__(
        self,
        *,
        local_peer: ID,
        local_private_key: PrivateKey,
        remote_peer: ID,
        remote_permanent_pubkey: PublicKey,
        is_initiator: bool,
    ) -> None:
        self.local_peer = local_peer
        self.local_private_key = local_private_key
        self.remote_peer = remote_peer
        self.remote_permanent_pubkey = remote_permanent_pubkey
        self.is_initiator = is_initiator

    def get_local_peer(self) -> ID:
        return self.local_peer

    def get_local_private_key(self) -> PrivateKey:
        return self.local_private_key

    def get_remote_peer(self) -> ID:
        return self.remote_peer

    def get_remote_public_key(self) -> PublicKey:
        return self.remote_permanent_pubkey
