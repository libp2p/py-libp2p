import logging

from multiaddr import (
    Multiaddr,
)

from libp2p.custom_types import (
    TProtocol,
)
from libp2p.host.autonat.pb.autonat_pb2 import (
    DialResponse,
    Message,
    Status,
    Type,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.network.stream.net_stream import (
    NetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import (
    IPeerStore,
)
from libp2p.utils.varint import (
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)

AUTONAT_PROTOCOL_ID = TProtocol("/libp2p/autonat/1.0.0")

logger = logging.getLogger(__name__)


class AutoNATStatus:
    """
    AutoNAT Status Enumeration.

    Defines the possible states of NAT traversal for a libp2p node:
    - UNKNOWN (0): Initial state, NAT status not yet determined
    - PUBLIC (1): Node is publicly reachable from the internet
    - PRIVATE (2): Node is behind NAT, not directly reachable
    """

    UNKNOWN = 0
    PUBLIC = 1
    PRIVATE = 2


class AutoNATService:
    """
    AutoNAT Service Implementation.

    A service that helps libp2p nodes determine their NAT status by
    attempting to establish connections with other peers. The service
    maintains a record of dial attempts and their results to classify
    the node as either public or private.
    """

    def __init__(self, host: BasicHost) -> None:
        """
        Create a new AutoNAT service instance.

        Parameters
        ----------
        host : BasicHost
            The libp2p host instance that provides networking capabilities
            for the AutoNAT service, including peer discovery and connection
            management.

        """
        self.host = host
        self.peerstore: IPeerStore = host.get_peerstore()
        self.status = AutoNATStatus.UNKNOWN
        self.dial_results: dict[ID, bool] = {}

    async def handle_stream(self, stream: NetStream) -> None:
        """
        Process an incoming AutoNAT stream.

        Parameters
        ----------
        stream : NetStream
            The network stream to handle for AutoNAT protocol communication.

        """
        try:
            request_bytes = await read_varint_prefixed_bytes(stream)
            request = Message()
            request.ParseFromString(request_bytes)
            response = await self._handle_request(request)
            await stream.write(encode_varint_prefixed(response.SerializeToString()))
        except Exception as e:
            logger.error("Error handling AutoNAT stream: %s", str(e))
        finally:
            await stream.close()

    async def _handle_request(self, request: bytes | Message) -> Message:
        """
        Process an AutoNAT protocol request.

        Parameters
        ----------
        request : Union[bytes, Message]
            The request data to be processed, either as raw bytes or a
            pre-parsed Message object.

        Returns
        -------
        Message
            The response message containing the result of processing the
            request. Returns an error response if the request type is not
            recognized.

        """
        if isinstance(request, bytes):
            message = Message()
            message.ParseFromString(request)
        else:
            message = request

        if message.type == Type.DIAL:
            response = await self._handle_dial(message)
            return response

        # Handle unknown request type
        response = Message()
        response.type = Type.DIAL_RESPONSE
        error_response = DialResponse()
        error_response.status = Status.E_INTERNAL_ERROR
        response.dial_response.CopyFrom(error_response)
        return response

    async def _handle_dial(self, message: Message) -> Message:
        """
        Process an AutoNAT dial request.

        Dials the requesting peer back on its advertised addresses and
        reports the outcome, mirroring the canonical AutoNAT behaviour.

        Parameters
        ----------
        message : Message
            The dial request message containing the peer to dial back.

        Returns
        -------
        Message
            A DIAL_RESPONSE carrying the dial outcome and, on success, the
            address that was successfully dialed.

        """
        response = Message()
        response.type = Type.DIAL_RESPONSE
        dial_response = DialResponse()

        peer_id = ID(message.dial.peer.id)
        dialed_addr = await self._try_dial(peer_id, list(message.dial.peer.addrs))
        self.dial_results[peer_id] = dialed_addr is not None

        if dialed_addr is not None:
            dial_response.status = Status.OK
            dial_response.addr = dialed_addr
        else:
            dial_response.status = Status.E_DIAL_ERROR

        response.dial_response.CopyFrom(dial_response)
        return response

    async def _try_dial(self, peer_id: ID, addrs: list[bytes]) -> bytes | None:
        """
        Attempt to establish a connection with a peer.

        Tries each advertised address in turn and returns the first one
        that yields a connection.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to attempt to dial.
        addrs : list[bytes]
            The peer's advertised addresses to try.

        Returns
        -------
        bytes | None
            The successfully dialed address, or None if all attempts failed.

        """
        candidates: list[bytes] = list(addrs)
        try:
            candidates.extend(self.peerstore.addrs(peer_id))
        except Exception:
            pass
        for addr in candidates:
            try:
                await self.host.connect(PeerInfo(peer_id, [Multiaddr(addr)]))
                return bytes(addr)
            except Exception:
                continue
        return None

    def get_status(self) -> int:
        """
        Retrieve the current AutoNAT status.

        Returns
        -------
        int
            The current NAT status:
            - AutoNATStatus.UNKNOWN (0): Status not yet determined
            - AutoNATStatus.PUBLIC (1): Node is publicly reachable
            - AutoNATStatus.PRIVATE (2): Node is behind NAT

        """
        return self.status

    def update_status(self) -> None:
        """
        Update the AutoNAT status based on dial results.

        Analyzes the accumulated dial attempt results to determine if the
        node is publicly reachable. The node is considered public if at
        least two successful dial attempts have been recorded.
        """
        if not self.dial_results:
            self.status = AutoNATStatus.UNKNOWN
            return

        success_count = sum(1 for success in self.dial_results.values() if success)
        if success_count >= 2:
            self.status = AutoNATStatus.PUBLIC
        else:
            self.status = AutoNATStatus.PRIVATE
