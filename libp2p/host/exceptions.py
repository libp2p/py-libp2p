from libp2p.exceptions import (
    BaseLibp2pError,
)


class HostException(BaseLibp2pError):
    """A generic exception  in `IHost`."""


class ConnectionFailure(HostException):
    pass


class StreamFailure(HostException):
    pass
