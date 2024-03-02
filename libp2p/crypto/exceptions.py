from libp2p.exceptions import (
    BaseLibp2pError,
)


class CryptographyError(BaseLibp2pError):
    pass


class MissingDeserializerError(CryptographyError):
    """
    Raise if the requested deserialization routine is missing for some type
    of cryptographic key.
    """
