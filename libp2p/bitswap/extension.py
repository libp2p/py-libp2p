from abc import ABC, abstractmethod
from typing import Any

from libp2p.abc import INetStream
from libp2p.peer.id import ID as PeerID


class IBitswapExtension(ABC):
    """
    Abstract base class for protocol-bound Bitswap extensions.
    Extensions are registered for specific protocol versions to handle messages.
    """

    def set_client(self, client: Any) -> None:
        """
        Set the parent BitswapClient instance.
        """
        self.client = client

    @abstractmethod
    async def process_message(
        self, peer_id: PeerID, msg_bytes: bytes, stream: INetStream
    ) -> bool:
        """
        Process an incoming message.

        Args:
            peer_id: The ID of the peer sending the message
            msg_bytes: The raw bytes of the incoming message
            stream: The network stream to communicate back

        Returns:
            True if the extension fully handled the message and no further
            processing is required.
            False if normal processing should continue.

        """
        pass

    @abstractmethod
    async def process_wantlist(
        self, wantlist: Any, peer_id: PeerID, stream: INetStream
    ) -> bool:
        """
        Process a wantlist specifically.

        Args:
            wantlist: The Wantlist protobuf object
            peer_id: The ID of the peer
            stream: The network stream

        Returns:
            True if the extension handled the wantlist fully.
            False if BitswapClient should process it normally.

        """
        pass
