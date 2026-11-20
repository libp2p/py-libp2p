"""Rotation history and diagnostic histograms must not grow for connection life."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from aioquic.quic import events
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from multiaddr import Multiaddr
import trio

from libp2p.peer.id import ID
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.connection_id_registry import ConnectionIDRegistry


@pytest.mark.trio
async def test_connection_keeps_only_bounded_recent_cid_history(monkeypatch):
    transport: Any = SimpleNamespace(_config=QUICTransportConfig())
    conn = QUICConnection(
        QuicConnection(configuration=QuicConfiguration(is_client=True)),
        ("127.0.0.1", 4001),
        ID(b"peer"),
        ID(b"local"),
        True,
        Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"),
        transport,
    )

    async def notify(*args):
        pass

    monkeypatch.setattr(conn, "_notify_listener_of_new_connection_id", notify)
    await conn._handle_connection_id_issued(events.ConnectionIdIssued(b"anchor"))
    for i in range(5000):
        cid = i.to_bytes(8, "big")
        await conn._handle_connection_id_issued(events.ConnectionIdIssued(cid))
        await conn._handle_connection_id_retired(events.ConnectionIdRetired(cid))
    assert conn._available_connection_ids == {b"anchor"}
    assert conn.get_current_connection_id() == b"anchor"
    assert conn._stats["connection_ids_issued"] == 5001
    assert conn._stats["connection_ids_retired"] == 5000
    assert len(conn._retired_connection_ids) <= 128
    assert len(conn._connection_id_sequence_numbers) <= 128


@pytest.mark.trio
async def test_registry_histogram_does_not_keep_every_lifetime_sequence():
    registry = ConnectionIDRegistry(trio.Lock())
    conn = Mock()
    conn._remote_addr = ("127.0.0.1", 4001)
    for sequence in range(2000):
        cid = sequence.to_bytes(8, "big")
        await registry.register_connection(cid, conn, conn._remote_addr, sequence)
        await registry.unregister_connection_object(conn)
    stats = registry.get_stats()
    assert stats["total_connection_ids"] == 0
    distribution = stats["sequence_distribution"]
    assert isinstance(distribution, dict)
    assert len(distribution) <= 129
    assert sum(distribution.values()) == 2000
