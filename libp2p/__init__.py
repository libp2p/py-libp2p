from collections.abc import (
    Mapping,
    Sequence,
)
from importlib.metadata import version as __version
from typing import (
    Literal,
    Optional,
    Type,
    cast,
)

import multiaddr

from libp2p.abc import (
    IHost,
    IMuxedConn,
    INetworkService,
    IPeerRouting,
    IPeerStore,
    ISecureTransport,
)
from libp2p.crypto.keys import (
    KeyPair,
)
from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import (
    TMuxerOptions,
    TProtocol,
    TSecurityOptions,
)
from libp2p.discovery.mdns.mdns import (
    MDNSDiscovery,
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
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
from libp2p.security.noise.transport import Transport as NoiseTransport
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.stream_muxer.yamux.yamux import (
    Yamux,
)
from libp2p.stream_muxer.yamux.yamux import PROTOCOL_ID as YAMUX_PROTOCOL_ID
from libp2p.transport.tcp.tcp import (
    TCP,
)
from libp2p.transport.upgrader import (
    TransportUpgrader,
)
from libp2p.utils.logging import (
    setup_logging,
)

# Initialize logging configuration
setup_logging()

# Default multiplexer choice
DEFAULT_MUXER = "YAMUX"

# Multiplexer options
MUXER_YAMUX = "YAMUX"
MUXER_MPLEX = "MPLEX"
DEFAULT_NEGOTIATE_TIMEOUT = 5



def set_default_muxer(muxer_name: Literal["YAMUX", "MPLEX"]) -> None:
    """
    Set the default multiplexer protocol to use.

    :param muxer_name: Either "YAMUX" or "MPLEX"
    :raise ValueError: If an unsupported muxer name is provided
    """
    global DEFAULT_MUXER
    muxer_upper = muxer_name.upper()
    if muxer_upper not in [MUXER_YAMUX, MUXER_MPLEX]:
        raise ValueError(f"Unknown muxer: {muxer_name}. Use 'YAMUX' or 'MPLEX'.")
    DEFAULT_MUXER = muxer_upper


def get_default_muxer() -> str:
    """
    Returns the currently selected default muxer.

    :return: Either "YAMUX" or "MPLEX"
    """
    return DEFAULT_MUXER


def create_yamux_muxer_option() -> TMuxerOptions:
    """
    Returns muxer options with Yamux as the primary choice.

    :return: Muxer options with Yamux first
    """
    return {
        TProtocol(YAMUX_PROTOCOL_ID): Yamux,  # Primary choice
        TProtocol(MPLEX_PROTOCOL_ID): Mplex,  # Fallback for compatibility
    }


def create_mplex_muxer_option() -> TMuxerOptions:
    """
    Returns muxer options with Mplex as the primary choice.

    :return: Muxer options with Mplex first
    """
    return {
        TProtocol(MPLEX_PROTOCOL_ID): Mplex,  # Primary choice
        TProtocol(YAMUX_PROTOCOL_ID): Yamux,  # Fallback
    }


def generate_new_rsa_identity() -> KeyPair:
    return create_new_key_pair()


def generate_peer_id_from(key_pair: KeyPair) -> ID:
    public_key = key_pair.public_key
    return ID.from_pubkey(public_key)


def get_default_muxer_options() -> TMuxerOptions:
    """
    Returns the default muxer options based on the current default muxer setting.

    :return: Muxer options with the preferred muxer first
    """
    if DEFAULT_MUXER == "MPLEX":
        return create_mplex_muxer_option()
    else:  # YAMUX is default
        return create_yamux_muxer_option()


def new_swarm(
    key_pair: KeyPair | None = None,
    muxer_opt: TMuxerOptions | None = None,
    sec_opt: TSecurityOptions | None = None,
    peerstore_opt: IPeerStore | None = None,
    muxer_preference: Literal["YAMUX", "MPLEX"] | None = None,
    listen_addrs: Sequence[multiaddr.Multiaddr] | None = None,
) -> INetworkService:
    """
    Create a swarm instance based on the parameters.

    :param key_pair: optional choice of the ``KeyPair``
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param muxer_preference: optional explicit muxer preference
    :param listen_addrs: optional list of multiaddrs to listen on
    :return: return a default swarm instance

    Note: Yamux (/yamux/1.0.0) is the preferred stream multiplexer
          due to its improved performance and features.
          Mplex (/mplex/6.7.0) is retained for backward compatibility
          but may be deprecated in the future.
    """
    if key_pair is None:
        key_pair = generate_new_rsa_identity()

    id_opt = generate_peer_id_from(key_pair)

    if listen_addrs is None:
        transport = TCP()
    else:
        addr = listen_addrs[0]
        if addr.__contains__("tcp"):
            transport = TCP()
        elif addr.__contains__("quic"):
            raise ValueError("QUIC not yet supported")
        else:
            raise ValueError(f"Unknown transport in listen_addrs: {listen_addrs}")

    # Generate X25519 keypair for Noise
    noise_key_pair = create_new_x25519_key_pair()

    # Default security transports (using Noise as primary)
    secure_transports_by_protocol: Mapping[TProtocol, ISecureTransport] = sec_opt or {
        NOISE_PROTOCOL_ID: NoiseTransport(
            key_pair, noise_privkey=noise_key_pair.private_key
        ),
        TProtocol(secio.ID): secio.Transport(key_pair),
        TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(
            key_pair, peerstore=peerstore_opt
        ),
    }

    # Use given muxer preference if provided, otherwise use global default
    if muxer_preference is not None:
        temp_pref = muxer_preference.upper()
        if temp_pref not in [MUXER_YAMUX, MUXER_MPLEX]:
            raise ValueError(
                f"Unknown muxer: {muxer_preference}. Use 'YAMUX' or 'MPLEX'."
            )
        active_preference = temp_pref
    else:
        active_preference = DEFAULT_MUXER

    # Use provided muxer options if given, otherwise create based on preference
    if muxer_opt is not None:
        muxer_transports_by_protocol = muxer_opt
    else:
        if active_preference == MUXER_MPLEX:
            muxer_transports_by_protocol = create_mplex_muxer_option()
        else:  # YAMUX is default
            muxer_transports_by_protocol = create_yamux_muxer_option()

    upgrader = TransportUpgrader(
        secure_transports_by_protocol=secure_transports_by_protocol,
        muxer_transports_by_protocol=muxer_transports_by_protocol,
    )

    peerstore = peerstore_opt or PeerStore()
    # Store our key pair in peerstore
    peerstore.add_key_pair(id_opt, key_pair)

    return Swarm(id_opt, peerstore, upgrader, transport)


def new_host(
    key_pair: KeyPair | None = None,
    muxer_opt: TMuxerOptions | None = None,
    sec_opt: TSecurityOptions | None = None,
    peerstore_opt: IPeerStore | None = None,
    disc_opt: IPeerRouting | None = None,
    muxer_preference: Literal["YAMUX", "MPLEX"] | None = None,
    listen_addrs: Sequence[multiaddr.Multiaddr] | None = None,
    enable_mDNS: bool = False,
    negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
) -> IHost:
    """
    Create a new libp2p host based on the given parameters.

    :param key_pair: optional choice of the ``KeyPair``
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param disc_opt: optional discovery
    :param muxer_preference: optional explicit muxer preference
    :param listen_addrs: optional list of multiaddrs to listen on
    :param enable_mDNS: whether to enable mDNS discovery
    :return: return a host instance
    """
    swarm = new_swarm(
        key_pair=key_pair,
        muxer_opt=muxer_opt,
        sec_opt=sec_opt,
        peerstore_opt=peerstore_opt,
        muxer_preference=muxer_preference,
        listen_addrs=listen_addrs,
    )

    if disc_opt is not None:
        return RoutedHost(swarm, disc_opt, enable_mDNS)
    return BasicHost(network=swarm,enable_mDNS=enable_mDNS , negotitate_timeout=negotiate_timeout)

__version__ = __version("libp2p")
