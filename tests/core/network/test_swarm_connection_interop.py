from typing import cast

from multiaddr import Multiaddr

from libp2p.abc import (
    ConnectionType,
    IMuxedConn,
)
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.swarm import Swarm


class _DummyMuxedConn:
    peer_id = "peer"
    is_closed = False
    negotiated_security_protocol: str | None = None
    negotiated_muxer_protocol: str | None = None

    async def close(self) -> None:
        return None

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.DIRECT


class _DummySwarm:
    def __init__(self) -> None:
        self.peerstore = None

    def remove_conn(self, conn) -> None:
        return None

    async def notify_disconnected(self, conn) -> None:
        return None

    async def notify_opened_stream(self, stream) -> None:
        return None

    async def notify_closed_stream(self, stream) -> None:
        return None

    async def common_stream_handler(self, stream) -> None:
        return None


def test_swarm_connection_interop_metadata_for_tcp() -> None:
    conn = SwarmConn(
        cast(IMuxedConn, _DummyMuxedConn()),
        cast(Swarm, _DummySwarm()),
    )
    conn.set_transport_info(
        [Multiaddr("/ip4/127.0.0.1/tcp/4001")], ConnectionType.DIRECT
    )
    conn.set_negotiated_protocols("/noise", "/yamux/1.0.0")

    metadata = conn.get_interop_metadata()

    assert metadata["transport_family"] == "tcp"
    assert metadata["security_protocol"] == "/noise"
    assert metadata["muxer_protocol"] == "/yamux/1.0.0"
    assert metadata["connection_type"] == "direct"


def test_swarm_connection_interop_metadata_for_quic() -> None:
    conn = SwarmConn(
        cast(IMuxedConn, _DummyMuxedConn()),
        cast(Swarm, _DummySwarm()),
    )
    conn.set_transport_info(
        [Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1")],
        ConnectionType.DIRECT,
    )
    conn.set_negotiated_protocols("quic-tls", None)

    metadata = conn.get_interop_metadata()

    assert metadata["transport_family"] == "quic-v1"
    assert metadata["security_protocol"] == "quic-tls"
    assert metadata["muxer_protocol"] == "n/a"


def test_swarm_connection_interop_metadata_falls_back_to_muxed_conn() -> None:
    dummy_conn = _DummyMuxedConn()
    dummy_conn.negotiated_security_protocol = "/noise"
    dummy_conn.negotiated_muxer_protocol = "/yamux/1.0.0"

    conn = SwarmConn(
        cast(IMuxedConn, dummy_conn),
        cast(Swarm, _DummySwarm()),
    )
    conn.set_transport_info(
        [Multiaddr("/ip4/127.0.0.1/tcp/4001")], ConnectionType.DIRECT
    )

    metadata = conn.get_interop_metadata()

    assert metadata["security_protocol"] == "/noise"
    assert metadata["muxer_protocol"] == "/yamux/1.0.0"


def test_swarm_connection_interop_metadata_infers_direct_from_addrs() -> None:
    conn = SwarmConn(
        cast(IMuxedConn, _DummyMuxedConn()),
        cast(Swarm, _DummySwarm()),
    )
    conn.set_transport_info(
        [Multiaddr("/ip4/127.0.0.1/tcp/4001")],
        ConnectionType.UNKNOWN,
    )

    metadata = conn.get_interop_metadata()

    assert metadata["connection_type"] == "direct"
