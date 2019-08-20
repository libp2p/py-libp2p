# TODO: Add `BaseLibp2pError` and `UpgradeFailure` can inherit from it?
class UpgradeFailure(Exception):
    pass


class SecurityUpgradeFailure(UpgradeFailure):
    pass
