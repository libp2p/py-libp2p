from dataclasses import (
    dataclass,
)
import hmac

from Crypto.Cipher import (
    AES,
)
import Crypto.Util.Counter as Counter


class InvalidMACException(Exception):
    pass


@dataclass(frozen=True)
class EncryptionParameters:
    cipher_type: str
    hash_type: str
    iv: bytes
    mac_key: bytes
    cipher_key: bytes


class MacAndCipher:
    def __init__(self, parameters: EncryptionParameters) -> None:
        self.authenticator = hmac.new(
            parameters.mac_key, digestmod=parameters.hash_type
        )
        iv_bit_size = 8 * len(parameters.iv)
        cipher = AES.new(
            parameters.cipher_key,
            AES.MODE_CTR,
            counter=Counter.new(
                iv_bit_size,
                initial_value=int.from_bytes(parameters.iv, byteorder="big"),
            ),
        )
        self.cipher = cipher

    def encrypt(self, data: bytes) -> bytes:
        return self.cipher.encrypt(data)

    def authenticate(self, data: bytes) -> bytes:
        authenticator = self.authenticator.copy()
        authenticator.update(data)
        return authenticator.digest()

    def decrypt_if_valid(self, data_with_tag: bytes) -> bytes:
        tag_position = len(data_with_tag) - self.authenticator.digest_size
        data = data_with_tag[:tag_position]
        tag = data_with_tag[tag_position:]

        authenticator = self.authenticator.copy()
        authenticator.update(data)
        expected_tag = authenticator.digest()

        if not hmac.compare_digest(tag, expected_tag):
            raise InvalidMACException(expected_tag, tag)

        return self.cipher.decrypt(data)


def initialize_pair(
    cipher_type: str, hash_type: str, secret: bytes
) -> tuple[EncryptionParameters, EncryptionParameters]:
    """
    Return a pair of ``Keys`` for use in securing a communications channel
    with authenticated encryption derived from the ``secret`` and using the
    requested ``cipher_type`` and ``hash_type``.
    """
    if cipher_type != "AES-128":
        raise NotImplementedError()
    if hash_type != "SHA256":
        raise NotImplementedError()

    iv_size = 16
    cipher_key_size = 16
    hmac_key_size = 20
    seed = b"key expansion"

    params_size = iv_size + cipher_key_size + hmac_key_size
    result = bytearray(2 * params_size)

    authenticator = hmac.new(secret, digestmod=hash_type)
    authenticator.update(seed)
    tag = authenticator.digest()

    i = 0
    len_result = 2 * params_size
    while i < len_result:
        authenticator = hmac.new(secret, digestmod=hash_type)

        authenticator.update(tag)
        authenticator.update(seed)

        another_tag = authenticator.digest()

        remaining_bytes = len(another_tag)

        if i + remaining_bytes > len_result:
            remaining_bytes = len_result - i

        result[i : i + remaining_bytes] = another_tag[0:remaining_bytes]

        i += remaining_bytes

        authenticator = hmac.new(secret, digestmod=hash_type)
        authenticator.update(tag)
        tag = authenticator.digest()

    first_half = result[:params_size]
    second_half = result[params_size:]

    return (
        EncryptionParameters(
            cipher_type,
            hash_type,
            bytes(first_half[0:iv_size]),
            bytes(first_half[iv_size + cipher_key_size :]),
            bytes(first_half[iv_size : iv_size + cipher_key_size]),
        ),
        EncryptionParameters(
            cipher_type,
            hash_type,
            bytes(second_half[0:iv_size]),
            bytes(second_half[iv_size + cipher_key_size :]),
            bytes(second_half[iv_size : iv_size + cipher_key_size]),
        ),
    )
