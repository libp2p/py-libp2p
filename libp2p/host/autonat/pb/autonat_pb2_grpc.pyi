from typing import Any, List, Optional, Tuple, Union
import grpc

class AutoNATStub:
    def __init__(self, channel: grpc.Channel) -> None: ...
    Dial: Any

class AutoNATServicer:
    def Dial(self, request: Any, context: Any) -> Any: ...

def add_AutoNATServicer_to_server(servicer: AutoNATServicer, server: Any) -> None: ...

class AutoNAT:
    @staticmethod
    def Dial(
        request: Any,
        target: str,
        options: Tuple[Any, ...] = (),
        channel_credentials: Optional[Any] = None,
        call_credentials: Optional[Any] = None,
        insecure: bool = False,
        compression: Optional[Any] = None,
        wait_for_ready: Optional[bool] = None,
        timeout: Optional[float] = None,
        metadata: Optional[List[Tuple[str, str]]] = None,
    ) -> Any: ...
