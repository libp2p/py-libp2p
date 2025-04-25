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
    Status enumeration for the AutoNAT service.

    This class defines the possible states of NAT traversal for a node:
    - UNKNOWN (0): The node's NAT status has not been determined yet
    - PUBLIC (1): The node is publicly reachable
    - PRIVATE (2): The node is behind NAT and not directly reachable
    """

    UNKNOWN = 0
    PUBLIC = 1
    PRIVATE = 2


class AutoNATService:
    """
    Service for determining if a node is publicly reachable.

    The AutoNAT service helps nodes determine their NAT status by attempting
    to establish connections with other peers. It maintains a record of dial
    attempts and their results to classify the node as public or private.
    """

    def __init__(self, host: BasicHost) -> None:
        """
        Initialize the AutoNAT service.

        Args:
        ----
        host (BasicHost): The libp2p host instance that provides networking
            capabilities for the AutoNAT service, including peer discovery
            and connection management.

        """
        self.host = host
        self.peerstore: IPeerStore = host.get_peerstore()
        self.status = AutoNATStatus.UNKNOWN
        self.dial_results: dict[ID, bool] = {}

    async def handle_stream(self, stream: NetStream) -> None:
        """
        Handle an incoming stream.

        :param stream: The stream to handle
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
        Handle an AutoNAT request.

        Parses and processes incoming AutoNAT requests, routing them to
        appropriate handlers based on the message type.

        Args:
        ----
        request (bytes | Message): The request bytes that need to be parsed
            and handled by the AutoNAT service, or a Message object directly.

        Returns
        -------
        Message: The response message containing the result of the request.
            Returns an error response if the request type is not recognized.

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
        Handle a DIAL request.

        Processes dial requests by attempting to connect to specified peers
        and recording the results of these connection attempts.

        Args:
        ----
        message (Message): The request message containing the dial request
            parameters and peer information.

        Returns
        -------
        Message: The response message containing the dial results, including
            success/failure status for each attempted peer connection.

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

        # Initialize the dial_response field if it doesn't exist
        if not hasattr(response, "dial_response"):
            response.dial_response = DialResponse()
        response.dial_response.CopyFrom(dial_response)
        return response

    async def _try_dial(self, peer_id: ID) -> bool:
        """
        Try to dial a peer.

        Attempts to establish a connection with a specified peer to test
        NAT traversal capabilities.

        Args:
        ----
        peer_id (ID): The identifier of the peer to attempt to dial for
            NAT traversal testing.

        Returns
        -------
        bool: True if the dial was successful and a connection could be
            established, False if the connection attempt failed.

        """
        try:
            stream = await self.host.new_stream(peer_id, [AUTONAT_PROTOCOL_ID])
            await stream.close()
            return True
        except Exception:
            return False

    def get_status(self) -> int:
        """
        Get the current AutoNAT status.

        Retrieves the current NAT status of the node based on previous
        dial attempts and their results.

        Returns
        -------
        int: The current status as an integer:
            - AutoNATStatus.UNKNOWN (0): Status not yet determined
            - AutoNATStatus.PUBLIC (1): Node is publicly reachable
            - AutoNATStatus.PRIVATE (2): Node is behind NAT

        """
        return self.status

    def update_status(self) -> None:
        """
        Update the AutoNAT status based on dial results.

        Analyzes the results of previous dial attempts to determine if the
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
