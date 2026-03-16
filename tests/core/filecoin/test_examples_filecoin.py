import ast
import inspect

from examples.filecoin import (
    filecoin_connect_demo as connect_demo,
    filecoin_ping_identify_demo as ping_identify_demo,
    filecoin_pubsub_demo as pubsub_demo,
)


def test_filecoin_connect_demo_parser_defaults() -> None:
    parser = connect_demo.build_parser()
    args = parser.parse_args([])
    assert args.network == "mainnet"
    assert args.peer is None
    assert args.resolve_dns is True
    assert args.timeout == 10.0
    assert args.json is False


def test_filecoin_ping_identify_demo_parser_defaults() -> None:
    parser = ping_identify_demo.build_parser()
    args = parser.parse_args([])
    assert args.network == "mainnet"
    assert args.peer is None
    assert args.resolve_dns is True
    assert args.timeout == 10.0
    assert args.ping_count == 3
    assert args.json is False


def test_filecoin_pubsub_demo_parser_defaults() -> None:
    parser = pubsub_demo.build_parser()
    args = parser.parse_args([])
    assert args.network == "mainnet"
    assert args.resolve_dns is True
    assert args.include_quic is False
    assert args.seconds == 20.0
    assert args.max_messages is None
    assert args.topic == "both"
    assert args.json is False


def test_connect_demo_json_payload_shape() -> None:
    payload = connect_demo._build_result(
        network_alias="mainnet",
        network_name="testnetnet",
        attempted=3,
        connected=True,
        address="/ip4/127.0.0.1/tcp/1234/p2p/12D3KooW...",
        peer_id="12D3KooW...",
        connection={
            "transport_family": "tcp",
            "transport_addresses": ["/ip4/127.0.0.1/tcp/1234"],
            "connection_type": "direct",
            "security_protocol": "/noise",
            "muxer_protocol": "/yamux/1.0.0",
        },
        interop={
            "case": "public_filecoin_bootstrap_connect",
            "workflow": "runtime_bootstrap_smoke",
            "result": "pass",
            "failure_mode": None,
        },
        error=None,
    )
    assert set(payload.keys()) == {
        "network_alias",
        "network_name",
        "attempted",
        "connected",
        "address",
        "peer_id",
        "connection",
        "interop",
        "error",
    }


def test_ping_identify_demo_json_payload_shape() -> None:
    payload = ping_identify_demo._build_result(
        network_alias="calibnet",
        network_name="calibrationnet",
        connected=True,
        address="/ip4/127.0.0.1/tcp/9999/p2p/12D3KooW...",
        peer_id="12D3KooW...",
        connection={
            "transport_family": "tcp",
            "transport_addresses": ["/ip4/127.0.0.1/tcp/9999"],
            "connection_type": "direct",
            "security_protocol": "/noise",
            "muxer_protocol": "/yamux/1.0.0",
        },
        identify={
            "agent_version": "lotus/1.35.0",
            "protocol_version": "ipfs/0.1.0",
            "protocol_count": 8,
            "advertised_filecoin_protocols": [
                "/fil/hello/1.0.0",
                "/fil/chain/xchg/0.0.1",
            ],
            "supports_filecoin_hello": True,
            "supports_filecoin_chain_exchange": True,
        },
        ping={"count": 3, "rtts_us": [100, 110, 120], "avg_rtt_us": 110},
        interop={
            "case": "public_filecoin_ping_identify",
            "workflow": "runtime_bootstrap_smoke",
            "result": "pass",
            "failure_mode": None,
        },
        error=None,
    )
    assert set(payload.keys()) == {
        "network_alias",
        "network_name",
        "connected",
        "address",
        "peer_id",
        "connection",
        "identify",
        "ping",
        "interop",
        "error",
    }
    assert set(payload["identify"].keys()) == {
        "agent_version",
        "protocol_version",
        "protocol_count",
        "advertised_filecoin_protocols",
        "supports_filecoin_hello",
        "supports_filecoin_chain_exchange",
    }
    assert set(payload["ping"].keys()) == {"count", "rtts_us", "avg_rtt_us"}


def test_pubsub_demo_json_payload_shape() -> None:
    payload = pubsub_demo._build_snapshot(
        network_alias="mainnet",
        network_name="testnetnet",
        bootstrap_addrs=["/ip4/127.0.0.1/tcp/1234/p2p/12D3KooW..."],
        listen_port=0,
        topics=["/fil/blocks/testnetnet", "/fil/msgs/testnetnet"],
        max_messages=25,
    )
    assert payload["mode"] == "read_only_observer"
    assert payload["topics"]["selected"] == [
        "/fil/blocks/testnetnet",
        "/fil/msgs/testnetnet",
    ]
    assert payload["max_messages"] == 25
    assert payload["interop"]["case"] == "filecoin_read_only_gossipsub_observer"
    assert payload["interop"]["result"] == "partial"
    assert payload["interop"]["expected_failure_modes"]


def test_pubsub_observer_demo_has_no_publish_call_path() -> None:
    module_ast = ast.parse(inspect.getsource(pubsub_demo))

    for node in ast.walk(module_ast):
        if isinstance(node, ast.Attribute) and node.attr == "publish":
            raise AssertionError("pubsub observer demo must not call publish")
