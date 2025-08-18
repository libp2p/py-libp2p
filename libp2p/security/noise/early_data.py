from abc import ABC, abstractmethod

from libp2p.abc import IRawConnection
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

from .pb import noise_pb2 as noise_pb


class EarlyDataHandler(ABC):
    """Interface for handling early data during Noise handshake"""

    @abstractmethod
    async def send(
        self, conn: IRawConnection, peer_id: ID
    ) -> noise_pb.NoiseExtensions | None:
        """Called to generate early data to send during handshake"""
        pass

    @abstractmethod
    async def received(
        self, conn: IRawConnection, extensions: noise_pb.NoiseExtensions | None
    ) -> None:
        """Called when early data is received during handshake"""
        pass


class TransportEarlyDataHandler(EarlyDataHandler):
    """Default early data handler for muxer negotiation"""

    def __init__(self, supported_muxers: list[TProtocol]):
        self.supported_muxers = supported_muxers
        self.received_muxers: list[TProtocol] = []

    async def send(
        self, conn: IRawConnection, peer_id: ID
    ) -> noise_pb.NoiseExtensions | None:
        """Send our supported muxers list"""
        if not self.supported_muxers:
            return None

        extensions = noise_pb.NoiseExtensions()
        # Convert TProtocol to string for serialization
        extensions.stream_muxers[:] = [str(muxer) for muxer in self.supported_muxers]
        return extensions

    async def received(
        self, conn: IRawConnection, extensions: noise_pb.NoiseExtensions | None
    ) -> None:
        """Store received muxers list"""
        if extensions and extensions.stream_muxers:
            self.received_muxers = [
                TProtocol(muxer) for muxer in extensions.stream_muxers
            ]

    def match_muxers(self, is_initiator: bool) -> TProtocol | None:
        """Find first common muxer between local and remote"""
        if is_initiator:
            # Initiator: find first local muxer that remote supports
            for local_muxer in self.supported_muxers:
                if local_muxer in self.received_muxers:
                    return local_muxer
        else:
            # Responder: find first remote muxer that we support
            for remote_muxer in self.received_muxers:
                if remote_muxer in self.supported_muxers:
                    return remote_muxer
        return None
