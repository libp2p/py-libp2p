from collections import OrderedDict
from typing import TYPE_CHECKING

from libp2p.host.host_interface import IHost

if TYPE_CHECKING:
    from libp2p.typing import TProtocol, StreamHandlerFn


def get_default_protocols(host: IHost) -> "OrderedDict[TProtocol, StreamHandlerFn]":
    return OrderedDict()
