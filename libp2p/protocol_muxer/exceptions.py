from libp2p.exceptions import (
    BaseLibp2pError,
)


class MultiselectCommunicatorError(BaseLibp2pError):
    """Raised when an error occurs during read/write via communicator."""


class MultiselectError(BaseLibp2pError):
    """Raised when an error occurs in multiselect process."""


class MultiselectClientError(BaseLibp2pError):
    """Raised when an error occurs in protocol selection process."""
