import logging

from libp2p.custom_types import (
    TProtocol,
)
from libp2p.host.autonat.pb.autonat_pb2 import (
    DialResponse,
    Message,
    PeerInfo,
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
from libp2p.peer.peerstore import (
    IPeerStore,
)

AUTONAT_PROTOCOL_ID = TProtocol("/ipfs/autonat/1.0.0")

logger = logging.getLogger("libp2p.host.autonat")


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
            request_bytes = await stream.read()
            request = Message()
            request.ParseFromString(request_bytes)
            response = await self._handle_request(request)
            await stream.write(response.SerializeToString())
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

        if message.type == Type.Value("DIAL"):
            response = await self._handle_dial(message)
            return response

        # Handle unknown request type
        response = Message()
        response.type = Type.Value("DIAL_RESPONSE")
        error_response = DialResponse()
        error_response.status = Status.E_INTERNAL_ERROR
        response.dial_response.CopyFrom(error_response)
        return response

    async def _handle_dial(self, message: Message) -> Message:
        """
        Process an AutoNAT dial request.

        Parameters
        ----------
        message : Message
            The dial request message containing peer information to test
            connectivity.

        Returns
        -------
        Message
            The response message containing the results of the dial
            attempts, including success/failure status for each peer.

        """
        response = Message()
        response.type = Type.Value("DIAL_RESPONSE")
        dial_response = DialResponse()
        dial_response.status = Status.OK

        for peer in message.dial.peers:
            peer_id = ID(peer.id)
            if peer_id in self.dial_results:
                success = self.dial_results[peer_id]
            else:
                success = await self._try_dial(peer_id)
                self.dial_results[peer_id] = success

            peer_info = PeerInfo()
            peer_info.id = peer_id.to_bytes()
            peer_info.addrs.extend(peer.addrs)
            peer_info.success = success
            dial_response.peers.append(peer_info)

        response.dial_response.CopyFrom(dial_response)
        return response

    async def _try_dial(self, peer_id: ID) -> bool:
        """
        Attempt to establish a connection with a peer.

        Parameters
        ----------
        peer_id : ID
            The identifier of the peer to attempt to dial.

        Returns
        -------
        bool
            True if the connection was successfully established,
            False if the connection attempt failed.

        """
        try:
            stream = await self.host.new_stream(peer_id, [AUTONAT_PROTOCOL_ID])
            await stream.close()
            return True
        except Exception:
            return False

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
