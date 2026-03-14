import base64
import types
from typing import Any, cast

import pytest
from aiortc import RTCIceCandidate, RTCSessionDescription
from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option, generate_peer_id_from
from libp2p.abc import ConnectionType, IMuxedConn, IMuxedStream, ISecureConn
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.secp256k1 import create_new_key_pair as create_secp256k1_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.network.swarm import Swarm
from libp2p.network.transport_manager import TransportManager
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.security.security_multistream import SecurityMultistream
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.webrtc.private_to_public import connect as connect_module
from libp2p.transport.webrtc.private_to_public.connect import connect
from libp2p.transport.webrtc.private_to_public.transport import WebRTCDirectTransport
from libp2p.transport.webrtc.private_to_public.util import fingerprint_to_certhash


def fingerprint_components() -> tuple[str, str]:
    bytes_seq = bytes(range(32))
    hex_str = ":".join(f"{b:02X}" for b in bytes_seq)
    return hex_str, f"sha-256 {hex_str}"


def build_multiaddr(peer_id: ID, fingerprint: str) -> tuple[Multiaddr, str]:
    certhash = fingerprint_to_certhash(fingerprint)
    maddr = Multiaddr(
        f"/ip4/127.0.0.1/udp/12345/webrtc-direct/certhash/{certhash}/p2p/{peer_id}"
    )
    return maddr, certhash


def new_peer_id() -> ID:
    return generate_peer_id_from(create_new_key_pair())


class MockMuxedConn(IMuxedConn):
    """Valid mock muxed connection with all required attributes."""

    def __init__(self, peer_id: ID):
        self.peer_id = peer_id
        self._closed = False
        self._streams: list[IMuxedStream] = []
        self.event_started = trio.Event()
        self._is_initiator = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def is_initiator(self) -> bool:
        return self._is_initiator

    async def start(self) -> None:
        self.event_started.set()

    async def close(self) -> None:
        self._closed = True

    async def open_stream(self) -> IMuxedStream:
        from unittest.mock import Mock

        stream = Mock(spec=IMuxedStream)
        self._streams.append(stream)
        return stream

    async def accept_stream(self) -> IMuxedStream:
        from unittest.mock import Mock

        stream = Mock(spec=IMuxedStream)
        self._streams.append(stream)
        return stream

    def get_streams(self) -> tuple[IMuxedStream, ...]:
        return tuple(self._streams)

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.DIRECT


class StubChannel:
    readyState = "open"

    def on(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class StubRTCPeerConnection:
    def __init__(self) -> None:
        self.localDescription = RTCSessionDescription(sdp="", type="offer")
        self.remoteDescription = RTCSessionDescription(sdp="", type="answer")
        self._callbacks: dict[str, list[Any]] = {}
        self.iceCandidates: list[RTCIceCandidate] = []

    def createDataChannel(self, *_args: Any, **_kwargs: Any) -> StubChannel:
        return StubChannel()

    def on(self, event: str, callback: Any) -> None:
        self._callbacks.setdefault(event, []).append(callback)


class StubDirectPeerConnection:
    def __init__(self, local_fp_full: str, remote_fp_full: str) -> None:
        self._local_fp_full = local_fp_full
        self._remote_fp_full = remote_fp_full
        self._local_fp_hex = local_fp_full.split(" ", 1)[1]
        self._remote_fp_hex = remote_fp_full.split(" ", 1)[1]
        self.peer_connection = StubRTCPeerConnection()
        self.localDescription = RTCSessionDescription(sdp="", type="offer")
        self.remoteDescription = RTCSessionDescription(sdp="", type="answer")
        self.iceGatheringState = "complete"
        self.iceConnectionState = "connected"
        self.connectionState = "connected"
        self.iceCandidates: list[RTCIceCandidate] = []

    async def createOffer(self) -> Any:
        desc = RTCSessionDescription(
            sdp=f"v=0\r\na=fingerprint:{self._local_fp_full}\r\n", type="offer"
        )
        self.localDescription = desc
        self.peer_connection.localDescription = desc
        return desc

    async def createAnswer(self) -> Any:
        desc = RTCSessionDescription(
            sdp=f"v=0\r\na=fingerprint:{self._remote_fp_full}\r\n", type="answer"
        )
        self.localDescription = desc
        self.peer_connection.localDescription = desc
        return desc

    async def setLocalDescription(self, desc: Any) -> None:
        self.localDescription = desc
        self.peer_connection.localDescription = desc

    async def setRemoteDescription(self, desc: Any) -> None:
        self.remoteDescription = desc
        self.peer_connection.remoteDescription = desc

    def remoteFingerprint(self) -> Any:
        return types.SimpleNamespace(algorithm="sha-256", value=self._remote_fp_hex)

    def createDataChannel(self, *args: Any, **kwargs: Any) -> StubChannel:
        return self.peer_connection.createDataChannel(*args, **kwargs)

    def on(self, event: str, callback: Any) -> None:
        self.peer_connection.on(event, callback)


def test_noise_transport_stores_prologue() -> None:
    key_pair = create_secp256k1_key_pair()
    transport = NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=create_secp256k1_key_pair().private_key,
    )
    prologue = b"custom-prologue"
    transport.set_prologue(prologue)
    pattern = transport.get_pattern()
    assert getattr(pattern, "prologue", None) == prologue


