"""
Bitswap protocol errors.
"""


class BitswapError(Exception):
    """Base exception for Bitswap errors."""

    pass


class InvalidBlockError(BitswapError):
    """Raised when a block is invalid or malformed."""

    pass


class BlockTooLargeError(BitswapError):
    """Raised when a block exceeds the maximum size."""

    pass


class MessageTooLargeError(BitswapError):
    """Raised when a message exceeds the maximum size."""

    pass


class TimeoutError(BitswapError):
    """Raised when an operation times out."""

    pass


class BlockNotFoundError(BitswapError):
    """Raised when a requested block is not found."""

    pass


class BlockUnavailableError(BitswapError):
    """Raised when a peer confirms they don't have a requested block (DontHave)."""

    pass


class InvalidCIDError(BitswapError):
    """Raised when a CID is invalid."""

    pass
