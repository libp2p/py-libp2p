from abc import ABC, abstractmethod
from typing import Sequence

from libp2p.protocol_muxer.multiselect_communicator_interface import (
    IMultiselectCommunicator,
)
from libp2p.typing import TProtocol


class IMultiselectClient(ABC):
    """Client for communicating with receiver's multiselect module in order to
    select a protocol id to communicate over."""

    async def handshake(self, communicator: IMultiselectCommunicator) -> None:
        """
        Ensure that the client and multiselect are both using the same
        multiselect protocol.

        :param stream: stream to communicate with multiselect over
        :raise Exception: multiselect protocol ID mismatch
        """

    @abstractmethod
    async def select_one_of(
        self, protocols: Sequence[TProtocol], communicator: IMultiselectCommunicator
    ) -> TProtocol:
        """
        For each protocol, send message to multiselect selecting protocol and
        fail if multiselect does not return same protocol. Returns first
        protocol that multiselect agrees on (i.e. that multiselect selects)

        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """

    async def try_select(
        self, communicator: IMultiselectCommunicator, protocol: TProtocol
    ) -> TProtocol:
        """
        Try to select the given protocol or raise exception if fails.

        :param communicator: communicator to use to communicate with counterparty
        :param protocol: protocol to select
        :raise Exception: error in protocol selection
        :return: selected protocol
        """
