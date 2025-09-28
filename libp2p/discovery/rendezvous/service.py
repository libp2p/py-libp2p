"""
Rendezvous service implementation for hosting a rendezvous point.
"""

import logging
import time

import varint

from libp2p.abc import IHost, INetStream
from libp2p.peer.id import ID as PeerID

from .config import (
    MAX_DISCOVER_LIMIT,
    MAX_NAMESPACE_LENGTH,
    MAX_PEER_ADDRESS_LENGTH,
    MAX_REGISTRATIONS,
    MAX_TTL,
    RENDEZVOUS_PROTOCOL,
)
from .messages import (
    create_discover_response_message,
    create_register_response_message,
    parse_peer_info,
)
from .pb.rendezvous_pb2 import Message

logger = logging.getLogger(__name__)


class RegistrationRecord:
    """Represents a peer registration record."""

    def __init__(self, peer_id: PeerID, addrs: list[bytes], namespace: str, ttl: int):
        self.peer_id = peer_id
        self.addrs = addrs
        self.namespace = namespace
        self.ttl = ttl
        self.registered_at = time.time()
        self.expires_at = self.registered_at + ttl

    def is_expired(self) -> bool:
        """Check if this registration has expired."""
        return time.time() > self.expires_at

    def to_protobuf_register(self) -> Message.Register:
        """Convert to protobuf Register message."""
        register = Message.Register()
        register.ns = self.namespace
        register.peer.id = self.peer_id.to_bytes()
        register.peer.addrs.extend(self.addrs)
        register.ttl = max(0, int(self.expires_at - time.time()))
        return register


