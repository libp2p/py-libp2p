from collections import (
    OrderedDict,
)
from typing import (
    TYPE_CHECKING,
)

from libp2p.abc import (
    IHost,
)
from libp2p.host.ping import (
    ID as PingID,
    handle_ping,
)
from libp2p.identity.identify.identify import (
    ID as IdentifyID,
    identify_handler_for,
)

if TYPE_CHECKING:
    from libp2p.custom_types import (
        StreamHandlerFn,
        TProtocol,
    )


def get_default_protocols(host: IHost) -> "OrderedDict[TProtocol, StreamHandlerFn]":
    return OrderedDict(
        ((IdentifyID, identify_handler_for(host)), (PingID, handle_ping))
    )
