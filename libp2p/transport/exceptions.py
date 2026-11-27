from libp2p.exceptions import (
    BaseLibp2pError,
)


class OpenConnectionError(BaseLibp2pError):
    pass


class UpgradeFailure(BaseLibp2pError):
    pass


class SecurityUpgradeFailure(UpgradeFailure):
    protocol_id: str | None = None


class MuxerUpgradeFailure(UpgradeFailure):
    pass
