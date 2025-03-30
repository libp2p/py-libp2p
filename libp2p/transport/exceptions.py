from libp2p.exceptions import (
    BaseLibp2pError,
)


class TransportError(BaseLibp2pError):
    """Raised when there is an error in the transport layer."""


class OpenConnectionError(BaseLibp2pError):
    pass


class UpgradeFailure(BaseLibp2pError):
    pass


class SecurityUpgradeFailure(UpgradeFailure):
    pass


class MuxerUpgradeFailure(UpgradeFailure):
    pass