@pytest.mark.trio
async def test_connect_uses_security_multistream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_aio_as_trio(awaitable: Any) -> Any:
        return await awaitable

    monkeypatch.setattr(connect_module, "aio_as_trio", fake_aio_as_trio)

    def fake_munge_offer(sdp: str, _ufrag: str, _pwd: str) -> str:
        return sdp

    def fake_munge_answer(sdp: str, _ufrag: str) -> str:
        return sdp

    def fake_get_fingerprint(sdp: str | None) -> str | None:
        if sdp is None:
            return None
        for line in sdp.splitlines():
            line = line.strip()
            if line.startswith("a=fingerprint:"):
                fingerprint_part = line.split(":", 1)[1].strip()
                parts = fingerprint_part.split(" ", 1)
                if len(parts) == 2:
                    return parts[1].strip()
        return None

    monkeypatch.setattr(connect_module.SDP, "munge_offer", fake_munge_offer)
    if hasattr(connect_module.SDP, "munge_answer"):
        monkeypatch.setattr(connect_module.SDP, "munge_answer", fake_munge_answer)
    monkeypatch.setattr(
        connect_module.SDP, "get_fingerprint_from_sdp", fake_get_fingerprint
    )

    captured_prologue: dict[str, Any] = {}

    def fake_generate_noise_prologue(
        local_fp: str, remote_ma: Multiaddr, role: str
    ) -> bytes:
        captured_prologue["local_fp"] = local_fp
        captured_prologue["remote_ma"] = remote_ma
        captured_prologue["role"] = role
        return b"fake-prologue"

    monkeypatch.setattr(
        connect_module, "generate_noise_prologue", fake_generate_noise_prologue
    )

    _, local_fp_full = fingerprint_components()
    _, remote_fp_full = fingerprint_components()
    remote_peer_id = new_peer_id()

    remote_addr, _ = build_multiaddr(remote_peer_id, remote_fp_full)

    stub_peer = StubDirectPeerConnection(local_fp_full, remote_fp_full)

    async def offer_handler(_offer: Any, _ufrag: str) -> Any:
        return RTCSessionDescription(
            sdp=f"v=0\r\na=fingerprint:{remote_fp_full}\r\n", type="answer"
        )

    # Use real NoiseTransport and SecurityMultistream
    key_pair = create_new_key_pair()
    noise_key_pair = create_new_x25519_key_pair()
    noise_transport = NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=noise_key_pair.private_key,
    )

    # Create a mock secure connection to return from handshake
    class MockSecureConnFromHandshake(ISecureConn):
        def __init__(self, local_peer: ID, remote_peer: ID):
            self._local_peer = local_peer
            self._remote_peer = remote_peer
            self.closed = False
            self.remote_multiaddr = remote_addr
            self.local_fingerprint = local_fp_full.split(" ", 1)[1]
            self.remote_fingerprint = remote_fp_full.split(" ", 1)[1]
            self.remote_peer_id = remote_peer

        async def close(self) -> None:
            self.closed = True

        async def read(self, n: int | None = None) -> bytes:
            return b""

        async def write(self, data: bytes) -> None:
            pass

        def get_remote_address(self) -> tuple[str, int] | None:
            return None

        def get_local_peer(self) -> ID:
            return self._local_peer

        def get_local_private_key(self) -> PrivateKey:
            return key_pair.private_key

        def get_remote_peer(self) -> ID:
            return self._remote_peer

        def get_remote_public_key(self) -> PublicKey:
            return create_new_key_pair().public_key

        def get_transport_addresses(self) -> list[Multiaddr]:
            return [self.remote_multiaddr] if self.remote_multiaddr else []

        def get_connection_type(self) -> ConnectionType:
            return ConnectionType.DIRECT

    secure_inbound_called = False

    async def mock_secure_inbound(conn: Any) -> ISecureConn:
        nonlocal secure_inbound_called
        secure_inbound_called = True
        # Return a mock secure connection instead of performing real handshake
        return MockSecureConnFromHandshake(
            generate_peer_id_from(key_pair), remote_peer_id
        )

    noise_transport.secure_inbound = mock_secure_inbound  # type: ignore

    # Create real SecurityMultistream with Noise transport
    security_multistream = SecurityMultistream({NOISE_PROTOCOL_ID: noise_transport})

    secure_conn, _ = await connect(
        peer_connection=cast(Any, stub_peer),
        ufrag="testufrag",
        ice_pwd="testpassword1234567890test",
        role="client",
        remote_addr=remote_addr,
        remote_peer_id=remote_peer_id,
        offer_handler=offer_handler,
        security_multistream=security_multistream,
    )

    assert isinstance(secure_conn, ISecureConn)
    assert noise_transport._prologue == b"fake-prologue"
    assert captured_prologue["role"] == "client"
    assert secure_inbound_called, "secure_inbound should have been called"
    secure_conn_any = cast(Any, secure_conn)
    assert captured_prologue["remote_ma"] == getattr(
        secure_conn_any, "remote_multiaddr", None
    )
    assert captured_prologue["local_fp"] == (
        getattr(secure_conn_any, "local_fingerprint", None)
        or local_fp_full.split(" ", 1)[1]
    )


