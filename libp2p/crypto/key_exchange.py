from collections.abc import Callable
from typing import (
    cast,
)

from cryptography.hazmat.primitives.asymmetric import ec

from libp2p.crypto.ecc import (
    ECCPrivateKey,
    ECCPublicKey,
    create_new_key_pair,
)
from libp2p.crypto.keys import (
    PublicKey,
)

SharedKeyGenerator = Callable[[bytes], bytes]


def create_ephemeral_key_pair(curve_type: str) -> tuple[PublicKey, SharedKeyGenerator]:
    """Facilitates ECDH key exchange."""
    if curve_type != "P-256":
        raise NotImplementedError()

    key_pair = create_new_key_pair(curve_type)

    def _key_exchange(serialized_remote_public_key: bytes) -> bytes:
        private_key = cast(ECCPrivateKey, key_pair.private_key)

        remote_public_key = ECCPublicKey.from_bytes(
            serialized_remote_public_key, curve_type
        )

        # The shared secret is the x coordinate, without its leading zero bytes.
        shared_key = private_key.impl.exchange(ec.ECDH(), remote_public_key.impl)
        return shared_key.lstrip(b"\x00")

    return key_pair.public_key, _key_exchange
