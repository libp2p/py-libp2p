from abc import ABC, abstractmethod
from typing import Sequence

from libp2p.stream_muxer.abc import IMuxedStream
from libp2p.typing import TProtocol


class IMultiselectClient(ABC):
    """
    Client for communicating with receiver's multiselect
    module in order to select a protocol id to communicate over
    """

    @abstractmethod
    async def select_protocol_or_fail(
        self, protocol: TProtocol, stream: IMuxedStream
    ) -> TProtocol:
        """
        Send message to multiselect selecting protocol
        and fail if multiselect does not return same protocol
        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """

    @abstractmethod
    async def select_one_of(
        self, protocols: Sequence[TProtocol], stream: IMuxedStream
    ) -> TProtocol:
        """
        For each protocol, send message to multiselect selecting protocol
        and fail if multiselect does not return same protocol. Returns first
        protocol that multiselect agrees on (i.e. that multiselect selects)
        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """
