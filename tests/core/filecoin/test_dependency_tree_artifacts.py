from collections import defaultdict, deque
import json
from pathlib import Path

from libp2p import filecoin

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_PATH = REPO_ROOT / "artifacts" / "filecoin" / "libp2p_dependency_tree.v1.json"
TREE_DOC_PATH = REPO_ROOT / "docs" / "filecoin" / "libp2p_dependency_tree.md"
MATRIX_DOC_PATH = REPO_ROOT / "docs" / "filecoin" / "parity_matrix.md"


def _load_artifact() -> dict:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_dependency_tree_artifact_schema() -> None:
    artifact = _load_artifact()

    assert set(artifact.keys()) == {"meta", "nodes", "edges"}
    assert artifact["meta"]["format"] == "libp2p_dependency_tree.v1"
    assert artifact["meta"]["sources"]["lotus"]["version"] == "v1.35.0"
    assert artifact["meta"]["sources"]["forest"]["version"] == "0.32.2"

    allowed_relations = set(artifact["meta"]["allowed_relations"])
    assert allowed_relations == {
        "defines",
        "consumes",
        "configures",
        "maps_to",
        "derived_from",
    }

    required_node_keys = {
        "id",
        "project",
        "symbol",
        "kind",
        "file",
        "line_start",
        "line_end",
        "version",
    }
    for node in artifact["nodes"]:
        assert required_node_keys.issubset(node.keys())

    required_edge_keys = {"from", "to", "relation"}
    node_ids = {node["id"] for node in artifact["nodes"]}
    for edge in artifact["edges"]:
        assert required_edge_keys.issubset(edge.keys())
        assert edge["relation"] in allowed_relations
        assert edge["from"] in node_ids
        assert edge["to"] in node_ids


def test_all_public_filecoin_exports_present_in_graph_nodes() -> None:
    artifact = _load_artifact()
    py_symbols = {
        node["symbol"] for node in artifact["nodes"] if node["project"] == "py-libp2p"
    }
    missing = set(filecoin.__all__) - py_symbols
    assert missing == set()


def test_required_symbols_have_upstream_lineage_path() -> None:
    artifact = _load_artifact()
    nodes_by_id = {node["id"]: node for node in artifact["nodes"]}
    ids_by_symbol = defaultdict(list)
    for node in artifact["nodes"]:
        ids_by_symbol[node["symbol"]].append(node["id"])

    incoming_edges: dict[str, list[dict]] = defaultdict(list)
    for edge in artifact["edges"]:
        incoming_edges[edge["to"]].append(edge)

    def has_upstream_lineage(node_id: str, max_depth: int = 4) -> bool:
        queue = deque([(node_id, 0)])
        visited = set()
        while queue:
            current, depth = queue.popleft()
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            for edge in incoming_edges[current]:
                source = edge["from"]
                source_node = nodes_by_id[source]
                if source_node["project"] != "py-libp2p":
                    return True
                queue.append((source, depth + 1))
        return False

    required_symbols = {
        "FIL_HELLO_PROTOCOL",
        "FIL_CHAIN_EXCHANGE_PROTOCOL",
        "blocks_topic",
        "messages_topic",
        "dht_protocol_name",
        "filecoin_message_id",
        "MAINNET_BOOTSTRAP",
        "CALIBNET_BOOTSTRAP",
        "GOSSIP_SCORE_THRESHOLD",
        "PUBLISH_SCORE_THRESHOLD",
        "GRAYLIST_SCORE_THRESHOLD",
        "ACCEPT_PX_SCORE_THRESHOLD",
        "build_filecoin_gossipsub",
        "build_filecoin_pubsub",
    }

    for symbol in required_symbols:
        matching_ids = [
            node_id
            for node_id in ids_by_symbol[symbol]
            if nodes_by_id[node_id]["project"] == "py-libp2p"
        ]
        assert matching_ids, f"missing py-libp2p node for symbol {symbol}"
        assert any(has_upstream_lineage(node_id) for node_id in matching_ids), (
            f"missing upstream lineage path for symbol {symbol}"
        )


def test_parity_matrix_rows_have_upstream_references() -> None:
    content = MATRIX_DOC_PATH.read_text(encoding="utf-8")
    rows = [
        line
        for line in content.splitlines()
        if line.startswith("| ") and not line.startswith("|---")
    ]
    # header + separator + at least one data row
    assert len(rows) >= 3

    data_rows = rows[1:]
    for row in data_rows:
        assert "node/" in row or "chain/" in row or "build/" in row or "src/" in row, (
            f"row lacks Lotus/Forest reference: {row}"
        )


def test_dependency_tree_doc_contains_required_mermaid_sections() -> None:
    content = TREE_DOC_PATH.read_text(encoding="utf-8")
    assert content.count("```mermaid") >= 3
    assert "## Constants lineage tree" in content
    assert "## Runtime bootstrap flow tree" in content
    assert "## Pubsub preset / score lineage tree" in content
    assert "## Divergences and source-of-truth decisions" in content
