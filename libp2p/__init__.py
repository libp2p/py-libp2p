"""Libp2p Python implementation."""

from __future__ import annotations

import logging
from pathlib import Path
import ssl
from libp2p.transport.quic.utils import is_quic_multiaddr
from typing import Any
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.config import QUICTransportConfig
from collections.abc import (
    Mapping,
    Sequence,
)
from importlib.metadata import version as __version
from typing import (
    Literal,
    Optional,
)

import multiaddr

from libp2p.abc import (
    IHost,
    INetworkService,
    IPeerRouting,
    IPeerStore,
    ISecureTransport,
    ITransport,
)
from libp2p.rcmgr import ResourceManager
from libp2p.crypto.keys import (
    KeyPair,
)
from libp2p.crypto.ed25519 import (
    Ed25519PrivateKey,
    create_new_key_pair as create_new_ed25519_key_pair,
)
from libp2p.crypto.rsa import (
    create_new_key_pair as create_new_rsa_key_pair,
)
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
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
from libp2p.network.config import (
    ConnectionConfig,
    RetryConfig
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import (
    PeerStore,
    create_signed_peer_record,
)
from libp2p.peer.persistent import (
    create_sync_peerstore,
    create_async_peerstore,
    create_sync_sqlite_peerstore,
    create_async_sqlite_peerstore,
    create_sync_memory_peerstore,
    create_async_memory_peerstore,
    create_sync_leveldb_peerstore,
    create_async_leveldb_peerstore,
    create_sync_rocksdb_peerstore,
    create_async_rocksdb_peerstore,
)
import libp2p
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.security.tls.transport import (
    PROTOCOL_ID as TLS_PROTOCOL_ID,
    TLSTransport
)

import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.stream_muxer.yamux.yamux import (
    PROTOCOL_ID as YAMUX_PROTOCOL_ID,
    Yamux,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)
from libp2p.transport.upgrader import (
    TransportUpgrader,
)
from libp2p.transport.transport_registry import (
    create_transport_for_multiaddr,
    get_supported_transport_protocols,
)
import libp2p.utils
from libp2p.utils.logging import (
    setup_logging,
)
import libp2p.utils.paths

# Initialize logging configuration
setup_logging()

# Default multiplexer choice
DEFAULT_MUXER = "YAMUX"

# Multiplexer options
MUXER_YAMUX = "YAMUX"
MUXER_MPLEX = "MPLEX"
DEFAULT_NEGOTIATE_TIMEOUT = 30  # seconds - increased for high-concurrency scenarios

logger = logging.getLogger(__name__)

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

def save_keypair(key_pair: KeyPair, type: str= "ed25519") -> None:
    """
    Persist a private key to disk in PEM format.

    Currently supports only Ed25519 keys. Writes the key to a predefined
    path for later retrieval.

    :param key_pair: KeyPair object containing private and public keys.
    :param type: Type of key to save (default: "ed25519").
    :raises ValueError: if an unsupported key type is provided.
    """
    pvt_key = key_pair.private_key

    match type:
        case "ed25519":
            assert isinstance(pvt_key, Ed25519PrivateKey)
            raw = pvt_key.to_bytes()
            crypto_key = ed25519.Ed25519PrivateKey.from_private_bytes(raw)

            pem = crypto_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )

            libp2p.utils.paths.ED25519_PATH.write_bytes(pem)

        case _:
            raise ValueError(f"unsupported key type: {type}")

def load_keypair(type: str = "ed25519") -> KeyPair | None:
    """
    Load a private key from disk and reconstruct its KeyPair.

    Currently supports only Ed25519 keys. Returns None if the key file does
    not exist.

    :param type: Type of key to load (default: "ed25519").
    :return: KeyPair object if found, or None.
    :raises ValueError: if an unsupported key type is provided.
    """

    match type:
        case "ed25519":
            path = libp2p.utils.paths.ED25519_PATH
            if not path.exists():
                return None

            pem = path.read_bytes()
            crypto_key = serialization.load_pem_private_key(
                pem,
                password=None,
            )

            assert isinstance(crypto_key, ed25519.Ed25519PrivateKey)
            raw = crypto_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )

            pvt_key = Ed25519PrivateKey.from_bytes(raw)
            pub_key = pvt_key.get_public_key()

            return KeyPair(pvt_key, pub_key)

        case _:
            raise ValueError(f"unsupported key type: {type}")


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
    return create_new_rsa_key_pair()


