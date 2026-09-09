from collections import (
    OrderedDict,
)
import logging
from typing import (
    Generic,
    TypeVar,
)

from libp2p.custom_types import (
    TProtocol,
)
from libp2p.io.abc import (
    ReadWriteCloser,
)

from .exceptions import (
    MultiselectError,
)
from .multiselect import (
    DEFAULT_NEGOTIATE_TIMEOUT,
    Multiselect,
)
from .multiselect_client import (
    MultiselectClient,
)
from .multiselect_communicator import (
    MultiselectCommunicator,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class GenericMultistreamSelector(Generic[T]):
    """
    A generic multistream-select protocol negotiator.

    Consolidates the duplicated negotiation logic from SecurityMultistream
    and MuxerMultistream into a single reusable class. Both security and
    muxer layers use this selector for negotiation only; the caller is
    responsible for applying the chosen handler (e.g. securing the connection
    or instantiating the muxer).
    """

    handlers: "OrderedDict[TProtocol, T]"
    multiselect: Multiselect
    multiselect_client: MultiselectClient

    def __init__(self) -> None:
        self.handlers = OrderedDict()
        self.multiselect = Multiselect()
        self.multiselect_client = MultiselectClient()

    def add_handler(self, protocol: TProtocol, handler: T) -> None:
        """
        Add a protocol and its handler.

        Re-adding an existing protocol moves it to the end, updating its
        precedence in negotiation.

        :param protocol: the protocol name negotiated via multistream-select.
        :param handler: the handler or factory associated with the protocol.
        """
        self.handlers.pop(protocol, None)
        self.handlers[protocol] = handler
        self.multiselect.add_handler(protocol, None)

    def get_protocols(self) -> list[TProtocol]:
        """
        Return the list of registered protocols in precedence order.

        :return: list of protocol names.
        """
        return list(self.handlers.keys())

    async def select(
        self,
        conn: ReadWriteCloser,
        is_initiator: bool,
        negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> "tuple[TProtocol, T]":
        """
        Negotiate and select a protocol with the remote peer.

        :param conn: connection supporting read/write (ReadWriteCloser).
        :param is_initiator: True if we initiated the connection.
        :param negotiate_timeout: timeout for negotiation in seconds.
        :return: tuple of (selected_protocol, handler).
        :raises MultiselectError: if listener-side negotiation fails or no protocol
            is selected.
        :raises MultiselectClientError: if initiator-side negotiation via
            ``MultiselectClient.select_one_of`` fails.
        """
        communicator = MultiselectCommunicator(conn)
        protocol: TProtocol | None

        if is_initiator:
            protocol = await self.multiselect_client.select_one_of(
                tuple(self.handlers.keys()), communicator, negotiate_timeout
            )
        else:
            protocol, _ = await self.multiselect.negotiate(
                communicator, negotiate_timeout
            )

        if protocol is None:
            raise MultiselectError("Failed to negotiate: no protocol selected")

        return protocol, self.handlers[protocol]
