"""
Allowlist implementation for the resource manager.

Only the specific peers and multiaddresses in the
allowlist can bypass the resource limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from multiaddr import Multiaddr

from libp2p.peer.id import ID


@dataclass
class AllowlistConfig:
    """Configuration for the allowlist."""

    peers: set[ID] = field(default_factory=set)
    multiaddrs: set[str] = field(default_factory=set)
    peer_multiaddrs: set[tuple[ID, str]] = field(default_factory=set)


class Allowlist:
    """
    Allowlist for bypassing resource limits.

    The allowlist can contain:
    - Specific peer IDs
    - Specific multiaddresses
    - Specific peer-multiaddr combinations
    """

    def __init__(self, config: AllowlistConfig | None = None):
        if config is None:
            config = AllowlistConfig()

        self.peers = set(config.peers)
        self.multiaddrs = set(config.multiaddrs)
        self.peer_multiaddrs = set(config.peer_multiaddrs)

    def add_peer(self, peer_id: ID) -> None:
        """Add a peer to the allowlist."""
        self.peers.add(peer_id)

    def remove_peer(self, peer_id: ID) -> None:
        """Remove a peer from the allowlist."""
        self.peers.discard(peer_id)

    def add_multiaddr(self, multiaddr: Multiaddr | str) -> None:
        """Add a multiaddress to the allowlist."""
        if isinstance(multiaddr, Multiaddr):
            multiaddr = str(multiaddr)
        self.multiaddrs.add(multiaddr)

    def remove_multiaddr(self, multiaddr: Multiaddr | str) -> None:
        """Remove a multiaddress from the allowlist."""
        if isinstance(multiaddr, Multiaddr):
            multiaddr = str(multiaddr)
        self.multiaddrs.discard(multiaddr)

    def add_peer_multiaddr(self, peer_id: ID, multiaddr: Multiaddr | str) -> None:
        """Add a peer-multiaddr combination to the allowlist."""
        if isinstance(multiaddr, Multiaddr):
            multiaddr = str(multiaddr)
        self.peer_multiaddrs.add((peer_id, multiaddr))

    def remove_peer_multiaddr(self, peer_id: ID, multiaddr: Multiaddr | str) -> None:
        """Remove a peer-multiaddr combination from the allowlist."""
        if isinstance(multiaddr, Multiaddr):
            multiaddr = str(multiaddr)
        self.peer_multiaddrs.discard((peer_id, multiaddr))

    def allowed_peer(self, peer_id: ID) -> bool:
        """Check if a peer is allowlisted."""
        return peer_id in self.peers

    def allowed_multiaddr(self, multiaddr: Multiaddr | str) -> bool:
        """Check if a multiaddress is allowlisted."""
        if isinstance(multiaddr, Multiaddr):
            multiaddr_str = str(multiaddr)
        else:
            multiaddr_str = multiaddr

        # Check exact match
        return multiaddr_str in self.multiaddrs

    def allowed_peer_and_multiaddr(
        self,
        peer_id: ID,
        multiaddr: Multiaddr | str,
    ) -> bool:
        """Check if a peer-multiaddr combination is allowlisted."""
        if isinstance(multiaddr, Multiaddr):
            multiaddr_str = str(multiaddr)
        else:
            multiaddr_str = multiaddr

        # Check specific peer-multiaddr combination
        if (peer_id, multiaddr_str) in self.peer_multiaddrs:
            return True

        # Check if peer is generally allowlisted
        if self.allowed_peer(peer_id):
            return True

        # Check if multiaddr is generally allowlisted
        if self.allowed_multiaddr(multiaddr):
            return True

        return False

    def allowed(self, multiaddr: Multiaddr | str) -> bool:
        """
        Check if a multiaddress is allowlisted (alias for allowed_multiaddr).

        This method name matches the Go implementation.
        """
        return self.allowed_multiaddr(multiaddr)

    def get_allowed_peers(self) -> set[ID]:
        """Get all allowed peers."""
        return self.peers.copy()

    def get_allowed_multiaddrs(self) -> set[str]:
        """Get all allowed multiaddresses."""
        return self.multiaddrs.copy()

    def clear(self) -> None:
        """Clear all allowlist entries."""
        self.peers.clear()
        self.multiaddrs.clear()
        self.peer_multiaddrs.clear()

    def is_empty(self) -> bool:
        """Check if the allowlist is empty."""
        return not self.peers and not self.multiaddrs and not self.peer_multiaddrs

    def __len__(self) -> int:
        """Get the total number of allowlist entries."""
        return len(self.peers) + len(self.multiaddrs) + len(self.peer_multiaddrs)

    def __repr__(self) -> str:
        """String representation of the allowlist."""
        return (
            f"Allowlist("
            f"peers={len(self.peers)}, "
            f"multiaddrs={len(self.multiaddrs)}, "
            f"peer_multiaddrs={len(self.peer_multiaddrs)})"
        )


def new_allowlist() -> Allowlist:
    """Create a new empty allowlist."""
    return Allowlist()


def new_allowlist_with_config(config: AllowlistConfig) -> Allowlist:
    """Create a new allowlist with the given configuration."""
    return Allowlist(config)