def test_fingerprint_to_certhash_matches_digest() -> None:
    hex_part, fp_full = fingerprint_components()
    certhash = fingerprint_to_certhash(fp_full)
    # The certhash format is: "u" (multibase prefix) + base64url(multihash_bytes)
    # where multihash_bytes = [0x12 (SHA-256 code), 0x20 (length), digest_bytes]
    digest_bytes = bytes.fromhex(hex_part.replace(":", ""))
    multihash_bytes = (
        bytes([0x12, 0x20]) + digest_bytes
    )  # SHA-256 code + length + digest
    expected = (
        "u"  # multibase prefix for base64url
        + base64.urlsafe_b64encode(multihash_bytes).decode("utf-8").rstrip("=")
    )
    assert certhash == expected


@pytest.mark.trio
async def test_transport_manager_skips_security_for_secure_conn() -> None:
    key_pair = create_new_key_pair()
    local_peer = generate_peer_id_from(key_pair)
    remote_peer = new_peer_id()
    noise_key_pair = create_new_x25519_key_pair()
    noise_transport = NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=noise_key_pair.private_key,
    )
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={NOISE_PROTOCOL_ID: noise_transport},
        muxer_transports_by_protocol=create_yamux_muxer_option(),
    )
    peerstore = PeerStore()
    peerstore.add_key_pair(local_peer, key_pair)

    class StubTransport:
        def __init__(self, secure_conn: ISecureConn):
            self.secure_conn = secure_conn

        def set_host(self, _host: Any) -> None:
            return None

        def is_started(self) -> bool:
            return True

        async def dial(self, _maddr: Multiaddr) -> ISecureConn:
            return self.secure_conn

        def can_handle(self, _maddr: Multiaddr) -> bool:
            return True

        def create_listener(self, _handler: Any) -> Any:
            raise NotImplementedError

    # Create a minimal secure connection for testing
    # We'll use a real Noise secure connection by creating a mock raw connection
    # and performing handshake, but for simplicity in this test, we'll just verify
    # that the transport manager skips security upgrade when given ISecureConn

    class MockSecureConn(ISecureConn):
        def __init__(self, local_peer: ID, remote_peer: ID):
            self._local_peer = local_peer
            self._remote_peer = remote_peer
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        async def read(self, n: int | None = None) -> bytes:
            return b""

        async def write(self, data: bytes) -> None:
            pass

        def get_remote_address(self) -> tuple[str, int] | None:
            return None

        def get_local_peer(self) -> ID:
            return self._local_peer

        def get_local_private_key(self) -> PrivateKey:
            return create_new_key_pair().private_key

        def get_remote_peer(self) -> ID:
            return self._remote_peer

        def get_remote_public_key(self) -> PublicKey:
            return create_new_key_pair().public_key

        def get_transport_addresses(self) -> list[Multiaddr]:
            return []

        def get_connection_type(self) -> ConnectionType:
            return ConnectionType.DIRECT

    secure_conn = MockSecureConn(local_peer, remote_peer)
    transport = StubTransport(secure_conn)

    swarm = Swarm(
        local_peer,
        peerstore,
        upgrader,
        transport,  # type: ignore
        retry_config=None,
        connection_config=None,
    )

    manager = TransportManager(host=None, swarm=swarm)
    manager.register_transport("custom", cast(Any, transport))

    maddr = Multiaddr(f"/ip4/127.0.0.1/tcp/15000/p2p/{remote_peer.to_base58()}")

    original_upgrade_security = swarm.upgrader.upgrade_security
    security_called = False

    async def track_upgrade_security(*args: Any, **kwargs: Any) -> ISecureConn:
        nonlocal security_called
        security_called = True
        return await original_upgrade_security(*args, **kwargs)

    swarm.upgrader.upgrade_security = track_upgrade_security  # type: ignore
    connection_called = False
    connection_arg = None
    mock_muxed = MockMuxedConn(remote_peer)

    async def track_upgrade_connection(*args: Any, **kwargs: Any) -> Any:
        nonlocal connection_called, connection_arg
        connection_called = True
        connection_arg = args[0] if args else None
        # Return mock muxed connection instead of trying to negotiate
        # This avoids the need for actual muxer negotiation which requires
        # a working connection that can read/write
        return mock_muxed

    swarm.upgrader.upgrade_connection = track_upgrade_connection  # type: ignore

    # Track if add_conn was called
    add_conn_called_with = None

    async def mock_add_conn(muxed_conn: Any) -> Any:
        nonlocal add_conn_called_with
        add_conn_called_with = muxed_conn

        # Return a simple mock network connection
        class MockNetConn:
            def __init__(self, muxed_conn: Any):
                self.muxed_conn = muxed_conn

        return MockNetConn(muxed_conn)

    swarm.add_conn = mock_add_conn  # type: ignore

    muxed = await manager.dial(maddr)

    assert security_called is False, (
        "Security upgrade should be skipped for ISecureConn"
    )
    assert connection_called is True, "Connection upgrade should be called"
    assert connection_arg is secure_conn, (
        "Connection upgrade should receive the secure connection"
    )
    assert add_conn_called_with is mock_muxed, (
        "add_conn should be called with muxed connection"
    )
    assert muxed is not None, "dial should return a network connection"


