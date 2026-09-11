"""
Resource management for Circuit Relay v2.

This module handles managing resources for relay operations,
including reservations and connection limits.
"""

from dataclasses import (
    dataclass,
)
from enum import Enum, auto
import hashlib
import logging
import os
import time

from libp2p.abc import (
    IHost,
)
from libp2p.peer.id import (
    ID,
)

# Import the protobuf definitions
from .pb.circuit_pb2 import Reservation as PbReservation

logger = logging.getLogger(__name__)

# Prefix for data to be signed, helps prevent signature reuse attacks

RANDOM_BYTES_LENGTH = 16  # 128 bits of randomness
TIMESTAMP_MULTIPLIER = 1000000  # To convert seconds to microseconds


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
        self.expires_at = int(self.created_at + limits.duration)
        self.data_used = 0
        self.active_connections = 0
        self.voucher = self._generate_voucher()
        self.voucher_obj: ReservationVoucher | None = None
        self.addrs: list[bytes] = []  # List of addresses for this reservation

    def _generate_voucher(self) -> bytes:
        """
        Generate a unique cryptographically secure voucher for this reservation.

        Returns
        -------
        bytes
            A secure voucher token

        """
        # Create a random token using a combination of:
        # - Random bytes for unpredictability
        # - Peer ID to bind it to the specific peer
        # - Timestamp for uniqueness
        # - Hash everything for a fixed size output
        random_bytes = os.urandom(RANDOM_BYTES_LENGTH)
        timestamp = str(int(self.created_at * TIMESTAMP_MULTIPLIER)).encode()
        peer_bytes = self.peer_id.to_bytes()

        # Combine all elements and hash them
        h = hashlib.sha256()
        h.update(random_bytes)
        h.update(timestamp)
        h.update(peer_bytes)

        return h.digest()

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

        # Check the voucher only when the peer presents one. Relays
        # following the spec (e.g. rust-libp2p) omit vouchers; requiring
        # them would break interop. A presented voucher must match.
        if proto_res.voucher and proto_res.voucher != reservation.voucher:
            logger.debug(
                "Voucher mismatch for peer %s",
                peer_id,
            )
            return False

        return True

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
        return self.limits.duration

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
            return True
        return False

    def refresh_reservation(self, peer_id: ID) -> int:
        if self.has_reservation(peer_id):
            self.create_reservation(peer_id)
            return self.limits.duration

        return 0

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
            return reservation
        return None
