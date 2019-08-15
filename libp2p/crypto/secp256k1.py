import coincurve
from libp2p.crypto.keys import KeyPair, KeyType, PrivateKey, PublicKey


class Secp256k1PublicKey(PublicKey):
    def __init__(self, impl: coincurve.PublicKey) -> None:
        self.impl = impl

    def to_bytes(self) -> bytes:
        return self.impl.format()

    def get_type(self) -> KeyType:
        return KeyType.Secp256k1

    def verify(self, data: bytes, signature: bytes) -> bool:
        raise NotImplementedError


class Secp256k1PrivateKey(PrivateKey):
    def __init__(self, impl: coincurve.PrivateKey) -> None:
        self.impl = impl

    @classmethod
    def new(cls, secret: bytes = None) -> "Secp256k1PrivateKey":
        private_key_impl = coincurve.PrivateKey(secret)
        return cls(private_key_impl)

    def to_bytes(self) -> bytes:
        return self.impl.secret

    def get_type(self) -> KeyType:
        return KeyType.Secp256k1

    def sign(self, data: bytes) -> bytes:
        raise NotImplementedError

    def get_public_key(self) -> PublicKey:
        public_key_impl = coincurve.PublicKey.from_secret(self.impl.secret)
        return Secp256k1PublicKey(public_key_impl)


def create_new_key_pair(secret: bytes = None) -> KeyPair:
    """
    Returns a new Secp256k1 keypair derived from the provided ``secret``,
    a sequence of bytes corresponding to some integer between 0 and the group order.

    A valid secret is created if ``None`` is passed.
    """
    private_key = Secp256k1PrivateKey.new(secret)
    public_key = private_key.get_public_key()
    return KeyPair(private_key, public_key)
