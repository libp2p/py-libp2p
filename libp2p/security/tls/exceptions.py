"""TLS security transport exceptions."""

from libp2p.exceptions import BaseLibp2pError


class TLSError(BaseLibp2pError):
    """Base exception for TLS security transport errors."""

    pass


class MissingLibp2pExtensionError(TLSError):
    """
    Raised when a peer certificate does not contain the required libp2p
    X.509 extension (OID 1.3.6.1.4.1.53594.1.1).

    This typically happens with autotls certificates that are valid TLS
    certificates but don't carry the embedded libp2p public key.
    """

    pass
