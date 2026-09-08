"""Tests that QUICTransportConfig flow-control windows map onto aioquic."""

from __future__ import annotations

from aioquic.quic.configuration import QuicConfiguration

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.utils import (
    apply_flow_control_windows,
    create_client_config_from_base,
    create_server_config_from_base,
)


def test_apply_flow_control_windows_sets_aioquic_limits() -> None:
    cfg = QUICTransportConfig(
        STREAM_FLOW_CONTROL_WINDOW=256 * 1024,
        CONNECTION_FLOW_CONTROL_WINDOW=512 * 1024,
    )
    quic = QuicConfiguration(is_client=True)
    apply_flow_control_windows(quic, cfg)
    assert quic.max_stream_data == 256 * 1024
    assert quic.max_data == 512 * 1024


def test_create_server_and_client_configs_apply_flow_control() -> None:
    transport_cfg = QUICTransportConfig(
        STREAM_FLOW_CONTROL_WINDOW=128 * 1024,
        CONNECTION_FLOW_CONTROL_WINDOW=256 * 1024,
    )
    base = QuicConfiguration(is_client=False, alpn_protocols=["libp2p"])
    server = create_server_config_from_base(base, transport_config=transport_cfg)
    client = create_client_config_from_base(
        QuicConfiguration(is_client=True, alpn_protocols=["libp2p"]),
        transport_config=transport_cfg,
    )
    assert server.max_stream_data == 128 * 1024
    assert server.max_data == 256 * 1024
    assert client.max_stream_data == 128 * 1024
    assert client.max_data == 256 * 1024


def test_quic_transport_setup_applies_flow_control_to_stored_configs() -> None:
    key_pair = create_new_key_pair()
    transport_cfg = QUICTransportConfig(
        STREAM_FLOW_CONTROL_WINDOW=192 * 1024,
        CONNECTION_FLOW_CONTROL_WINDOW=384 * 1024,
    )
    transport = QUICTransport(private_key=key_pair.private_key, config=transport_cfg)
    for protocol, quic_cfg in transport._quic_configs.items():
        assert quic_cfg.max_stream_data == 192 * 1024, protocol
        assert quic_cfg.max_data == 384 * 1024, protocol
