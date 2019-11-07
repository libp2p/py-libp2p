from collections import OrderedDict
from typing import TYPE_CHECKING

from libp2p.host.host_interface import IHost
from libp2p.host.ping import ID as PingID
from libp2p.host.ping import handle_ping
from libp2p.identity.identify.protocol import ID as IdentifyID
from libp2p.identity.identify.protocol import identify_handler_for

if TYPE_CHECKING:
    from libp2p.typing import TProtocol, StreamHandlerFn


def get_default_protocols(host: IHost) -> "OrderedDict[TProtocol, StreamHandlerFn]":
    return OrderedDict(
        ((IdentifyID, identify_handler_for(host)), (PingID, handle_ping))
    )
