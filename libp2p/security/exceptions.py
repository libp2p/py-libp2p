from libp2p.exceptions import (
    BaseLibp2pError,
)


class HandshakeFailure(BaseLibp2pError):
    pass


class SecurityError(BaseLibp2pError):
    pass
