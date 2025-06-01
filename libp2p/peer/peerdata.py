from collections.abc import (
    Sequence,
)
import time
from typing import (
    Any,
)

from multiaddr import (
    Multiaddr,
)

from libp2p.abc import (
    IPeerData,
)
from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)

"""
Latency EWMA Smoothing governs the deacy of the EWMA (the speed at which
is changes). This must be a normalized (0-1) value.
1 is 100% change, 0 is no change.
"""
LATENCY_EWMA_SMOOTHING = 0.1


class PeerData(IPeerData):
    pubkey: PublicKey | None
    privkey: PrivateKey | None
    metadata: dict[Any, Any]
    protocols: list[str]
    addrs: list[Multiaddr]
    last_identified: int
    ttl: int  # Keep ttl=0 by default for always valid

    def __init__(self) -> None:
        self.pubkey = None
        self.privkey = None
        self.metadata = {}
        self.protocols = []
        self.addrs = []
        self.last_identified = int(time.time())
        self.ttl = 0

    def get_protocols(self) -> list[str]:
        """
        :return: all protocols associated with given peer
        """
        return self.protocols

    def add_protocols(self, protocols: Sequence[str]) -> None:
        """
        :param protocols: protocols to add
        """
        self.protocols.extend(list(protocols))

    def set_protocols(self, protocols: Sequence[str]) -> None:
        """
        :param protocols: protocols to set
        """
        self.protocols = list(protocols)

    def remove_protocols(self, protocols: Sequence[str]) -> None:
        """
        :param protocols: protocols to remove
        """
        for protocol in protocols:
            if protocol in self.protocols:
                self.protocols.remove(protocol)

    def supports_protocols(self, protocols: Sequence[str]) -> list[str]:
        """
        :param protocols: protocols to check from
        :return: all supported protocols in the given list
        """
        return [proto for proto in protocols if proto in self.protocols]

    def first_supported_protocol(self, protocols: Sequence[str]) -> str:
        """
        :param protocols: protocols to check from
        :return: first supported protocol in the given list
        """
        for protocol in protocols:
            if protocol in self.protocols:
                return protocol

        return "None supported"

    def clear_protocol_data(self) -> None:
        """Clear all protocols"""
        self.protocols = []

    def add_addrs(self, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        :param addrs: multiaddresses to add
        """
        expiry = time.time() + ttl if ttl is not None else float("inf")
        for addr in addrs:
            if addr not in self.addrs:
                self.addrs.append(addr)
            current_expiry = self.addrs_ttl.get(addr, 0)
            if expiry > current_expiry:
                self.addrs_ttl[addr] = expiry

    def set_addrs(self, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        :param addrs: multiaddresses to update
        :param ttl: new ttl
        """
        now = time.time()

        if ttl <= 0:
            # Put the TTL value to -1
            for addr in addrs:
                # TODO! if addr in self.addrs, remove them?
                if addr in self.addrs_ttl:
                    del self.addrs_ttl[addr]
            return

        expiry = now + ttl
        for addr in addrs:
            # TODO! if addr not in self.addrs, add them?
            self.addrs_ttl[addr] = expiry

    def update_addrs(self, oldTTL: int, newTTL: int) -> None:
        """
        :param oldTTL: old ttl
        :param newTTL: new ttl
        """
        now = time.time()

        new_expiry = now + newTTL
        old_expiry = now + oldTTL

        for addr, expiry in list(self.addrs_ttl.items()):
            # Approximate match by expiry time
            if abs(expiry - old_expiry) < 1:
                self.addrs_ttl[addr] = new_expiry

    def get_addrs(self) -> list[Multiaddr]:
        """
        :return: all multiaddresses
        """
        return self.addrs

    def clear_addrs(self) -> None:
        """Clear all addresses."""
        self.addrs = []

    def put_metadata(self, key: str, val: Any) -> None:
        """
        :param key: key in KV pair
        :param val: val to associate with key
        """
        self.metadata[key] = val

    def get_metadata(self, key: str) -> Any:
        """
        :param key: key in KV pair
        :return: val for key
        :raise PeerDataError: key not found
        """
        if key in self.metadata:
            return self.metadata[key]
        raise PeerDataError("key not found")

    def clear_metadata(self) -> None:
        """Clears metadata."""
        self.metadata = {}

    def add_pubkey(self, pubkey: PublicKey) -> None:
        """
        :param pubkey:
        """
        self.pubkey = pubkey

    def get_pubkey(self) -> PublicKey:
        """
        :return: public key of the peer
        :raise PeerDataError: if public key not found
        """
        if self.pubkey is None:
            raise PeerDataError("public key not found")
        return self.pubkey

    def add_privkey(self, privkey: PrivateKey) -> None:
        """
        :param privkey:
        """
        self.privkey = privkey

    def get_privkey(self) -> PrivateKey:
        """
        :return: private key of the peer
        :raise PeerDataError: if private key not found
        """
        if self.privkey is None:
            raise PeerDataError("private key not found")
        return self.privkey

    def update_last_identified(self) -> None:
        self.last_identified = int(time.time())

    def get_last_identified(self) -> int:
        """
        :return: last identified timestamp
        """
        return self.last_identified

    def get_ttl(self) -> int:
        """
        :return: ttl for current peer
        """
        return self.ttl

    def set_ttl(self, ttl: int) -> None:
        """
        :param ttl: ttl to set
        """
        self.ttl = ttl

    def is_expired(self) -> bool:
        """
        :return: true, if last_identified+ttl > current_time
        """
        # for ttl = 0; peer_data is always valid
        if self.ttl > 0 and self.last_identified + self.ttl < int(time.time()):
            return True
        return False


class PeerDataError(KeyError):
    """Raised when a key is not found in peer metadata."""
