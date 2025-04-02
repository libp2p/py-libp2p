from collections.abc import (
    Mapping,
)
from importlib.metadata import version as __version
from typing import (
    Type,
    cast,
)

from libp2p.abc import (
    IHost,
    IMuxedConn,
    INetworkService,
    IPeerRouting,
    IPeerStore,
    ISecureTransport,
)
from libp2p.crypto.ed25519 import create_new_key_pair as create_ed25519_key_pair
from libp2p.crypto.keys import (
    KeyPair,
)
from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TMuxerOptions,
    TProtocol,
    TSecurityOptions,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.host.routed_host import (
    RoutedHost,
)
from libp2p.network.swarm import (
    Swarm,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import (
    PeerStore,
)
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)
from libp2p.security.noise.transport import (
    PROTOCOL_ID,
    Transport,
)
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.stream_muxer.yamux.yamux import (
    Yamux,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)
from libp2p.transport.upgrader import (
    TransportUpgrader,
)


def generate_new_rsa_identity() -> KeyPair:
    return create_new_key_pair()


def generate_peer_id_from(key_pair: KeyPair) -> ID:
    public_key = key_pair.public_key
    return ID.from_pubkey(public_key)


def new_swarm(
    key_pair: KeyPair = None,
    muxer_opt: TMuxerOptions = None,
    sec_opt: TSecurityOptions = None,
    peerstore_opt: IPeerStore = None,
) -> INetworkService:
    """
    Create a swarm instance based on the parameters.

    :param key_pair: optional choice of the ``KeyPair``
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :return: return a default swarm instance
    """
    if key_pair is None:
        key_pair = create_ed25519_key_pair()  # Use Ed25519 instead of RSA

    id_opt = generate_peer_id_from(key_pair)
    transport = TCP()
    # noise_key_pair = key_pair  # Alternatively: create_ed25519_key_pair()

    secure_transports_by_protocol: Mapping[TProtocol, ISecureTransport] = {
        PROTOCOL_ID: Transport(key_pair, noise_privkey=key_pair.private_key)
    }
    muxer_transports_by_protocol: Mapping[TProtocol, type[IMuxedConn]] = {
        cast(TProtocol, "/yamux/1.0.0"): Yamux
    }

    upgrader = TransportUpgrader(
        secure_transports_by_protocol=secure_transports_by_protocol,
        muxer_transports_by_protocol=muxer_transports_by_protocol,
    )

    peerstore = peerstore_opt or PeerStore()
    peerstore.add_key_pair(id_opt, key_pair)

    return Swarm(id_opt, peerstore, upgrader, transport)


def new_host(
    key_pair: KeyPair = None,
    muxer_opt: TMuxerOptions = None,
    sec_opt: TSecurityOptions = None,
    peerstore_opt: IPeerStore = None,
    disc_opt: IPeerRouting = None,
) -> IHost:
    """
    Create a new libp2p host based on the given parameters.

    :param key_pair: optional choice of the ``KeyPair``
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param disc_opt: optional discovery
    :return: return a host instance
    """
    swarm = new_swarm(
        key_pair=key_pair,
        muxer_opt=muxer_opt,
        sec_opt=sec_opt,
        peerstore_opt=peerstore_opt,
    )
    host: IHost
    if disc_opt:
        host = RoutedHost(swarm, disc_opt)
    else:
        host = BasicHost(swarm)
    return host


__version__ = __version("libp2p")
