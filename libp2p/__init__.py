"""Libp2p Python implementation."""

from __future__ import annotations

import logging
from pathlib import Path
import ssl
from libp2p.transport.quic.utils import is_quic_multiaddr
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from libp2p.transport.cmux import PortDemultiplexer
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

def _build_transports_for_swarm(
    key_pair: KeyPair,
    listen_addrs: Sequence[multiaddr.Multiaddr] | None,
    transports: Sequence[ITransport] | None,
    enable_quic: bool,
    enable_tcp: bool,
    enable_websocket: bool,
    enable_autotls: bool,
    upgrader: TransportUpgrader,
    quic_config: QUICTransportConfig | None,
    tls_client_config: ssl.SSLContext | None,
    tls_server_config: ssl.SSLContext | None,
    # Pass QUICTransport class from module scope so monkeypatching in tests works.
    quic_class: type | None = None,
) -> list[ITransport]:
    """
    Build the ordered list of transports for the Swarm's TransportManager.

    Priority:
    1. Explicit ``transports`` list — used as-is (highest priority).
    2. ``listen_addrs`` inspection — auto-detects which transports are needed
       by inspecting **every** address (not just the first one).
    3. ``enable_*`` flags — coarse-grained control when no addresses given.
    4. Default fallback: TCP only.

    :param key_pair: The host's key pair (needed by QUIC for TLS).
    :param listen_addrs: The multiaddrs the host will listen on.
    :param transports: Explicit transport list, or ``None`` to auto-build.
    :param enable_quic: Whether to create a QUIC transport when auto-building.
    :param enable_tcp: Whether to include a TCP transport when auto-building.
    :param enable_websocket: Whether to include a WebSocket transport.
    :param enable_autotls: Whether to enable AutoTLS in QUIC/WebSocket transports.
    :param upgrader: The upgrader passed to WebSocket transport at construction.
    :param quic_config: Optional QUIC transport configuration.
    :param tls_client_config: TLS client context for WebSocket.
    :param tls_server_config: TLS server context for WebSocket.
    :returns: Ordered list of :class:`~libp2p.abc.ITransport` instances.
    """
    # Highest priority: user-supplied explicit list.
    if transports is not None:
        return list(transports)

    # Use the provided class (patchable by tests) or fall back to module-level import.
    _QUICTransport = quic_class if quic_class is not None else QUICTransport

    result: list[ITransport] = []

    if listen_addrs:
        # Use the transport registry to create transports for each address type,
        # matching the original new_swarm() behavior so monkeypatching the registry
        # in tests still works correctly.
        # NOTE: import the module (not the function) so tests can monkeypatch
        # `transport_registry.create_transport_for_multiaddr` and have it respected.
        from libp2p.transport import transport_registry as _tr

        # Build a temporary upgrader for registry lookup (the real upgrader is wired
        # in after the Swarm is created; the registry uses it mainly for WebSocket).
        from libp2p.transport.upgrader import TransportUpgrader as _TU

        temp_upgrader = _TU(
            secure_transports_by_protocol={},
            muxer_transports_by_protocol={},
        )

        seen_classes: set[type] = set()
        for addr in listen_addrs:
            transport_obj = _tr.create_transport_for_multiaddr(
                addr,
                temp_upgrader,
                private_key=key_pair.private_key,
                config=quic_config,
                enable_autotls=enable_autotls,
                tls_client_config=tls_client_config,
                tls_server_config=tls_server_config,
            )
            if transport_obj is None:
                continue

            cls = type(transport_obj)
            if cls not in seen_classes:
                seen_classes.add(cls)
                # For WebSocket, re-create with the real upgrader so the transport
                # gets the actual security/muxer config.
                from libp2p.transport.websocket.transport import WebsocketTransport
                if isinstance(transport_obj, WebsocketTransport):
                    transport_obj = WebsocketTransport(
                        upgrader,
                        tls_client_config=tls_client_config,
                        tls_server_config=tls_server_config,
                    )
                result.append(transport_obj)

        # If enable_quic=True is requested but no QUIC was detected in listen_addrs,
        # replace the result with only the QUIC transport (mirrors original new_swarm()
        # behavior where the transport was replaced rather than appended).
        if enable_quic and not any(type(t).__name__ == "QUICTransport" for t in result):
            result = [
                _QUICTransport(
                    key_pair.private_key,
                    config=quic_config,
                    enable_autotls=enable_autotls,
                )
            ]

    # Fall through to flags if nothing was auto-detected.
    if not result:
        if enable_quic:
            result.append(
                _QUICTransport(
                    key_pair.private_key,
                    config=quic_config,
                    enable_autotls=enable_autotls,
                )
            )
        if enable_websocket:
            from libp2p.transport.websocket.transport import WebsocketTransport
            result.append(
                WebsocketTransport(
                    upgrader,
                    tls_client_config=tls_client_config,
                    tls_server_config=tls_server_config,
                )
            )
        if enable_tcp or not result:
            result.append(TCP())

    return result


