from libp2p.exceptions import BaseLibp2pError


# TODO: Add `BaseLibp2pError` and `UpgradeFailure` can inherit from it?
class UpgradeFailure(BaseLibp2pError):
    pass


class SecurityUpgradeFailure(UpgradeFailure):
    pass


class MuxerUpgradeFailure(UpgradeFailure):
    pass


class HandshakeFailure(BaseLibp2pError):
    pass
