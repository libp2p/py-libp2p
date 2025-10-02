# Base Resource Scope that will be inherited by all the other scopes.

from .limits import BaseLimit
from .metrics import Metrics


class ResourceScope:
    def __init__(
        self,
        name: str,
        limits: BaseLimit,
        metrics: Metrics,
        parentscopes: list["ResourceScope"],
    ) -> None:
        self.name = name
        self.limits = limits
        self.metrics = metrics
        self.parentscopes = parentscopes

    def check_memory(self) -> None:
        pass

    def reserve_memory(self) -> None:
        pass

    def release_memory(self) -> None:
        pass

    def addstream(self) -> None:
        pass


class SystemScope:
    pass


class TransientScope:
    pass


class ServiceScope:
    pass


class PeerScope:
    pass


class ConnectionScope:
    pass


class StreamScope:
    def __init__(self) -> None:
        pass
