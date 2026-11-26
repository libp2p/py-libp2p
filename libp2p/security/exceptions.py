from libp2p.exceptions import (
    BaseLibp2pError,
)


class HandshakeFailure(BaseLibp2pError):
    protocol_id: str | None = None


class SecurityError(BaseLibp2pError):
    pass
