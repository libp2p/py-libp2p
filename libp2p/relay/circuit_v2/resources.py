"""
Resource management for Circuit Relay v2.

This module handles managing resources for relay operations,
including reservations and connection limits.
"""

from dataclasses import (
    dataclass,
)
from enum import Enum, auto
import logging
import time

from libp2p.abc import (
    IHost,
)
from libp2p.peer.envelope import (
    Envelope,
    make_unsigned,
    unmarshal_envelope,
)
from libp2p.peer.id import (
    ID,
)

# Import the protobuf definitions
from .pb.circuit_pb2 import (
    Reservation as PbReservation,
    Voucher as PbVoucher,
)

logger = logging.getLogger(__name__)

# Spec: Reservation Vouchers — Signed Envelope domain and multicodec code.
# Payload type uses raw bytes (NOT varint), matching go-libp2p wire format.
RELAY_RSVP_DOMAIN = "libp2p-relay-rsvp"
VOUCHER_PAYLOAD_TYPE = bytes([0x03, 0x02])


# Reservation status enum


# Reservation status enum
class ReservationStatus(Enum):
    """Lifecycle status of a relay reservation."""

    ACTIVE = auto()
    EXPIRED = auto()
    REJECTED = auto()


@dataclass
class RelayLimits:
    """Configuration for relay resource limits."""

    duration: int  # Maximum duration of a relay connection in seconds
    data: int  # Maximum data transfer allowed in bytes
    max_circuit_conns: int  # Maximum number of concurrent circuit connections
    max_reservations: int  # Maximum number of active reservations
    reservation_ttl: int = 3600  # Reservation validity in seconds (spec:
    # independent of the per-connection duration cap)


@dataclass
class ReservationVoucher:
    """
    Represents a voucher for a relay reservation.

    This is compatible with the Go implementation's ReservationVoucher.
    """

    # The relay peer ID
    relay: ID
    # The client peer ID
    peer: ID
    # Expiration time as Unix timestamp
    expiration: int
    # Optional list of addresses the client can use
    addrs: list[bytes] | None = None


class Reservation:
    """Represents a relay reservation."""

    def __init__(self, peer_id: ID, limits: RelayLimits, host: IHost | None = None):
        """
        Initialize a new reservation.

        Parameters
        ----------
        peer_id : ID
            The peer ID this reservation is for
        limits : RelayLimits
            The resource limits for this reservation
        host : IHost | None
            The host instance for accessing cryptographic keys

        """
        self.peer_id = peer_id
        self.limits = limits
        self.host = host
        self.created_at = time.time()
        self.expires_at = int(self.created_at + limits.reservation_ttl)
        self.data_used = 0
        self.active_connections = 0
        self.voucher = self._sign_voucher()
        self.voucher_obj: ReservationVoucher | None = None
        self.addrs: list[bytes] = []  # List of addresses for this reservation

    def _sign_voucher(self) -> bytes:
        """
        Sign a spec reservation voucher for this reservation.

        Returns the marshalled Signed Envelope (domain
        ``libp2p-relay-rsvp``, multicodec ``0x0302``) over
        ``Voucher{relay, peer, expiration}``, or ``b""`` when the host
        key is unavailable (vouchers are advisory per spec).
        """
        try:
            if self.host is None:
                return b""
            relay_id = self.host.get_id()
            payload = PbVoucher(
                relay=relay_id.to_bytes(),
                peer=self.peer_id.to_bytes(),
                expiration=int(self.expires_at),
            ).SerializeToString()
            private_key = self.host.get_private_key()
            unsigned = make_unsigned(RELAY_RSVP_DOMAIN, VOUCHER_PAYLOAD_TYPE, payload)
            signature = private_key.sign(unsigned)
            env = Envelope(
                public_key=private_key.get_public_key(),
                payload_type=VOUCHER_PAYLOAD_TYPE,
                raw_payload=payload,
                signature=signature,
            )
            return env.marshal_envelope()
        except Exception as e:
            logger.debug("Failed to sign reservation voucher: %s", e)
            return b""

    def is_expired(self) -> bool:
        """Check if the reservation has expired."""
        return time.time() > self.expires_at

    # Expose a friendly status enum

    @property
    def status(self) -> ReservationStatus:
        """Return the current status as a ``ReservationStatus`` enum."""
        return (
            ReservationStatus.EXPIRED if self.is_expired() else ReservationStatus.ACTIVE
        )

    def can_accept_connection(self) -> bool:
        """Check if a new connection can be accepted."""
        return (
            not self.is_expired()
            and self.active_connections < self.limits.max_circuit_conns
        )

    def track_data_transfer(self, bytes_transferred: int) -> bool:
        """
        Track data transferred for this reservation.

        Parameters
        ----------
        bytes_transferred : int
            Number of bytes transferred

        Returns
        -------
        bool
            True if the data limit has not been exceeded, False otherwise

        """
        # Check if this transfer would exceed the limit
        if self.data_used + bytes_transferred > self.limits.data:
            logger.debug(
                "Data transfer would exceed limit: %d + %d > %d",
                self.data_used,
                bytes_transferred,
                self.limits.data,
            )
            return False

        # Track the data transfer
        self.data_used += bytes_transferred
        return True

    def to_proto(self) -> PbReservation:
        """
        Convert the reservation to its protobuf representation.

        Returns
        -------
        PbReservation
            The protobuf representation of this reservation

        """
        return PbReservation(
            expire=int(self.expires_at),
            addrs=self.addrs,
            voucher=self.voucher,
        )