class RendezvousService:
    """
    Rendezvous service for hosting a rendezvous point.

    This service allows peers to register under namespaces and discover
    other peers that have registered under the same namespaces.
    """

    def __init__(self, host: IHost):
        """
        Initialize rendezvous service.

        Args:
            host: The libp2p host

        """
        self.host = host
        # Store registrations by namespace
        self.registrations: dict[str, dict[PeerID, RegistrationRecord]] = {}

        # Set up stream handler
        host.set_stream_handler(RENDEZVOUS_PROTOCOL, self._handle_stream)

        logger.info("Rendezvous service started")

    async def _handle_stream(self, stream: INetStream) -> None:
        """Handle incoming rendezvous protocol streams."""
        peer_id = stream.muxed_conn.peer_id
        logger.debug(f"New rendezvous stream from {peer_id}")

        try:
            while True:
                # Read message length
                length_bytes = b""
                while True:
                    b = await stream.read(1)
                    if not b:
                        return  # Stream closed
                    length_bytes += b
                    if b[0] & 0x80 == 0:
                        break

                message_length = varint.decode_bytes(length_bytes)

                # Read message data
                message_bytes = b""
                remaining = message_length
                while remaining > 0:
                    chunk = await stream.read(remaining)
                    if not chunk:
                        return  # Stream closed
                    message_bytes += chunk
                    remaining -= len(chunk)

                # Parse message
                request = Message()
                request.ParseFromString(message_bytes)

                # Handle message based on type
                response = None
                if request.type == Message.REGISTER:
                    response = self._handle_register(peer_id, request.register)
                elif request.type == Message.UNREGISTER:
                    self._handle_unregister(peer_id, request.unregister)
                    # No response for unregister
                elif request.type == Message.DISCOVER:
                    response = self._handle_discover(peer_id, request.discover)
                else:
                    logger.warning(f"Unknown message type: {request.type}")
                    return

                # Send response if needed
                if response:
                    response_bytes = response.SerializeToString()
                    await stream.write(varint.encode(len(response_bytes)))
                    await stream.write(response_bytes)

        except Exception as e:
            logger.error(f"Error handling stream from {peer_id}: {e}")
        finally:
            await stream.close()

    def _handle_register(
        self, peer_id: PeerID, register_msg: Message.Register
    ) -> Message:
        """Handle REGISTER message."""
        target_peer_id = PeerID(register_msg.peer.id)
        namespace = register_msg.ns
        ttl = register_msg.ttl

        # Only allow peers to register themselves
        if peer_id != target_peer_id:
            logger.warning(
                f"Peer {peer_id} tried to register {target_peer_id} "
                f"in namespace '{namespace}'"
            )
            return create_register_response_message(
                Message.ResponseStatus.E_NOT_AUTHORIZED, "Peer can only register itself"
            )

        # Validate namespace
        if not namespace or len(namespace) > MAX_NAMESPACE_LENGTH:
            return create_register_response_message(
                Message.ResponseStatus.E_INVALID_NAMESPACE, "Invalid namespace"
            )

        # Validate TTL
        if ttl <= 0 or ttl > MAX_TTL:
            return create_register_response_message(
                Message.ResponseStatus.E_INVALID_TTL,
                f"TTL must be between 1 and {MAX_TTL} seconds",
            )

        # Validate peer info
        if not register_msg.peer.id:
            return create_register_response_message(
                Message.ResponseStatus.E_INVALID_PEER_INFO, "Missing peer ID"
            )

        # Check address lengths
        for addr in register_msg.peer.addrs:
            if len(addr) > MAX_PEER_ADDRESS_LENGTH:
                return create_register_response_message(
                    Message.ResponseStatus.E_INVALID_PEER_INFO, "Address too long"
                )

        # Ensure namespace exists in registrations
        if namespace not in self.registrations:
            self.registrations[namespace] = {}

        # Check registration limit for namespace
        if len(self.registrations[namespace]) >= MAX_REGISTRATIONS:
            # Remove expired registrations first
            self._cleanup_expired_registrations(namespace)

            if len(self.registrations[namespace]) >= MAX_REGISTRATIONS:
                return create_register_response_message(
                    Message.ResponseStatus.E_UNAVAILABLE, "Registration limit reached"
                )

        # Create registration record
        try:
            reg_peer_id, _ = parse_peer_info(register_msg.peer)
        except Exception:
            return create_register_response_message(
                Message.ResponseStatus.E_INVALID_PEER_INFO, "Invalid peer info"
            )

        record = RegistrationRecord(
            reg_peer_id, list(register_msg.peer.addrs), namespace, ttl
        )

        # Store registration
        self.registrations[namespace][reg_peer_id] = record

        logger.info(
            f"Registered peer {reg_peer_id} in namespace '{namespace}' with TTL {ttl}s"
        )

        return create_register_response_message(Message.ResponseStatus.OK, "OK", ttl)

    def _handle_unregister(
        self, peer_id: PeerID, unregister_msg: Message.Unregister
    ) -> None:
        """Handle UNREGISTER message."""
        namespace = unregister_msg.ns
        target_peer_id = PeerID(unregister_msg.id)

        # Only allow peers to unregister themselves
        if peer_id != target_peer_id:
            logger.warning(
                f"Peer {peer_id} tried to unregister {target_peer_id} "
                f"from namespace '{namespace}'"
            )
            return

        # Remove registration
        if namespace in self.registrations:
            self.registrations[namespace].pop(target_peer_id, None)
            logger.info(
                f"Unregistered peer {target_peer_id} from namespace '{namespace}'"
            )

    def _handle_discover(
        self, peer_id: PeerID, discover_msg: Message.Discover
    ) -> Message:
        """Handle DISCOVER message."""
        namespace = discover_msg.ns
        limit = discover_msg.limit
        cookie = discover_msg.cookie

        # Validate namespace
        if not namespace or len(namespace) > MAX_NAMESPACE_LENGTH:
            return create_discover_response_message(
                [], b"", Message.ResponseStatus.E_INVALID_NAMESPACE, "Invalid namespace"
            )

        # Validate limit
        if limit <= 0 or limit > MAX_DISCOVER_LIMIT:
            limit = MAX_DISCOVER_LIMIT

        # Clean up expired registrations
        if namespace in self.registrations:
            self._cleanup_expired_registrations(namespace)
        else:
            self.registrations[namespace] = {}

        # Get registrations for namespace
        registrations = list(self.registrations[namespace].values())

        # Simple pagination using cookie as offset
        offset = 0
        if cookie:
            try:
                offset = int.from_bytes(cookie, "big")
            except (ValueError, OverflowError):
                return create_discover_response_message(
                    [], b"", Message.ResponseStatus.E_INVALID_COOKIE, "Invalid cookie"
                )

        # Get slice of registrations
        end_offset = min(offset + limit, len(registrations))
        slice_registrations = registrations[offset:end_offset]

        # Create new cookie for next page
        new_cookie = b""
        if end_offset < len(registrations):
            new_cookie = end_offset.to_bytes(4, "big")

        # Convert to protobuf Register messages
        pb_registrations = [reg.to_protobuf_register() for reg in slice_registrations]

        logger.debug(
            f"Discovered {len(pb_registrations)} peers in namespace '{namespace}' "
            f"for peer {peer_id}"
        )

        return create_discover_response_message(
            pb_registrations, new_cookie, Message.ResponseStatus.OK, "OK"
        )

    def _cleanup_expired_registrations(self, namespace: str) -> None:
        """Remove expired registrations from a namespace."""
        if namespace not in self.registrations:
            return

        expired_peers = [
            peer_id
            for peer_id, record in self.registrations[namespace].items()
            if record.is_expired()
        ]

        for peer_id in expired_peers:
            del self.registrations[namespace][peer_id]

        if expired_peers:
            logger.debug(
                f"Cleaned up {len(expired_peers)} expired registrations"
                f"from '{namespace}'"
            )

    def get_namespace_stats(self) -> dict[str, int]:
        """Get statistics about registrations per namespace."""
        stats = {}
        for namespace, registrations in self.registrations.items():
            # Clean up expired first
            self._cleanup_expired_registrations(namespace)
            stats[namespace] = len(registrations)
        return stats

    def cleanup_all_expired(self) -> None:
        """Clean up expired registrations from all namespaces."""
        for namespace in list(self.registrations.keys()):
            self._cleanup_expired_registrations(namespace)
            # Remove empty namespaces
            if not self.registrations[namespace]:
                del self.registrations[namespace]