def new_swarm(
    key_pair: KeyPair | None = None,
    muxer_opt: TMuxerOptions | None = None,
    sec_opt: TSecurityOptions | None = None,
    peerstore_opt: IPeerStore | None = None,
    muxer_preference: Literal["YAMUX", "MPLEX"] | None = None,
    listen_addrs: Sequence[multiaddr.Multiaddr] | None = None,
    # NEW: explicit transport list — highest priority
    transports: Sequence[ITransport] | None = None,
    # Backward-compat flags
    enable_quic: bool = False,
    enable_webrtc: bool = False,
    enable_autotls: bool = False,
    # NEW: convenience flags for auto-building transports
    enable_tcp: bool = True,
    enable_websocket: bool = False,
    retry_config: RetryConfig | None = None,
    connection_config: ConnectionConfig | QUICTransportConfig | None = None,
    tls_client_config: ssl.SSLContext | None = None,
    tls_server_config: ssl.SSLContext | None = None,
    resource_manager: ResourceManager | None = None,
    psk: str | None = None,
) -> INetworkService:
    """
    Create a swarm instance with multi-transport support.

    The swarm can listen on and dial over multiple transports simultaneously
    (TCP, WebSocket, QUIC), mirroring go-libp2p's architecture.

    Transport selection priority (highest to lowest):

    1. **Explicit ``transports`` list** — used as-is; all other transport
       parameters are ignored.
    2. **``listen_addrs`` inspection** — each address is inspected to determine
       which transports are needed (TCP, WebSocket, QUIC).  All detected
       transport types are created and registered.
    3. **``enable_*`` flags** — coarse-grained control when no addresses are
       provided (``enable_quic``, ``enable_websocket``, ``enable_tcp``).
    4. **Default fallback** — TCP only.

    :param key_pair: optional choice of the ``KeyPair``
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param muxer_preference: optional explicit muxer preference (``"YAMUX"`` or
        ``"MPLEX"``)
    :param listen_addrs: optional list of multiaddrs to listen on.  **All**
        addresses are inspected to determine which transports to create.
    :param transports: explicit list of transport instances to register.  When
        provided, all ``enable_*`` flags and ``listen_addrs``-based detection
        are bypassed.
    :param enable_quic: include a QUIC transport when auto-building (deprecated;
        prefer passing ``listen_addrs`` with QUIC addresses or ``transports``).
    :param enable_autotls: enable AutoTLS for QUIC / WebSocket transports.
    :param enable_tcp: include a TCP transport when auto-building (default True).
    :param enable_websocket: include a WebSocket transport when auto-building.
    :param retry_config: optional connection retry configuration.
    :param connection_config: optional connection configuration.
    :param tls_client_config: TLS client context for WebSocket transport.
    :param tls_server_config: TLS server context for WebSocket transport.
    :param resource_manager: optional resource manager for connection/stream limits.
    :param psk: optional pre-shared key for PSK encryption.
    :return: a Swarm instance implementing INetworkService.

    Examples::

        # TCP only (default)
        swarm = new_swarm()

        # TCP + WebSocket + QUIC auto-detected from listen_addrs
        swarm = new_swarm(listen_addrs=[
            Multiaddr("/ip4/0.0.0.0/tcp/4001"),
            Multiaddr("/ip4/0.0.0.0/tcp/4002/ws"),
            Multiaddr("/ip4/0.0.0.0/udp/4003/quic-v1"),
        ])

        # Explicit transport list
        swarm = new_swarm(transports=[TCP(), QUICTransport(kp.private_key)])

    Note: Yamux (/yamux/1.0.0) is the preferred stream multiplexer due to
          improved performance and features. Mplex is retained for backward
          compatibility but may be deprecated in the future.
    """
    logger.debug(
        "new_swarm: enable_quic=%s, enable_websocket=%s, listen_addrs=%s, "
        "transports=%s",
        enable_quic,
        enable_websocket,
        listen_addrs,
        [type(t).__name__ for t in transports] if transports is not None else None,
    )

    if key_pair is None:
        # Use Ed25519 by default for better interoperability with Rust/Go libp2p
        key_pair = generate_new_ed25519_identity()

    id_opt = generate_peer_id_from(key_pair)

    transport: TCP | QUICTransport | ITransport
    quic_transport_opt = connection_config if isinstance(connection_config, QUICTransportConfig) else None

    if listen_addrs is None:
        if enable_quic:
            transport = QUICTransport(
                key_pair.private_key,
                config=quic_transport_opt,
                enable_autotls=enable_autotls,
            )
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
            enable_autotls=enable_autotls,
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
        transport = QUICTransport(
            key_pair.private_key,
            config=quic_transport_opt,
            enable_autotls=enable_autotls,
        )

    # If enable_webrtc is True, force WebRTC Direct transport
    if enable_webrtc:
        from libp2p.transport.webrtc.transport import WebRTCDirectTransport

        logger.debug("new_swarm: Creating WebRTC Direct transport")
        transport = WebRTCDirectTransport(private_key=key_pair.private_key)

    logger.debug(f"new_swarm: Final transport type: {type(transport)}")

    # Generate X25519 keypair for Noise
    noise_key_pair = create_new_x25519_key_pair()

    # Default security transports
    secure_transports_by_protocol: Mapping[TProtocol, ISecureTransport] = sec_opt or {
        NOISE_PROTOCOL_ID: NoiseTransport(
            key_pair, noise_privkey=noise_key_pair.private_key
        ),
        TLS_PROTOCOL_ID: TLSTransport(key_pair, enable_autotls=enable_autotls),
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

    # Build the real upgrader first (WebSocket transport needs it at construction).
    upgrader = TransportUpgrader(
        secure_transports_by_protocol=secure_transports_by_protocol,
        muxer_transports_by_protocol=muxer_transports_by_protocol,
    )

    # Build the transport list using the helper.
    # Pass QUICTransport as a module-level reference so tests can monkeypatch it.
    transport_list = _build_transports_for_swarm(
        key_pair=key_pair,
        listen_addrs=listen_addrs,
        transports=transports,
        enable_quic=enable_quic,
        enable_tcp=enable_tcp,
        enable_websocket=enable_websocket,
        enable_autotls=enable_autotls,
        upgrader=upgrader,
        quic_config=quic_transport_opt,
        tls_client_config=tls_client_config,
        tls_server_config=tls_server_config,
        quic_class=QUICTransport,  # module-level ref; monkeypatching libp2p.QUICTransport works
    )
    logger.debug(
        "new_swarm: using transports: %s",
        [type(t).__name__ for t in transport_list],
    )

    peerstore = peerstore_opt or PeerStore()
    # Store our key pair in peerstore
    peerstore.add_key_pair(id_opt, key_pair)

    # ---- Detect shared-port TCP+WS addresses and build PortDemultiplexer ----
    # Mirrors go-libp2p: sharedTCP *tcpreuse.PortDemultiplexer is passed at transport
    # construction time.  When the listen_addrs include both a plain TCP and a
    # WebSocket address on the SAME port, we create one PortDemultiplexer so they share
    # the OS socket (EADDRINUSE prevention).
    port_demux = None
    port_demuxers: dict[tuple[str, int], PortDemultiplexer] = {}
    if listen_addrs:
        from libp2p.transport.cmux import PortDemultiplexer as _ConnMgr

        # Map (host, port) -> list of protocol-stacks that share that port.
        port_protos: dict[tuple[str, int], list[set[str]]] = {}
        for addr in listen_addrs:
            try:
                protos = {p.name for p in addr.protocols()}
                if "tcp" not in protos:
                    continue  # only TCP-based addrs can share
                host_val = (
                    addr.value_for_protocol("ip4")
                    or addr.value_for_protocol("ip6")
                )
                port_val = addr.value_for_protocol("tcp")
                if host_val is None or port_val is None:
                    continue
                key = (str(host_val), int(port_val))
                port_protos.setdefault(key, []).append(protos)
            except Exception:
                continue

        # A PortDemultiplexer is needed when a port has BOTH plain-TCP and WS/WSS addrs.
        for (host, port), proto_sets in port_protos.items():
            has_plain_tcp = any(
                "ws" not in ps and "wss" not in ps for ps in proto_sets
            )
            has_ws = any("ws" in ps or "wss" in ps for ps in proto_sets)
            if has_plain_tcp and has_ws:
                port_demuxers[(host, port)] = _ConnMgr(host, port)
                logger.debug(
                    "new_swarm: created PortDemultiplexer for shared port %s:%d",
                    host,
                    port,
                )

    from libp2p.transport.manager import TransportManager

    transport_manager = TransportManager(port_demuxers=port_demuxers)

    swarm = Swarm(
        id_opt,
        peerstore,
        upgrader,
        transports=transport_list,  # NEW: list instead of single transport
        retry_config=retry_config,
        connection_config=connection_config,
        psk=psk,
        transport_manager=transport_manager,
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
    enable_webrtc: bool = False,
    quic_transport_opt: QUICTransportConfig | None = None,
    tls_client_config: ssl.SSLContext | None = None,
    tls_server_config: ssl.SSLContext | None = None,
    resource_manager: ResourceManager | None = None,
    psk: str | None = None,
    bootstrap_allow_ipv6: bool = False,
    bootstrap_dns_timeout: float = 10.0,
    bootstrap_dns_max_retries: int = 3,
    connection_config: ConnectionConfig | None = None,
    announce_addrs: Sequence[multiaddr.Multiaddr] | None = None,
    # NEW: explicit transport list — highest priority
    transports: Sequence[ITransport] | None = None,
    # NEW: convenience flags
    enable_tcp: bool = True,
    enable_websocket: bool = False,
    enable_relay: bool = True,
) -> IHost:
    """
    Create a new libp2p host based on the given parameters.

    The host can listen on and dial over multiple transports simultaneously
    (TCP, WebSocket, QUIC), mirroring go-libp2p's architecture.

    Transport selection priority (highest to lowest):

    1. ``transports`` — explicit list, used as-is.
    2. ``listen_addrs`` inspection — all addresses are inspected.
    3. ``enable_*`` flags.
    4. Default: TCP only.

    :param key_pair: optional choice of the ``KeyPair``
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param disc_opt: optional discovery
    :param muxer_preference: optional explicit muxer preference
    :param listen_addrs: optional list of multiaddrs to listen on.  **All**
        addresses are inspected to determine which transports to create.
    :param enable_mDNS: whether to enable mDNS discovery
    :param bootstrap: optional list of bootstrap peer addresses as strings
    :param enable_quic: optional choice to use QUIC for transport
    :param enable_autotls: optional choice to use AutoTLS for security
    :param quic_transport_opt: optional configuration for quic transport
    :param tls_client_config: optional TLS client configuration for WebSocket transport
    :param tls_server_config: optional TLS server configuration for WebSocket transport
    :param resource_manager: optional resource manager for connection/stream limits
    :type resource_manager: :class:`libp2p.rcmgr.ResourceManager` or None
    :param psk: optional pre-shared key (PSK)
    :param bootstrap_allow_ipv6: if True, bootstrap accepts IPv6+TCP addresses
    :param bootstrap_dns_timeout: DNS resolution timeout in seconds per attempt
    :param bootstrap_dns_max_retries: max DNS resolution retries with backoff
    :param connection_config: optional connection configuration for connection manager
    :param announce_addrs: if set, these replace listen addrs in get_addrs()
    :param transports: explicit list of transport instances to register.  When
        provided, all ``enable_*`` flags and ``listen_addrs``-based detection
        are bypassed.
    :param enable_tcp: include a TCP transport when auto-building (default True).
    :param enable_websocket: include a WebSocket transport when auto-building.
    :return: return a host instance
    """

    if not enable_quic and quic_transport_opt is not None:
        logger.warning("QUIC config provided but QUIC not enabled, ignoring QUIC config")

    # Enable automatic protection by default: if no resource manager is supplied,
    # create a default instance so connections/streams are guarded out of the box.
    if resource_manager is None:
        try:
            from libp2p.rcmgr import new_resource_manager as _new_rm

            resource_manager = _new_rm()
        except Exception:
            # Fallback to leaving it None if creation fails for any reason.
            resource_manager = None

    # Determine the connection config to use.
    # QUIC transport config takes precedence if QUIC is enabled.
    effective_config: ConnectionConfig | QUICTransportConfig | None
    if enable_quic and quic_transport_opt is not None:
        effective_config = quic_transport_opt
    else:
        effective_config = connection_config

    swarm = new_swarm(
        enable_quic=enable_quic,
        enable_webrtc=enable_webrtc,
        key_pair=key_pair,
        muxer_opt=muxer_opt,
        sec_opt=sec_opt,
        peerstore_opt=peerstore_opt,
        enable_autotls=enable_autotls,
        muxer_preference=muxer_preference,
        listen_addrs=listen_addrs,
        connection_config=effective_config,
        tls_client_config=tls_client_config,
        tls_server_config=tls_server_config,
        resource_manager=resource_manager,
        psk=psk,
        # NEW: forward multi-transport params
        transports=transports,
        enable_tcp=enable_tcp,
        enable_websocket=enable_websocket,
    )

    if disc_opt is not None:
        host: IHost = RoutedHost(
            network=swarm,
            router=disc_opt,
            enable_mDNS=enable_mDNS,
            enable_upnp=enable_upnp,
            bootstrap=bootstrap,
            resource_manager=resource_manager,
            bootstrap_allow_ipv6=bootstrap_allow_ipv6,
            bootstrap_dns_timeout=bootstrap_dns_timeout,
            bootstrap_dns_max_retries=bootstrap_dns_max_retries,
            announce_addrs=announce_addrs,
        )
    else:
        host = BasicHost(
            network=swarm,
            enable_mDNS=enable_mDNS,
            bootstrap=bootstrap,
            enable_upnp=enable_upnp,
            negotiate_timeout=negotiate_timeout,
            resource_manager=resource_manager,
            bootstrap_allow_ipv6=bootstrap_allow_ipv6,
            bootstrap_dns_timeout=bootstrap_dns_timeout,
            bootstrap_dns_max_retries=bootstrap_dns_max_retries,
            announce_addrs=announce_addrs,
        )

    if enable_relay:
        from libp2p.relay.circuit_v2.transport import CircuitV2Transport
        from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
        from libp2p.relay.circuit_v2.config import RelayConfig
        from libp2p.network.swarm import Swarm
        from typing import cast

        config = RelayConfig()
        protocol = CircuitV2Protocol(host, config.limits)
        transport = CircuitV2Transport(host, protocol, config)
        cast(Swarm, swarm).transport_manager.add_transport(transport)

    return host


__version__ = __version("libp2p")