def generate_new_ed25519_identity() -> KeyPair:
    """
    Generate a new Ed25519 identity key pair.

    Ed25519 is preferred for better interoperability with other libp2p implementations
    (e.g., Rust, Go) which often disable RSA support.
    """
    return create_new_ed25519_key_pair()


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
    enable_quic: bool = False,
    enable_autotls: bool = False,
    retry_config: RetryConfig | None = None,
    connection_config: ConnectionConfig | QUICTransportConfig | None = None,
    tls_client_config: ssl.SSLContext | None = None,
    tls_server_config: ssl.SSLContext | None = None,
    resource_manager: ResourceManager | None = None,
    psk: str | None = None
) -> INetworkService:
    logger.debug(f"new_swarm: enable_quic={enable_quic}, listen_addrs={listen_addrs}")
    """
    Create a swarm instance based on the parameters.

    :param key_pair: optional choice of the ``KeyPair``
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param muxer_preference: optional explicit muxer preference
    :param listen_addrs: optional list of multiaddrs to listen on
    :param enable_quic: enable quic for transport
    :param enable_autotls: enable autotls for security
    :param quic_transport_opt: options for transport
    :param resource_manager: optional resource manager for connection/stream limits
    :type resource_manager: :class:`libp2p.rcmgr.ResourceManager` or None
    :param psk: optional pre-shared key for PSK encryption in transport
    :return: return a default swarm instance

    Note: Yamux (/yamux/1.0.0) is the preferred stream multiplexer
          due to its improved performance and features.
          Mplex (/mplex/6.7.0) is retained for backward compatibility
          but may be deprecated in the future.

    Note: Ed25519 keys are used by default for better interoperability with
          other libp2p implementations (Rust, Go) which often disable RSA support.
    """
    if key_pair is None:
        # Use Ed25519 by default for better interoperability with Rust/Go libp2p
        # which often compile without RSA support
        key_pair = generate_new_ed25519_identity()

    id_opt = generate_peer_id_from(key_pair)

    transport: TCP | QUICTransport | ITransport
    quic_transport_opt = connection_config if isinstance(connection_config, QUICTransportConfig) else None

    if listen_addrs is None:
        if enable_quic:
            transport = QUICTransport(key_pair.private_key, config=quic_transport_opt)
        else:
            transport = TCP()
    else:
        # Use transport registry to select the appropriate transport
        from libp2p.transport.transport_registry import create_transport_for_multiaddr

        # Create a temporary upgrader for transport selection
        # We'll create the real upgrader later with the proper configuration
        temp_upgrader = TransportUpgrader(
            secure_transports_by_protocol={},
            muxer_transports_by_protocol={}
        )

        addr = listen_addrs[0]
        logger.debug(f"new_swarm: Creating transport for address: {addr}")
        transport_maybe = create_transport_for_multiaddr(
            addr,
            temp_upgrader,
            private_key=key_pair.private_key,
            config=quic_transport_opt,
            tls_client_config=tls_client_config,
            tls_server_config=tls_server_config
        )

        if transport_maybe is None:
            raise ValueError(f"Unsupported transport for listen_addrs: {listen_addrs}")

        transport = transport_maybe
        logger.debug(f"new_swarm: Created transport: {type(transport)}")

    # If enable_quic is True but we didn't get a QUIC transport, force QUIC
    if enable_quic and not isinstance(transport, QUICTransport):
        logger.debug(f"new_swarm: Forcing QUIC transport (enable_quic=True but got {type(transport)})")
        transport = QUICTransport(key_pair.private_key, config=quic_transport_opt)

    logger.debug(f"new_swarm: Final transport type: {type(transport)}")

    # Generate X25519 keypair for Noise
    noise_key_pair = create_new_x25519_key_pair()

    # Default security transports
    # NOTE: Using Noise as primary for now because Python's ssl module has limitations
    # with mutual TLS authentication. See TLS_ANALYSIS.md for details.
    # TLS is still offered as a fallback option.
    secure_transports_by_protocol: Mapping[TProtocol, ISecureTransport] = sec_opt or {
        # TLS_PROTOCOL_ID: TLSTransport(key_pair),
        NOISE_PROTOCOL_ID: NoiseTransport(
            key_pair, noise_privkey=noise_key_pair.private_key
        ),
        TLS_PROTOCOL_ID: TLSTransport (
            key_pair, enable_autotls= enable_autotls
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

    swarm = Swarm(
        id_opt,
        peerstore,
        upgrader,
        transport,
        retry_config=retry_config,
        connection_config=connection_config,
        psk=psk
    )

    # Set resource manager if provided
    # Auto-create a default ResourceManager if one was not provided
    if resource_manager is None:
        try:
            from libp2p.rcmgr import new_resource_manager as _new_rm

            resource_manager = _new_rm()
        except Exception:
            resource_manager = None

    if resource_manager is not None:
        swarm.set_resource_manager(resource_manager)

    return swarm

    # Set resource manager if provided
    # Auto-create a default ResourceManager if one was not provided
    if resource_manager is None:
        try:
            from libp2p.rcmgr import new_resource_manager as _new_rm

            resource_manager = _new_rm()
        except Exception:
            resource_manager = None

    if resource_manager is not None:
        swarm.set_resource_manager(resource_manager)

    return swarm


def new_host(
    key_pair: KeyPair | None = None,
    muxer_opt: TMuxerOptions | None = None,
    sec_opt: TSecurityOptions | None = None,
    peerstore_opt: IPeerStore | None = None,
    disc_opt: IPeerRouting | None = None,
    muxer_preference: Literal["YAMUX", "MPLEX"] | None = None,
    listen_addrs: Sequence[multiaddr.Multiaddr] | None = None,
    enable_mDNS: bool = False,
    enable_upnp: bool = False,
    enable_autotls: bool = False,
    bootstrap: list[str] | None = None,
    negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    enable_quic: bool = False,
    quic_transport_opt: QUICTransportConfig | None = None,
    tls_client_config: ssl.SSLContext | None = None,
    tls_server_config: ssl.SSLContext | None = None,
    resource_manager: ResourceManager | None = None,
    psk: str | None = None
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
    :param bootstrap: optional list of bootstrap peer addresses as strings
    :param enable_quic: optinal choice to use QUIC for transport
    :param enable_autotls: optinal choice to use AutoTLS for security
    :param quic_transport_opt: optional configuration for quic transport
    :param tls_client_config: optional TLS client configuration for WebSocket transport
    :param tls_server_config: optional TLS server configuration for WebSocket transport
    :param resource_manager: optional resource manager for connection/stream limits
    :type resource_manager: :class:`libp2p.rcmgr.ResourceManager` or None
    :param psk: optional pre-shared key (PSK)
    :return: return a host instance
    """

    if not enable_quic and quic_transport_opt is not None:
        logger.warning(f"QUIC config provided but QUIC not enabled, ignoring QUIC config")

    # Enable automatic protection by default: if no resource manager is supplied,
    # create a default instance so connections/streams are guarded out of the box.
    if resource_manager is None:
        try:
            from libp2p.rcmgr import new_resource_manager as _new_rm

            resource_manager = _new_rm()
        except Exception:
            # Fallback to leaving it None if creation fails for any reason.
            resource_manager = None

    swarm = new_swarm(
        enable_quic=enable_quic,
        key_pair=key_pair,
        muxer_opt=muxer_opt,
        sec_opt=sec_opt,
        peerstore_opt=peerstore_opt,
        enable_autotls=enable_autotls,
        muxer_preference=muxer_preference,
        listen_addrs=listen_addrs,
        connection_config=quic_transport_opt if enable_quic else None,
        tls_client_config=tls_client_config,
        tls_server_config=tls_server_config,
        resource_manager=resource_manager,
        psk=psk
    )

    if disc_opt is not None:
        return RoutedHost(
            network=swarm,
            router=disc_opt,
            enable_mDNS=enable_mDNS,
            enable_upnp=enable_upnp,
            bootstrap=bootstrap,
            resource_manager=resource_manager,
        )
    return BasicHost(
        network=swarm,
        enable_mDNS=enable_mDNS,
        bootstrap=bootstrap,
        enable_upnp=enable_upnp,
        negotiate_timeout=negotiate_timeout,
        resource_manager=resource_manager,
    )

__version__ = __version("libp2p")