@pytest.mark.trio
async def test_register_incoming_connection_accepts_presecured_conn() -> None:
    transport = WebRTCDirectTransport()
    key_pair = create_new_key_pair()
    local_peer = generate_peer_id_from(key_pair)
    remote_peer = new_peer_id()
    noise_key_pair = create_new_x25519_key_pair()
    noise_transport = NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=noise_key_pair.private_key,
    )

    upgrader = TransportUpgrader(
        secure_transports_by_protocol={NOISE_PROTOCOL_ID: noise_transport},
        muxer_transports_by_protocol=create_yamux_muxer_option(),
    )

    peerstore = PeerStore()
    peerstore.add_key_pair(local_peer, key_pair)

    swarm = Swarm(
        local_peer,
        peerstore,
        upgrader,
        transport,  # type: ignore
        retry_config=None,
        connection_config=None,
    )

    class Host:
        def get_network(self) -> Swarm:
            return swarm

        def get_peerstore(self):
            return peerstore

    transport.host = cast(Any, Host())

    # Create a minimal secure connection
    class MockSecureConn(ISecureConn):
        def __init__(self, local_peer: ID, remote_peer: ID):
            self._local_peer = local_peer
            self._remote_peer = remote_peer
            self.remote_peer_id = remote_peer
            self.closed = False

        async def close(self) -> None:
            self.closed = True

        async def read(self, n: int | None = None) -> bytes:
            return b""

        async def write(self, data: bytes) -> None:
            pass

        def get_remote_address(self) -> tuple[str, int] | None:
            return None

        def get_local_peer(self) -> ID:
            return self._local_peer

        def get_local_private_key(self) -> PrivateKey:
            return create_new_key_pair().private_key

        def get_remote_peer(self) -> ID:
            return self._remote_peer

        def get_remote_public_key(self) -> PublicKey:
            return create_new_key_pair().public_key

        def get_transport_addresses(self) -> list[Multiaddr]:
            return []

        def get_connection_type(self) -> ConnectionType:
            return ConnectionType.DIRECT

    secure_conn = MockSecureConn(local_peer, remote_peer)
    secure_conn.remote_peer_id = remote_peer

    # Track if security upgrade was called
    original_upgrade_security = swarm.upgrader.upgrade_security
    security_called = False

    async def track_upgrade_security(*args: Any, **kwargs: Any) -> ISecureConn:
        nonlocal security_called
        security_called = True
        return await original_upgrade_security(*args, **kwargs)

    swarm.upgrader.upgrade_security = track_upgrade_security  # type: ignore
    connection_called = False

    # Create a mock muxed connection for the upgrade
    mock_muxed = MockMuxedConn(remote_peer)

    async def track_upgrade_connection(*args: Any, **kwargs: Any) -> Any:
        nonlocal connection_called
        connection_called = True
        return mock_muxed

    swarm.upgrader.upgrade_connection = track_upgrade_connection  # type: ignore

    # Mock add_conn to avoid needing to start the swarm
    async def mock_add_conn(muxed_conn: Any) -> Any:
        class MockNetConn:
            def __init__(self, muxed_conn: Any):
                self.muxed_conn = muxed_conn

        return MockNetConn(muxed_conn)

    swarm.add_conn = mock_add_conn  # type: ignore

    await transport.register_incoming_connection(secure_conn)

    assert security_called is False, (
        "Security upgrade should be skipped for presecured connection"
    )
    assert connection_called is True, "Connection upgrade should be called"
    assert transport.active_connections[str(remote_peer)] is secure_conn
