"""
Resource management for Circuit Relay v2.

This module handles managing resources for relay operations,
including reservations and connection limits.
"""

from dataclasses import (
    dataclass,
)
import hashlib
import os
import time

from libp2p.peer.id import (
    ID,
)

# Import the protobuf definitions
from .pb.circuit_pb2 import Reservation as PbReservation


@dataclass
class RelayLimits:
    """Configuration for relay resource limits."""

    duration: int  # Maximum duration of a relay connection in seconds
    data: int  # Maximum data transfer allowed in bytes
    max_circuit_conns: int  # Maximum number of concurrent circuit connections
    max_reservations: int  # Maximum number of active reservations


class Reservation:
    """Represents a relay reservation."""

    def __init__(self, peer_id: ID, limits: RelayLimits):
        """
        Initialize a new reservation.

        Parameters
        ----------
        peer_id : ID
            The peer ID this reservation is for
        limits : RelayLimits
            The resource limits for this reservation

        """
        self.peer_id = peer_id
        self.limits = limits
        self.created_at = time.time()
        self.expires_at = self.created_at + limits.duration
        self.data_used = 0
        self.active_connections = 0
        self.voucher = self._generate_voucher()

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
        random_bytes = os.urandom(16)  # 128 bits of randomness
        timestamp = str(int(self.created_at * 1000000)).encode()
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

    def can_accept_connection(self) -> bool:
        """Check if a new connection can be accepted."""
        return (
            not self.is_expired()
            and self.active_connections < self.limits.max_circuit_conns
            and self.data_used < self.limits.data
        )

    def to_proto(self) -> PbReservation:
        """Convert the reservation to its protobuf representation."""
        # TODO: For production use, implement proper signature generation
        # The signature should be created by signing the voucher with the
        # peer's private key. The current implementation with an empty signature
        # is intended for development and testing only.
        return PbReservation(
            expire=int(self.expires_at),
            voucher=self.voucher,
            signature=b"",
        )


class RelayResourceManager:
    """
    Manages resources and reservations for relay operations.

    This class handles:
    - Tracking active reservations
    - Enforcing resource limits
    - Managing connection quotas
    """

    def __init__(self, limits: RelayLimits):
        """
        Initialize the resource manager.

        Parameters
        ----------
        limits : RelayLimits
            The resource limits to enforce

        """
        self.limits = limits
        self._reservations: dict[ID, Reservation] = {}

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
        reservation = Reservation(peer_id, self.limits)
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
        # TODO: Implement voucher and signature verification
        reservation = self._reservations.get(peer_id)
        return (
            reservation is not None
            and not reservation.is_expired()
            and reservation.expires_at == proto_res.expire
        )

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
        reservation = self._reservations.get(peer_id)
        return reservation is not None and reservation.can_accept_connection()

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
