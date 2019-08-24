from typing import Callable, Tuple, cast

from Crypto.Math.Numbers import Integer
import Crypto.PublicKey.ECC as ECC

from libp2p.crypto.ecc import ECCPrivateKey, create_new_key_pair
from libp2p.crypto.keys import PublicKey

SharedKeyGenerator = Callable[[bytes], bytes]


def create_ephemeral_key_pair(curve_type: str) -> Tuple[PublicKey, SharedKeyGenerator]:
    """
    Facilitates ECDH key exchange.
    """
    if curve_type != "P-256":
        raise NotImplementedError()

    key_pair = create_new_key_pair(curve_type)

    def _key_exchange(serialized_remote_public_key: bytes) -> bytes:
        remote_public_key = ECC.import_key(serialized_remote_public_key)
        curve_point = remote_public_key.pointQ
        private_key = cast(ECCPrivateKey, key_pair.private_key)
        secret_point = curve_point * private_key.impl.d
        byte_size = secret_point.size_in_bytes()
        return cast(Integer, secret_point.x).to_bytes(byte_size)

    return key_pair.public_key, _key_exchange
