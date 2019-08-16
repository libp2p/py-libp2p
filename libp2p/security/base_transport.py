from libp2p.crypto.keys import KeyPair
from libp2p.peer.id import ID
from libp2p.security.secure_transport_interface import ISecureTransport


class BaseSecureTransport(ISecureTransport):
    """
    ``BaseSecureTransport`` is not fully instantiated from its abstract classes as it
    is only meant to be used in clases that derive from it.
    """

    def __init__(self, local_key_pair: KeyPair) -> None:
        self.local_private_key = local_key_pair.private_key
        self.local_peer = ID.from_pubkey(local_key_pair.public_key)
