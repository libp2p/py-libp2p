import json
from pathlib import Path

from multiaddr import Multiaddr

from libp2p.filecoin.interop import (
    extract_connection_metadata,
    transport_family_for_addrs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "filecoin_network_parity_and_interop.rst"
ARTIFACT_PATH = (
    REPO_ROOT / "artifacts" / "filecoin" / "network_parity_and_interop.v1.json"
)

REQUIRED_AUDIT_ROWS = {
    "listen_addresses",
    "transport_stack",
    "security_stack_order",
    "muxer_defaults",
    "ping_identify_host_defaults",
    "connection_manager_thresholds",
    "resource_manager_defaults",
    "bootstrap_protection",
    "discovery_stack",
    "idle_connection_and_redial",
    "request_response_stream_concurrency",
    "peer_protection_and_bans",
    "dht_protocol_and_filters",
    "pubsub_peer_scoring_note",
}

REQUIRED_INTEROP_CASES = {
    "public_filecoin_bootstrap_connect",
    "public_filecoin_ping_identify",
    "lotus_identify_ping_tcp",
    "forest_identify_ping_tcp",
    "lotus_protocol_advertisement",
    "forest_protocol_advertisement",
    "filecoin_read_only_gossipsub_observer",
    "hello_runtime_exchange",
    "chain_exchange_request_response",
}

REQUIRED_HEADINGS = [
    "Scope and evidence",
    "Network parity audit",
    "Preferred controlled workflow",
    "Secondary public-network smoke workflow",
    "Interoperability matrix",
    "Current gaps and expected failure modes",
]


class _DummyConn:
    def get_interop_metadata(self) -> dict[str, object]:
        return {
            "transport_family": "tcp",
            "transport_addresses": ["/ip4/127.0.0.1/tcp/4001"],
            "connection_type": "direct",
            "security_protocol": "/noise",
            "muxer_protocol": "/yamux/1.0.0",
        }


class _DummyNetwork:
    def get_connections(self, peer_id: object) -> list[object]:
        return [_DummyConn()]


class _DummyHost:
    def get_network(self) -> _DummyNetwork:
        return _DummyNetwork()


def _load_artifact() -> dict:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def _section_body(content: str, heading: str, next_heading: str | None) -> str:
    start = content.index(heading) + len(heading)
    end = content.index(next_heading, start) if next_heading else len(content)
    return content[start:end]


def test_network_parity_artifact_schema_and_enums() -> None:
    artifact = _load_artifact()
    assert artifact["meta"]["format"] == "filecoin_network_parity_and_interop.v1"
    assert artifact["meta"]["sources"]["lotus"]["version"] == "v1.35.0"
    assert artifact["meta"]["sources"]["forest"]["version"] == "0.32.2"
    assert artifact["meta"]["allowed_parity_statuses"] == [
        "aligned",
        "partial",
        "different",
        "out_of_scope",
    ]
    assert artifact["meta"]["allowed_interop_results"] == [
        "pass",
        "partial",
        "fail",
        "expected_gap",
    ]


def test_network_parity_artifact_has_required_rows() -> None:
    artifact = _load_artifact()
    assert {
        row["id"] for row in artifact["network_parity_audit"]
    } == REQUIRED_AUDIT_ROWS
    assert {row["id"] for row in artifact["interop_matrix"]} == REQUIRED_INTEROP_CASES


def test_network_parity_doc_has_required_sections_and_links() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")
    for heading in REQUIRED_HEADINGS:
        assert heading in content

    for index, heading in enumerate(REQUIRED_HEADINGS):
        next_heading = (
            REQUIRED_HEADINGS[index + 1] if index + 1 < len(REQUIRED_HEADINGS) else None
        )
        body = _section_body(content, heading, next_heading)
        assert "https://" in body, f"missing normative link in section: {heading}"


def test_transport_family_for_addrs_detects_tcp_and_quic() -> None:
    assert transport_family_for_addrs([Multiaddr("/ip4/127.0.0.1/tcp/4001")]) == "tcp"
    assert (
        transport_family_for_addrs([Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1")])
        == "quic-v1"
    )


def test_extract_connection_metadata_uses_interop_metadata_surface() -> None:
    metadata = extract_connection_metadata(_DummyHost(), "peer")
    assert metadata is not None
    assert metadata["transport_family"] == "tcp"
    assert metadata["muxer_protocol"] == "/yamux/1.0.0"
    assert metadata["connection_count"] == 1
