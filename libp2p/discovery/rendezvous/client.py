"""
Rendezvous client implementation.
"""

import logging
import random

import trio
import varint

from libp2p.abc import IHost
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import PeerInfo

from .config import (
    DEFAULT_DISCOVER_LIMIT,
    DEFAULT_TIMEOUT,
    DEFAULT_TTL,
    MAX_DISCOVER_LIMIT,
    MAX_NAMESPACE_LENGTH,
    MAX_TTL,
    MIN_TTL,
    RENDEZVOUS_PROTOCOL,
)
from .errors import RendezvousError, status_to_exception
from .messages import (
    create_discover_message,
    create_register_message,
    create_unregister_message,
    parse_peer_info,
)
from .pb.rendezvous_pb2 import Message

logger = logging.getLogger(__name__)


class RendezvousClient:
    """
    Rendezvous client for registering with and discovering peers through
    a rendezvous point.
    """

    def __init__(
        self, host: IHost, rendezvous_peer: PeerID, enable_refresh: bool = False
    ):
        """
        Initialize rendezvous client.

        Args:
            host: The libp2p host
            rendezvous_peer: Peer ID of the rendezvous server
            enable_refresh: Whether to enable automatic refresh

        """
        self.host = host
        self.rendezvous_peer = rendezvous_peer
        self.enable_refresh = enable_refresh
        self._refresh_cancel_scopes: dict[str, trio.CancelScope] = {}
        self._nursery: trio.Nursery | None = None

    def set_nursery(self, nursery: trio.Nursery) -> None:
        """Set the nursery for background tasks (called by RendezvousDiscovery)."""
        self._nursery = nursery

    async def register(self, namespace: str, ttl: int = DEFAULT_TTL) -> float:
        """
        Register this peer under a namespace.

        Args:
            namespace: Namespace to register under
            ttl: Time-to-live in seconds (default 2 hours)

        Returns:
            Actual TTL granted by the server

        Raises:
            RendezvousError: If registration fails

        """
        if ttl < MIN_TTL:
            raise ValueError(f"TTL too short, minimum is {MIN_TTL} seconds")

        if ttl > MAX_TTL:
            raise ValueError(f"TTL too long, maximum is {MAX_TTL} seconds")

        if len(namespace) > MAX_NAMESPACE_LENGTH:
            raise ValueError(f"Namespace too long, maximum is {MAX_NAMESPACE_LENGTH}")

        # Get our addresses
        addrs = self.host.get_addrs()
        if not addrs:
            raise ValueError("No addresses available to advertise")

        # Create and send register message
        msg = create_register_message(namespace, self.host.get_id(), addrs, ttl)

        response = await self._send_message(msg)
        if response is None:
            raise RendezvousError(
                Message.ResponseStatus.E_INTERNAL_ERROR,
                "No response received from rendezvous server",
            )

        if response.type != Message.REGISTER_RESPONSE:
            raise RendezvousError(
                Message.ResponseStatus.E_INTERNAL_ERROR,
                f"Unexpected response type: {response.type}",
            )

        resp = response.registerResponse
        if resp.status != Message.ResponseStatus.OK:
            error = status_to_exception(resp.status, resp.statusText)
            if error is not None:
                raise error

        actual_ttl = resp.ttl

        # Start auto-refresh only if enabled
        if self.enable_refresh:
            await self._start_refresh_task(namespace, actual_ttl)

        logger.info(f"Registered in namespace '{namespace}' with TTL {actual_ttl}s")
        return actual_ttl

    async def unregister(self, namespace: str) -> None:
        """
        Unregister this peer from a namespace.

        Args:
            namespace: Namespace to unregister from

        """
        # Stop refresh task
        await self._stop_refresh_task(namespace)

        # Send unregister message
        msg = create_unregister_message(namespace, self.host.get_id())
        await self._send_message(msg, expect_response=False)

        logger.info(f"Unregistered from namespace '{namespace}'")

    async def discover(
        self, namespace: str, limit: int = DEFAULT_DISCOVER_LIMIT, cookie: bytes = b""
    ) -> tuple[list[PeerInfo], bytes]:
        """
        Discover peers in a namespace.

        Args:
            namespace: Namespace to search
            limit: Maximum number of peers to return
            cookie: Pagination cookie from previous request

        Returns:
            Tuple of (peer list, new cookie for pagination)

        Raises:
            RendezvousError: If discovery fails

        """
        if limit > MAX_DISCOVER_LIMIT:
            limit = MAX_DISCOVER_LIMIT

        msg = create_discover_message(namespace, limit, cookie)
        response = await self._send_message(msg)
        if response is None:
            raise RendezvousError(
                Message.ResponseStatus.E_INTERNAL_ERROR,
                "No response received from rendezvous server",
            )

        if response.type != Message.DISCOVER_RESPONSE:
            raise RendezvousError(
                Message.ResponseStatus.E_INTERNAL_ERROR,
                f"Unexpected response type: {response.type}",
            )

        resp = response.discoverResponse
        if resp.status != Message.ResponseStatus.OK:
            error = status_to_exception(resp.status, resp.statusText)
            if error is not None:
                raise error

        # Parse registrations into PeerInfo objects
        peers = []
        for reg in resp.registrations:
            peer_id, addrs = parse_peer_info(reg.peer)
            peer_info = PeerInfo(peer_id, addrs)
            peers.append(peer_info)

        logger.debug(f"Discovered {len(peers)} peers in namespace '{namespace}'")
        return peers, resp.cookie

    async def _send_message(
        self, message: Message, expect_response: bool = True
    ) -> Message | None:
        """
        Send a message to the rendezvous server.

        Args:
            message: Protobuf message to send
            expect_response: Whether to wait for a response

        Returns:
            Response message if expect_response is True

        """
        stream = None
        try:
            # Open stream to rendezvous server with timeout
            with trio.move_on_after(DEFAULT_TIMEOUT) as cancel_scope:
                stream = await self.host.new_stream(
                    self.rendezvous_peer, [RENDEZVOUS_PROTOCOL]
                )

            if cancel_scope.cancelled_caught:
                raise RendezvousError(
                    Message.ResponseStatus.E_INTERNAL_ERROR,
                    f"Connection timeout after {DEFAULT_TIMEOUT}s",
                )

            # Serialize and send message with varint length prefix
            proto_bytes = message.SerializeToString()
            await stream.write(varint.encode(len(proto_bytes)))
            await stream.write(proto_bytes)

            if not expect_response:
                return None

            # Read response with timeout
            with trio.move_on_after(DEFAULT_TIMEOUT) as cancel_scope:
                # Read response length
                length_bytes = b""
                while True:
                    b = await stream.read(1)
                    if not b:
                        raise RendezvousError(
                            Message.ResponseStatus.E_INTERNAL_ERROR,
                            "Connection closed while reading response length",
                        )
                    length_bytes += b
                    if b[0] & 0x80 == 0:
                        break

                response_length = varint.decode_bytes(length_bytes)

                # Read response data
                response_bytes = b""
                remaining = response_length
                while remaining > 0:
                    chunk = await stream.read(remaining)
                    if not chunk:
                        raise RendezvousError(
                            Message.ResponseStatus.E_INTERNAL_ERROR,
                            "Connection closed while reading response data",
                        )
                    response_bytes += chunk
                    remaining -= len(chunk)

            if cancel_scope.cancelled_caught:
                raise RendezvousError(
                    Message.ResponseStatus.E_INTERNAL_ERROR,
                    f"Response timeout after {DEFAULT_TIMEOUT}s",
                )

            # Parse response
            response = Message()
            response.ParseFromString(response_bytes)
            return response

        finally:
            if stream:
                await stream.close()

    async def _start_refresh_task(self, namespace: str, ttl: int) -> None:
        """Start automatic registration refresh for a namespace using trio."""
        if not self._nursery:
            logger.warning("No nursery set for refresh tasks - refresh disabled")
            return

        await self._stop_refresh_task(namespace)

        cancel_scope = trio.CancelScope()

        async def refresh_task() -> None:
            with cancel_scope:
                await self._refresh_loop(namespace, ttl)

        # Store the cancel scope for later cancellation
        self._refresh_cancel_scopes[namespace] = cancel_scope

        # Start the refresh task using nursery.start_soon.
        self._nursery.start_soon(refresh_task)

    async def _stop_refresh_task(self, namespace: str) -> None:
        """Stop automatic registration refresh for a namespace using trio."""
        if namespace in self._refresh_cancel_scopes:
            cancel_scope = self._refresh_cancel_scopes.pop(namespace)
            cancel_scope.cancel()

    async def _refresh_loop(self, namespace: str, ttl: int) -> None:
        """Automatic registration refresh loop using trio."""
        error_count = 0

        while True:
            try:
                if error_count > 0:
                    # Exponential backoff on errors (cap at ~4 hours)
                    if error_count > 7:
                        error_count = 7
                    backoff = 2 << error_count
                    jitter_ms = random.randint(0, backoff * 60000)
                    jitter_seconds = jitter_ms / 1000.0
                    refresh_delay = 5 * 60 + jitter_seconds
                else:
                    refresh_delay = (7 * ttl) // 8

                logger.debug(
                    f"Waiting {refresh_delay}s before refreshing registration "
                    f"for namespace '{namespace}' (error_count={error_count})"
                )

                await trio.sleep(refresh_delay)

                # Refresh registration
                addrs = self.host.get_addrs()
                if not addrs:
                    logger.warning("No addresses available for refresh")
                    error_count += 1
                    continue

                msg = create_register_message(namespace, self.host.get_id(), addrs, ttl)

                response = await self._send_message(msg)
                if response is None:
                    logger.error("No response received during refresh")
                    error_count += 1
                    continue

                if (
                    response.type != Message.REGISTER_RESPONSE
                    or response.registerResponse.status != Message.ResponseStatus.OK
                ):
                    raise RendezvousError(
                        response.registerResponse.status,
                        response.registerResponse.statusText,
                    )

                logger.debug(f"Refreshed registration for namespace '{namespace}'")
                error_count = 0

            except trio.Cancelled:
                logger.debug(f"Refresh task cancelled for namespace '{namespace}'")
                break
            except Exception as e:
                logger.error(f"Error refreshing registration for '{namespace}': {e}")
                error_count += 1

    async def close(self) -> None:
        """Close the client and stop all refresh tasks."""
        # Cancel all refresh tasks
        for namespace in list(self._refresh_cancel_scopes.keys()):
            await self._stop_refresh_task(namespace)
