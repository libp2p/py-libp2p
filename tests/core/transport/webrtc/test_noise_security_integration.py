import types
from typing import Any, cast

import pytest
from aiortc import RTCSessionDescription
from multiaddr import Multiaddr

from libp2p import generate_peer_id_from
from libp2p.abc import IRawConnection, ISecureConn, ISecureTransport
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.secp256k1 import create_new_key_pair as create_secp256k1_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.transport.webrtc.private_to_public import connect as connect_module
from libp2p.transport.webrtc.private_to_public.connect import connect
from libp2p.transport.webrtc.private_to_public.transport import WebRTCDirectTransport
from libp2p.transport.webrtc.private_to_public.util import (
    fingerprint_to_certhash,
)


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


class StubChannel:
    readyState = "open"

    def on(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class StubRTCPeerConnection:
    def __init__(self) -> None:
        self.localDescription = None
        self.remoteDescription = None
        self._callbacks: dict[str, list[Any]] = {}

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

    async def createOffer(self) -> Any:
        return RTCSessionDescription(
            sdp=f"v=0\r\na=fingerprint:{self._local_fp_full}\r\n", type="offer"
        )

    async def createAnswer(self) -> Any:
        return RTCSessionDescription(
            sdp=f"v=0\r\na=fingerprint:{self._remote_fp_full}\r\n", type="answer"
        )

    async def setLocalDescription(self, desc: Any) -> None:
        self.peer_connection.localDescription = desc

    async def setRemoteDescription(self, desc: Any) -> None:
        self.peer_connection.remoteDescription = desc

    def remoteFingerprint(self) -> Any:
        return types.SimpleNamespace(algorithm="sha-256", value=self._remote_fp_hex)


class StubSecureConn(ISecureConn):
    def __init__(self, local_peer: ID, remote_peer: ID, initiator: bool) -> None:
        self._local_peer = local_peer
        self._local_private_key: PrivateKey = create_secp256k1_key_pair().private_key
        self._remote_peer = remote_peer
        self._remote_public_key: PublicKey = self._local_private_key.get_public_key()
        self.is_initiator = initiator
        self.remote_peer_id = remote_peer
        self.closed = False
        self.remote_multiaddr: Multiaddr | None = None
        self.remote_fingerprint: str | None = None
        self.local_fingerprint: str | None = None

    async def close(self) -> None:
        self.closed = True

    async def read(self, n: int | None = None) -> bytes:
        return b""

    async def write(self, data: bytes) -> None:
        return None

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    def get_local_peer(self) -> ID:
        return self._local_peer

    def get_local_private_key(self) -> PrivateKey:
        return self._local_private_key

    def get_remote_peer(self) -> ID:
        return self._remote_peer

    def get_remote_public_key(self) -> PublicKey:
        return self._remote_public_key


class StubSecurityTransport(ISecureTransport):
    def __init__(self, local_peer: ID) -> None:
        self.local_peer = local_peer
        self.prologue: bytes | None = None
        self.outbound_called = False
        self.inbound_called = False
        self.last_conn: IRawConnection | None = None
        self.last_peer: ID | None = None

    def set_prologue(self, prologue: bytes | None) -> None:
        self.prologue = prologue

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        self.outbound_called = True
        self.last_conn = conn
        self.last_peer = peer_id
        return StubSecureConn(self.local_peer, peer_id, initiator=True)

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        self.inbound_called = True
        self.last_conn = conn
        return StubSecureConn(self.local_peer, new_peer_id(), initiator=False)


class StubSecurityMultistream:
    def __init__(self, transport: StubSecurityTransport):
        self.transport = transport
        self.selected: tuple[IRawConnection, bool] | None = None

    async def select_transport(
        self, conn: IRawConnection, is_initiator: bool
    ) -> ISecureTransport:
        self.selected = (conn, is_initiator)
        return self.transport


class StubUpgrader:
    def __init__(self) -> None:
        self.security_called = False
        self.connection_called = False
        self.security_multistream = StubSecurityMultistream(
            StubSecurityTransport(new_peer_id())
        )
        self.muxed_conn = object()
        self.last_secure_conn: ISecureConn | None = None

    async def upgrade_security(self, *_args: Any, **_kwargs: Any) -> Any:
        self.security_called = True
        return StubSecureConn(new_peer_id(), new_peer_id(), initiator=True)

    async def upgrade_connection(self, conn: ISecureConn, _peer_id: ID) -> Any:
        self.connection_called = True
        self.last_secure_conn = conn
        return self.muxed_conn


class StubSwarm:
    def __init__(self) -> None:
        self.upgrader = StubUpgrader()
        self.add_conn_called_with = None

    async def add_conn(self, conn: Any) -> Any:
        self.add_conn_called_with = conn
        return conn


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

    def fake_munge_offer(sdp: str, _ufrag: str) -> str:
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

    transport = StubSecurityTransport(local_peer=remote_peer_id)
    security_multistream = StubSecurityMultistream(transport)

    secure_conn, _ = await connect(
        peer_connection=cast(Any, stub_peer),
        ufrag="testufrag",
        role="client",
        remote_addr=remote_addr,
        remote_peer_id=remote_peer_id,
        offer_handler=offer_handler,
        security_multistream=cast(Any, security_multistream),
    )

    assert transport.outbound_called is True
    assert isinstance(secure_conn, ISecureConn)
    assert transport.prologue == b"fake-prologue"
    assert captured_prologue["role"] == "client"
    secure_conn_any = cast(Any, secure_conn)
    assert captured_prologue["remote_ma"] == getattr(
        secure_conn_any, "remote_multiaddr", None
    )
    assert captured_prologue["local_fp"] == (
        getattr(secure_conn_any, "local_fingerprint", None)
        or local_fp_full.split(" ", 1)[1]
    )


@pytest.mark.trio
async def test_transport_manager_skips_security_for_secure_conn() -> None:
    from libp2p.network.transport_manager import TransportManager

    local_peer = new_peer_id()
    remote_peer = new_peer_id()
    secure_conn = StubSecureConn(local_peer, remote_peer, initiator=True)
    transport = StubTransport(secure_conn)

    swarm = StubSwarm()
    swarm.upgrader.security_multistream = StubSecurityMultistream(
        StubSecurityTransport(local_peer)
    )

    manager = TransportManager(host=None, swarm=swarm)
    manager.register_transport("custom", cast(Any, transport))

    maddr = Multiaddr(f"/ip4/127.0.0.1/tcp/15000/p2p/{remote_peer.to_base58()}")

    muxed = await manager.dial(maddr)

    assert muxed is swarm.upgrader.muxed_conn
    assert swarm.upgrader.security_called is False
    assert swarm.upgrader.connection_called is True
    assert swarm.add_conn_called_with is muxed


@pytest.mark.trio
async def test_register_incoming_connection_accepts_presecured_conn() -> None:
    transport = WebRTCDirectTransport()
    swarm = StubSwarm()
    swarm.upgrader.security_multistream = StubSecurityMultistream(
        StubSecurityTransport(new_peer_id())
    )

    class Host:
        def get_network(self) -> StubSwarm:
            return swarm

        def get_peerstore(self):
            return None

    transport.host = cast(Any, Host())

    local_peer = new_peer_id()
    remote_peer = new_peer_id()
    secure_conn = StubSecureConn(local_peer, remote_peer, initiator=False)
    secure_conn.remote_peer_id = remote_peer

    await transport.register_incoming_connection(secure_conn)

    assert swarm.upgrader.security_called is False
    assert swarm.upgrader.connection_called is True
    assert transport.active_connections[str(remote_peer)] is secure_conn
