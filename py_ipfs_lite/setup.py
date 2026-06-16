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
    
    from libp2p.security.noise.transport import Transport as NoiseTransport
    from libp2p.security.secio.transport import Transport as SecioTransport
    from libp2p.crypto.keys import KeyPair
    import libp2p.security.secio.transport as secio
    from libp2p.crypto.ed25519 import create_new_key_pair
    from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
    
    host_key_pair = host_key if isinstance(host_key, KeyPair) else create_new_key_pair()
    
    # Disable TLS to avoid python ssl limitations breaking interop
    noise_key_pair = create_new_x25519_key_pair()
    sec_opt = {
        "/noise": NoiseTransport(host_key_pair, noise_privkey=noise_key_pair.private_key),
        "/secio/1.0.0": SecioTransport(host_key_pair),
    }

    host = new_host(
        key_pair=host_key_pair,
        listen_addrs=maddrs,
        sec_opt=sec_opt
    )
    routing = KadDHT(host=host, mode=DHTMode.SERVER)
    return host, routing

