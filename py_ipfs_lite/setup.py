from __future__ import annotations

from typing import Any

from libp2p import new_host
from libp2p.crypto.keys import KeyPair
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from multiaddr import Multiaddr


def default_bootstrap_peers() -> list[Any]:
    return [
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
    ]


def new_in_memory_datastore() -> dict[str, bytes]:
    return {}


async def setup_libp2p(
    *,
    host_key: Any,
    secret: bytes | None,
    listen_addrs: list[Any],
    datastore: Any | None,
    extra_options: list[Any] | None = None,
) -> tuple[Any, Any]:
    # Ensure host_key is a proper KeyPair if it's supposed to be
    # and listen_addrs are Multiaddrs
    maddrs = [Multiaddr(a) if isinstance(a, str) else a for a in listen_addrs]
    
    host = new_host(
        key_pair=host_key if isinstance(host_key, KeyPair) else None,
        listen_addrs=maddrs
    )
    routing = KadDHT(host=host, mode=DHTMode.SERVER)
    return host, routing

