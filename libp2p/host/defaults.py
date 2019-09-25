from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libp2p.typing import TProtocol, StreamHandlerFn

DEFAULT_HOST_PROTOCOLS: "OrderedDict[TProtocol, StreamHandlerFn]" = OrderedDict()
