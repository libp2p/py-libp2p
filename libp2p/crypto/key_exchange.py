from collections.abc import Callable
import sys
from typing import (
    cast,
)

if sys.platform != "win32":
    from fastecdsa.encoding import (
        util,
    )

    int_bytelen = util.int_bytelen
else:
    from math import (
        ceil,
        log2,
    )

    def int_bytelen(n: int) -> int:
        if n == 0:
            return 1
        return ceil(log2(abs(n) + 1) / 8)


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

        remote_point = ECCPublicKey.from_bytes(serialized_remote_public_key, curve_type)

        if sys.platform != "win32":
            secret_point = remote_point.impl * private_key.impl
            secret_x_coordinate = secret_point.x
            byte_size = int_bytelen(secret_x_coordinate)
            return secret_x_coordinate.to_bytes(byte_size, byteorder="big")
        else:
            # Windows implementation using coincurve
            shared_key = private_key.impl.ecdh(remote_point.impl.public_key)
            return shared_key

    return key_pair.public_key, _key_exchange
