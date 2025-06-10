"""
QUIC transport specific exceptions.
"""

from libp2p.exceptions import (
    BaseLibp2pError,
)


class QUICError(BaseLibp2pError):
    """Base exception for QUIC transport errors."""


class QUICDialError(QUICError):
    """Exception raised when QUIC dial operation fails."""


class QUICListenError(QUICError):
    """Exception raised when QUIC listen operation fails."""


class QUICConnectionError(QUICError):
    """Exception raised for QUIC connection errors."""


class QUICStreamError(QUICError):
    """Exception raised for QUIC stream errors."""


class QUICConfigurationError(QUICError):
    """Exception raised for QUIC configuration errors."""


class QUICSecurityError(QUICError):
    """Exception raised for QUIC security/TLS errors."""