class RelayResourceManager:
    """
    Manages resources and reservations for relay operations.

    This class handles:
    - Tracking active reservations
    - Enforcing resource limits
    - Managing connection quotas
    """

    def __init__(self, limits: RelayLimits, host: IHost | None = None):
        """
        Initialize the resource manager.

        Parameters
        ----------
        limits : RelayLimits
            The resource limits to enforce
        host : IHost | None
            The host instance for accessing cryptographic keys and peer store

        """
        self.limits = limits
        self.host = host
        self._reservations: dict[ID, Reservation] = {}
        self.peer_store = host.get_peerstore() if host else None

    def can_accept_reservation(self, peer_id: ID) -> bool:
        """
        Check if a new reservation can be accepted for the given peer.

        Parameters
        ----------
        peer_id : ID
            The peer ID requesting the reservation

        Returns
        -------
        bool
            True if the reservation can be accepted

        """
        # Clean expired reservations
        self._clean_expired()

        # Check if peer already has a valid reservation
        existing = self._reservations.get(peer_id)
        if existing and not existing.is_expired():
            return True

        # Check if we're at the reservation limit
        return len(self._reservations) < self.limits.max_reservations

    def create_reservation(self, peer_id: ID) -> Reservation:
        """
        Create a new reservation for the given peer.

        Parameters
        ----------
        peer_id : ID
            The peer ID to create the reservation for

        Returns
        -------
        Reservation
            The newly created reservation

        """
        reservation = Reservation(peer_id, self.limits, self.host)
        self._reservations[peer_id] = reservation
        return reservation

    def verify_reservation(self, peer_id: ID, proto_res: PbReservation) -> bool:
        """
        Verify a reservation from a protobuf message.

        Parameters
        ----------
        peer_id : ID
            The peer ID the reservation is for
        proto_res : PbReservation
            The protobuf reservation message

        Returns
        -------
        bool
            True if the reservation is valid

        """
        # First check if we have a reservation for this peer
        reservation = self._reservations.get(peer_id)
        if reservation is None:
            logger.debug("No reservation found for peer %s", peer_id)
            return False

        # Check if the reservation has expired
        if reservation.is_expired():
            logger.debug("Reservation for peer %s has expired", peer_id)
            return False

        # Check if the expiration time matches (accounting for integer
        # truncation in protobuf)
        if abs(int(reservation.expires_at) - proto_res.expire) > 1:
            logger.debug(
                "Expiration time mismatch: expected %s, got %s",
                int(reservation.expires_at),
                proto_res.expire,
            )
            return False

        # Verify a presented voucher: it must be a valid Signed Envelope
        # from us (domain libp2p-relay-rsvp) binding this peer and a
        # matching expiration. Relays following the spec (e.g.
        # rust-libp2p) omit vouchers; requiring them would break interop,
        # so absence is accepted.
        if proto_res.voucher:
            if not self._verify_voucher(peer_id, bytes(proto_res.voucher)):
                logger.debug("Voucher mismatch for peer %s", peer_id)
                return False

        return True

    def _verify_voucher(self, peer_id: ID, voucher: bytes) -> bool:
        """Validate a presented reservation voucher envelope."""
        try:
            env = unmarshal_envelope(voucher)
            env.validate(RELAY_RSVP_DOMAIN)
            if bytes(env.payload_type) != VOUCHER_PAYLOAD_TYPE:
                return False
            payload = PbVoucher()
            payload.ParseFromString(bytes(env.raw_payload))
            if ID(payload.peer) != peer_id:
                return False
            if self.host is not None and ID(payload.relay) != self.host.get_id():
                return False
            expected = int(self._reservations[peer_id].expires_at)
            if abs(int(payload.expiration) - expected) > 1:
                return False
            return True
        except Exception as e:
            logger.debug("Voucher verification failed for %s: %s", peer_id, e)
            return False

    def can_accept_connection(self, peer_id: ID) -> bool:
        """
        Check if a new connection can be accepted for the given peer.

        Parameters
        ----------
        peer_id : ID
            The peer ID requesting the connection

        Returns
        -------
        bool
            True if the connection can be accepted

        """
        reservation = self.get_reservation(peer_id)
        return reservation is not None and reservation.can_accept_connection()

    def track_data_transfer(self, peer_id: ID, bytes_transferred: int) -> bool:
        """
        Track data transferred for a peer's reservation.

        Parameters
        ----------
        peer_id : ID
            The peer ID
        bytes_transferred : int
            Number of bytes transferred

        Returns
        -------
        bool
            True if the data limit has not been exceeded, False otherwise

        """
        reservation = self._reservations.get(peer_id)
        if reservation is None:
            logger.debug("No reservation found for peer %s", peer_id)
            return False

        # Delegate to the reservation's track_data_transfer method
        return reservation.track_data_transfer(bytes_transferred)

    def _clean_expired(self) -> None:
        """Remove expired reservations."""
        now = time.time()
        expired = [
            peer_id
            for peer_id, res in self._reservations.items()
            if now > res.expires_at
        ]
        for peer_id in expired:
            del self._reservations[peer_id]

    def reserve(self, peer_id: ID) -> int:
        """
        Create or update a reservation for a peer and return the TTL.

        Parameters
        ----------
        peer_id : ID
            The peer ID to reserve for

        Returns
        -------
        int
            The TTL of the reservation in seconds

        """
        # Check for existing reservation
        existing = self._reservations.get(peer_id)
        if existing and not existing.is_expired():
            # Return remaining time for existing reservation
            remaining = max(0, int(existing.expires_at - time.time()))
            return remaining

        # Create new reservation
        self.create_reservation(peer_id)
        return self.limits.reservation_ttl

    def has_reservation(self, peer_id: ID) -> bool:
        """
        Check if a reservation already exists for a peer

        Parameters
        ----------
        peer_id : ID
            The peer ID to check for

        Returns
        -------
        bool
            True if reservation exists, False otherwise

        """
        existing = self._reservations.get(peer_id)
        if existing and not existing.is_expired():
            return self._is_peer_connected(peer_id)
        return False

    def refresh_reservation(self, peer_id: ID) -> int:
        existing = self._reservations.get(peer_id)
        if existing and not existing.is_expired():
            # Extend validity in place: replacing the object would wipe
            # data_used/active_connections and let peers reset quotas.
            existing.expires_at = int(time.time() + self.limits.reservation_ttl)
            return self.limits.reservation_ttl

        return 0

    def _is_peer_connected(self, peer_id: ID) -> bool:
        """
        Return True if the peer currently has a live connection.

        Spec: a reservation is only valid while the peer holds an active
        connection to the relay. Fail-open when the host is unavailable
        (e.g. unit tests) to preserve prior behavior there.
        """
        if self.host is None:
            return True
        try:
            network = self.host.get_network()
            conns = (getattr(network, "connections", {}) or {}).get(peer_id)
            return bool(conns)
        except Exception:
            return True

    def get_reservation(self, peer_id: ID) -> Reservation | None:
        """
        Get an active reservation for a peer.

        Parameters
        ----------
        peer_id : ID
            The peer ID to get the reservation for

        Returns
        -------
        Reservation | None
            The reservation if it exists and is active, None otherwise

        """
        reservation = self._reservations.get(peer_id)
        if reservation and not reservation.is_expired():
            if self._is_peer_connected(peer_id):
                return reservation
        return None
