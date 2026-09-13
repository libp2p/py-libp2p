import logging

from multiaddr import (
    Multiaddr,
)
from multiaddr.exceptions import (
    ProtocolLookupError,
)
import trio

from libp2p.abc import (
    INetStream,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.host.autonat.pb.autonat_pb2 import (
    Message,
)
from libp2p.host.basic_host import (
    BasicHost,
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

# Client verdict aggregation follows the spec heuristic: more than three
# servers must agree before the status flips.
CONFIRMATIONS_REQUIRED = 4

_CLIENT_TIMEOUT = 30.0

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


def _normalize_ip(ip: str) -> str:
    """Strip IPv4-mapped IPv6 prefix so comparisons work across families."""
    lowered = ip.lower()
    if lowered.startswith("::ffff:"):
        return lowered[7:]
    return lowered


def _addr_ip(addr: Multiaddr) -> str | None:
    """
    Return the IP embedded in a multiaddr, or None if it carries none.

    A trailing `/p2p/<peer-id>` suffix (as advertised by some
    implementations) is stripped before inspection.
    """
    try:
        try:
            p2p_val = addr.value_for_protocol("p2p")
        except ProtocolLookupError:
            p2p_val = None
        if p2p_val:
            addr = addr.decapsulate(Multiaddr(f"/p2p/{p2p_val}"))
        try:
            return _normalize_ip(addr.value_for_protocol("ip4"))
        except ProtocolLookupError:
            pass
        try:
            return _normalize_ip(addr.value_for_protocol("ip6"))
        except ProtocolLookupError:
            pass
    except Exception:
        pass
    return None


def _is_relayed_stream(stream: INetStream) -> bool:
    """
    Return True if the stream runs over a relayed (p2p-circuit) connection.

    The spec forbids serving dial requests received via relayed connections:
    the requester's IP cannot be validated there.
    """
    try:
        muxed_conn = getattr(stream, "muxed_conn", None)
        get_addrs = getattr(muxed_conn, "get_transport_addresses", None)
        if not callable(get_addrs):
            return False
        addrs = get_addrs() or []
    except Exception:
        return False
    return any("/p2p-circuit" in str(a) for a in addrs)


class AutoNATService:
    """
    AutoNAT Service Implementation.

    Implements both halves of the AutoNAT v1 protocol
    (libp2p/specs autonat-v1, Recommendation):

    - Server: answers dial-back requests from other peers, dialing only
      addresses based on the requester's observed IP and never serving
      requests received over relayed connections.
    - Client: asks other peers to dial it back and aggregates their
      verdicts into a PUBLIC/PRIVATE reachability status.

    Pass ``serve=True`` (default) to answer requests; use
    :meth:`check_reachability` (or :meth:`periodic_check`) to determine
    your own status.
    """

    def __init__(
        self, host: BasicHost, serve: bool = True, confirmations: int | None = None
    ) -> None:
        """
        Create a new AutoNAT service instance.

        Parameters
        ----------
        host : BasicHost
            The libp2p host instance.
        serve : bool
            Register the AutoNAT stream handler so this node answers
            dial-back requests from other peers.
        confirmations : int | None
            Verdicts required before the status flips (spec: more than
            three). Defaults to :data:`CONFIRMATIONS_REQUIRED`.

        """
        self.host = host
        self.peerstore: IPeerStore = host.get_peerstore()
        self.status = AutoNATStatus.UNKNOWN
        self.confirmations = confirmations or CONFIRMATIONS_REQUIRED
        # Server verdicts about us, keyed by reporting server.
        self.dial_results: dict[ID, bool] = {}
        if serve:
            host.set_stream_handler(AUTONAT_PROTOCOL_ID, self.handle_stream)

    # ------------------------------------------------------------------
    # Server side
    # ------------------------------------------------------------------

    async def handle_stream(self, stream: INetStream) -> None:
        """
        Process an incoming AutoNAT stream.

        Parameters
        ----------
        stream : INetStream
            The network stream to handle for AutoNAT protocol communication.

        """
        try:
            request_bytes = await read_varint_prefixed_bytes(stream)
            request = Message()
            request.ParseFromString(request_bytes)
            observed_ip = self._observed_ip(stream)
            response = await self._handle_request(
                request, observed_ip, _is_relayed_stream(stream)
            )
            await stream.write(encode_varint_prefixed(response.SerializeToString()))
        except Exception as e:
            logger.error("Error handling AutoNAT stream: %s", str(e))
        finally:
            await stream.close()

    @staticmethod
    def _observed_ip(stream: INetStream) -> str | None:
        """Return the requester's observed IP, or None if unavailable."""
        try:
            remote = stream.get_remote_address()
        except Exception:
            return None
        if not remote:
            return None
        return _normalize_ip(remote[0])

    async def _handle_request(
        self, request: bytes | Message, observed_ip: str | None, is_relayed: bool
    ) -> Message:
        """
        Process an AutoNAT protocol request.

        Parameters
        ----------
        request : Union[bytes, Message]
            The request data to be processed, either as raw bytes or a
            pre-parsed Message object.
        observed_ip : str | None
            The requester's observed IP address (anti-abuse gating).
        is_relayed : bool
            Whether the request arrived over a relayed connection.

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

        if message.type == Message.DIAL:
            response = await self._handle_dial(message, observed_ip, is_relayed)
            return response

        # Handle unknown request type
        response = Message()
        response.type = Message.DIAL_RESPONSE
        response.dialResponse.status = Message.E_BAD_REQUEST
        response.dialResponse.statusText = "unknown message type"
        return response

    async def _handle_dial(
        self, message: Message, observed_ip: str | None, is_relayed: bool
    ) -> Message:
        """
        Process an AutoNAT dial request.

        Dials the requesting peer back on its advertised addresses and
        reports the outcome, mirroring the canonical AutoNAT behaviour.
        Only addresses based on the requester's observed IP are dialed;
        requests over relayed connections are refused outright.

        Parameters
        ----------
        message : Message
            The dial request message containing the peer to dial back.
        observed_ip : str | None
            The requester's observed IP address.
        is_relayed : bool
            Whether the request arrived over a relayed connection.

        Returns
        -------
        Message
            A DIAL_RESPONSE carrying the dial outcome and, on success, the
            address that was successfully dialed.

        """
        response = Message()
        response.type = Message.DIAL_RESPONSE

        if is_relayed:
            response.dialResponse.status = Message.E_DIAL_REFUSED
            response.dialResponse.statusText = (
                "dial requests over relayed connections are refused"
            )
            return response

        peer_id = ID(message.dial.peer.id)
        dialable = self._filter_by_observed_ip(
            [bytes(a) for a in message.dial.peer.addrs], observed_ip
        )
        if not dialable:
            response.dialResponse.status = Message.E_DIAL_REFUSED
            response.dialResponse.statusText = (
                "no advertised address matches the observed IP"
            )
            return response

        dialed_addr = await self._try_dial(peer_id, dialable)

        if dialed_addr is not None:
            response.dialResponse.status = Message.OK
            response.dialResponse.addr = dialed_addr
        else:
            response.dialResponse.status = Message.E_DIAL_ERROR
            response.dialResponse.statusText = "all dials failed"

        return response

    @staticmethod
    def _filter_by_observed_ip(
        addrs: list[bytes], observed_ip: str | None
    ) -> list[bytes]:
        """
        Keep only candidate addresses based on the observed IP.

        The spec forbids dialing anything else (amplification-attack
        prevention). Without an observed IP nothing is dialable.
        """
        if observed_ip is None:
            return []
        dialable = []
        for raw in addrs:
            try:
                ip = _addr_ip(Multiaddr(raw))
            except Exception:
                continue
            if ip == observed_ip:
                dialable.append(raw)
        return dialable

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
            The peer's advertised addresses to try. Callers must ensure
            these passed the observed-IP gate.

        Returns
        -------
        bytes | None
            The successfully dialed address, or None if all attempts failed.

        """
        for addr in addrs:
            try:
                await self.host.connect(PeerInfo(peer_id, [Multiaddr(addr)]))
                return bytes(addr)
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Client side
    # ------------------------------------------------------------------

    async def query_server(
        self,
        server_id: ID,
        addrs: list[bytes] | None = None,
        timeout: float = _CLIENT_TIMEOUT,
    ) -> tuple[int, bytes | None]:
        """
        Ask a server to dial us back and return its verdict.

        Parameters
        ----------
        server_id : ID
            The peer to request a dial-back from.
        addrs : list[bytes] | None
            Addresses to advertise (defaults to our listen addresses).
        timeout : float
            Seconds to wait for the verdict.

        Returns
        -------
        tuple[int, bytes | None]
            The ``ResponseStatus`` value and, on success, the address the
            server reached us at. Transport-level failures raise.

        """
        if addrs is None:
            addrs = [a.to_bytes() for a in self.host.get_addrs()]
        request = Message()
        request.type = Message.DIAL
        request.dial.peer.id = self.host.get_id().to_bytes()
        for raw in addrs:
            request.dial.peer.addrs.append(raw)

        stream = None
        try:
            with trio.fail_after(timeout):
                stream = await self.host.new_stream(server_id, [AUTONAT_PROTOCOL_ID])
                await stream.write(encode_varint_prefixed(request.SerializeToString()))
                response_bytes = await read_varint_prefixed_bytes(stream)
        finally:
            if stream is not None:
                await stream.close()

        response = Message()
        response.ParseFromString(response_bytes)
        status = int(response.dialResponse.status)
        addr = (
            bytes(response.dialResponse.addr)
            if response.dialResponse.HasField("addr")
            else None
        )
        self.dial_results[server_id] = status == int(Message.OK)
        return status, addr

    def update_status(self) -> None:
        """
        Update the AutoNAT status from stored server verdicts.

        Follows the spec heuristic: more than three servers must agree.
        With :data:`CONFIRMATIONS_REQUIRED` confirmations of success the
        node is PUBLIC; with that many failures it is PRIVATE. Anything
        in between leaves the status unchanged.
        """
        if not self.dial_results:
            self.status = AutoNATStatus.UNKNOWN
            return

        required = self.confirmations
        success_count = sum(1 for success in self.dial_results.values() if success)
        failure_count = len(self.dial_results) - success_count
        if success_count >= required:
            self.status = AutoNATStatus.PUBLIC
        elif failure_count >= required:
            self.status = AutoNATStatus.PRIVATE

    async def check_reachability(self, servers: list[ID]) -> int:
        """
        Determine our reachability by querying AutoNAT servers.

        Queries each server (unreachable servers are recorded as
        failures), refreshes the status via :meth:`update_status`, and
        returns it.

        Parameters
        ----------
        servers : list[ID]
            Server peers to request dial-backs from.

        Returns
        -------
        int
            The updated AutoNAT status.

        """
        for server_id in servers:
            try:
                await self.query_server(server_id)
            except Exception as e:
                logger.debug("AutoNAT query to %s failed: %s", server_id, e)
                self.dial_results[server_id] = False
        self.update_status()
        return self.status

    async def periodic_check(
        self, servers: list[ID], interval_seconds: float = 300.0
    ) -> None:
        """
        Periodically re-check reachability until cancelled.

        Parameters
        ----------
        servers : list[ID]
            Server peers to request dial-backs from.
        interval_seconds : float
            Seconds between checks.

        """
        while True:
            await self.check_reachability(servers)
            await trio.sleep(interval_seconds)

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
