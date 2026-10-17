import json
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "filecoin_protocol_support_matrix.rst"
ARTIFACT_PATH = REPO_ROOT / "artifacts" / "filecoin" / "protocol_support_matrix.v1.json"

REQUIRED_SECTION_HEADINGS = [
    "Summary matrix",
    "Core diagnostics surfaces",
    "Filecoin request/response protocols",
    "Filecoin pubsub compatibility",
    "Out-of-scope note",
    "Roadmap priorities",
]

REQUIRED_ROW_LABELS = [
    "Identify",
    "Ping",
    "Hello protocol ID",
    "Hello runtime / wire behavior",
    "Chain exchange protocol ID",
    "Chain exchange request/response behavior",
    "Gossipsub protocol negotiation",
    "Filecoin topic naming",
    "Filecoin message ID function",
    "Score thresholds",
    "Full topic scoring parity",
    "Bootstrapper / PX / direct-peer behavior",
    "Drand / F3 topic handling",
    "Bitswap note",
]

ALLOWED_STATUSES = {"implemented", "partial", "missing", "out_of_scope"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}


def _section_body(content: str, heading: str, next_heading: str | None) -> str:
    start = content.index(heading) + len(heading)
    end = content.index(next_heading, start) if next_heading else len(content)
    return content[start:end]


def _load_artifact() -> dict:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_protocol_support_doc_has_required_sections_and_rows() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    for heading in REQUIRED_SECTION_HEADINGS:
        assert heading in content

    for row in REQUIRED_ROW_LABELS:
        assert row in content


def test_protocol_support_doc_uses_allowed_status_and_priority_values() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    statuses = set(re.findall(r"- Status: ``([^`]+)``", content))
    priorities = set(re.findall(r"- Priority: ``([^`]+)``", content))

    assert statuses
    assert statuses.issubset(ALLOWED_STATUSES)
    assert priorities.issubset(ALLOWED_PRIORITIES)


def test_protocol_support_doc_sections_have_upstream_citations() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    major_sections = REQUIRED_SECTION_HEADINGS[1:-1]
    for index, heading in enumerate(major_sections):
        next_heading = (
            major_sections[index + 1]
            if index + 1 < len(major_sections)
            else REQUIRED_SECTION_HEADINGS[-1]
        )
        body = _section_body(content, heading, next_heading)
        assert "https://" in body, f"missing upstream citation in section: {heading}"


def test_protocol_support_artifact_schema_and_required_rows() -> None:
    artifact = _load_artifact()

    assert set(artifact.keys()) == {"meta", "rows"}
    assert artifact["meta"]["format"] == "filecoin_protocol_support_matrix.v1"
    assert set(artifact["meta"]["status_values"]) == ALLOWED_STATUSES
    assert set(artifact["meta"]["priority_values"]) == ALLOWED_PRIORITIES

    required_row_keys = {
        "id",
        "concern",
        "status",
        "priority",
        "upstream_evidence",
        "py_libp2p_evidence",
        "current_practical_support",
        "failure_modes",
        "recommended_next_step",
    }
    row_ids = set()
    for row in artifact["rows"]:
        assert required_row_keys.issubset(row.keys())
        assert row["status"] in ALLOWED_STATUSES
        if row["priority"] is not None:
            assert row["priority"] in ALLOWED_PRIORITIES
        assert row["upstream_evidence"]
        assert row["py_libp2p_evidence"]
        row_ids.add(row["id"])

    assert row_ids == {
        "identify",
        "ping",
        "hello_protocol_id",
        "hello_runtime",
        "chain_exchange_protocol_id",
        "chain_exchange_runtime",
        "gossipsub_protocol_negotiation",
        "filecoin_topic_naming",
        "filecoin_message_id",
        "score_thresholds",
        "full_topic_scoring_parity",
        "bootstrapper_px_direct_peers",
        "drand_f3_topics",
        "bitswap_note",
    }


def test_protocol_support_artifact_stays_in_sync_with_doc_labels() -> None:
    artifact = _load_artifact()
    content = DOC_PATH.read_text(encoding="utf-8")

    for row in artifact["rows"]:
        assert row["concern"] in content
