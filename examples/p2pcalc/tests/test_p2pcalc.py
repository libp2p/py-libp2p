# tests/test_p2pcalc.py — Test suite for P2PCalc
# Author: Dashpreet Singh <dashpreetsinghhanda@gmail.com>
#
# Run: python -m pytest tests/test_p2pcalc.py -v
# No network or Redis needed — all tests are pure logic.

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent))

from p2pcalc.crdt import ConflictPolicy, MultiValueRegister, SheetCRDT, StructuralCRDT
from p2pcalc.operation import HLC, Operation, OperationFactory, OpType
from p2pcalc.state_sync import SnapshotCandidate

# ---------------------------------------------------------------------------
# HLC Tests
# ---------------------------------------------------------------------------


class TestHLC(unittest.TestCase):
    def test_monotonically_increasing(self):
        clock = HLC()
        timestamps = [clock.now() for _ in range(100)]
        for i in range(1, len(timestamps)):
            a, b = timestamps[i - 1], timestamps[i]
            # b must be strictly greater than a
            self.assertTrue(
                b[0] > a[0] or (b[0] == a[0] and b[1] > a[1]),
                f"HLC not monotonic: {a} -> {b}",
            )

    def test_update_advances_past_remote(self):
        clock = HLC()
        # Simulate a remote timestamp far in the future
        future_physical = int(time.time() * 1000) + 5000
        clock.update(future_physical, 0)
        ts = clock.now()
        self.assertGreaterEqual(ts[0], future_physical)

    def test_compare_physical_dominates(self):
        clock = HLC()
        a = (1000, 5)
        b = (2000, 0)
        self.assertEqual(clock.compare(a, b), -1)
        self.assertEqual(clock.compare(b, a), 1)

    def test_compare_logical_breaks_tie(self):
        clock = HLC()
        a = (1000, 3)
        b = (1000, 7)
        self.assertEqual(clock.compare(a, b), -1)
        self.assertEqual(clock.compare(b, a), 1)

    def test_compare_equal(self):
        clock = HLC()
        a = (1000, 3)
        self.assertEqual(clock.compare(a, a), 0)


# ---------------------------------------------------------------------------
# Operation Tests
# ---------------------------------------------------------------------------


class TestOperationFactory(unittest.TestCase):
    def setUp(self):
        self.factory = OperationFactory(peer_id="peer-A")

    def test_parse_set_cell_value(self):
        op = self.factory.from_socialcalc_command("set A1 value 42", "sheet1")
        self.assertEqual(op.op_type, OpType.SET_CELL_VALUE)
        self.assertEqual(op.payload["cell"], "A1")
        self.assertEqual(op.payload["value"], "42")
        self.assertEqual(op.sheet_id, "sheet1")
        self.assertEqual(op.peer_id, "peer-A")

    def test_parse_set_cell_formula(self):
        op = self.factory.from_socialcalc_command(
            "set B2 formula =SUM(A1:A5)", "sheet1"
        )
        self.assertEqual(op.op_type, OpType.SET_CELL_FORMULA)
        self.assertEqual(op.payload["cell"], "B2")
        self.assertEqual(op.payload["formula"], "=SUM(A1:A5)")

    def test_parse_set_cell_format(self):
        op = self.factory.from_socialcalc_command("set C3 bgcolor #ff0000", "sheet1")
        self.assertEqual(op.op_type, OpType.SET_CELL_FORMAT)
        self.assertEqual(op.payload["attr"], "bgcolor")

    def test_parse_erase(self):
        op = self.factory.from_socialcalc_command("erase A1", "sheet1")
        self.assertEqual(op.op_type, OpType.CLEAR_CELL)
        self.assertEqual(op.payload["cell"], "A1")

    def test_parse_insert_row(self):
        op = self.factory.from_socialcalc_command("insertrow 3 1", "sheet1")
        self.assertEqual(op.op_type, OpType.INSERT_ROW)
        self.assertEqual(op.payload["row"], 3)
        self.assertEqual(op.payload["count"], 1)

    def test_parse_delete_col(self):
        op = self.factory.from_socialcalc_command("deletecol C 2", "sheet1")
        self.assertEqual(op.op_type, OpType.DELETE_COL)
        self.assertEqual(op.payload["col"], "C")

    def test_parse_range_format(self):
        op = self.factory.from_socialcalc_command("set A1:B5 bgcolor blue", "sheet1")
        self.assertEqual(op.op_type, OpType.SET_RANGE_FORMAT)

    def test_serialisation_roundtrip(self):
        op = self.factory.from_socialcalc_command("set A1 value hello", "sheet1")
        restored = Operation.from_bytes(op.to_bytes())
        self.assertEqual(restored.op_id, op.op_id)
        self.assertEqual(restored.peer_id, op.peer_id)
        self.assertEqual(restored.raw_command, op.raw_command)
        self.assertEqual(restored.payload, op.payload)
        self.assertEqual(restored.hlc, op.hlc)

    def test_integrity_check_passes(self):
        op = self.factory.from_socialcalc_command("set A1 value 99", "sheet1")
        self.assertTrue(op.verify_integrity())

    def test_integrity_check_fails_on_tamper(self):
        op = self.factory.from_socialcalc_command("set A1 value 99", "sheet1")
        op.raw_command = "set A1 value 999"  # tampered
        self.assertFalse(op.verify_integrity())

    def test_snapshot_request(self):
        op = self.factory.make_snapshot_request("sheet1")
        self.assertEqual(op.op_type, OpType.SNAPSHOT_REQUEST)

    def test_snapshot_chunk(self):
        op = self.factory.make_snapshot_chunk(
            "sheet1", chunk_index=0, total_chunks=2, data=b"hello", op_log_from=42
        )
        self.assertEqual(op.op_type, OpType.SNAPSHOT_CHUNK)
        self.assertEqual(op.payload["idx"], 0)
        self.assertEqual(op.payload["total"], 2)
        self.assertEqual(op.payload["op_log_from"], 42)

    def test_heartbeat(self):
        op = self.factory.make_heartbeat("sheet1", cell_cursor="B7")
        self.assertEqual(op.op_type, OpType.HEARTBEAT)
        self.assertEqual(op.payload["cursor"], "B7")

    def test_hlc_assigned(self):
        op1 = self.factory.from_socialcalc_command("set A1 value 1", "s")
        op2 = self.factory.from_socialcalc_command("set A2 value 2", "s")
        t1 = op1.hlc
        t2 = op2.hlc
        self.assertTrue(t2[0] > t1[0] or (t2[0] == t1[0] and t2[1] > t1[1]))

    def test_depends_on_propagated(self):
        op = self.factory.from_socialcalc_command(
            "set A1 value x", "s", depends_on=["abc123"]
        )
        self.assertIn("abc123", op.depends_on)


# ---------------------------------------------------------------------------
# CRDT — MultiValueRegister Tests
# ---------------------------------------------------------------------------


class TestMultiValueRegister(unittest.TestCase):
    def _make_op(self, peer_id, cell, value, hlc_p, hlc_l):
        factory = OperationFactory(peer_id=peer_id)
        op = factory.from_socialcalc_command(f"set {cell} value {value}", "s")
        op.hlc_physical = hlc_p
        op.hlc_logical = hlc_l
        op.payload = {"cell": cell, "value": value}
        return op

    def test_lww_higher_hlc_wins(self):
        mvr = MultiValueRegister(policy=ConflictPolicy.LAST_WRITE_WINS)
        op1 = self._make_op("peer-A", "A1", "first", 1000, 0)
        op2 = self._make_op("peer-B", "A1", "second", 2000, 0)
        mvr.apply(op1)
        mvr.apply(op2)
        state = mvr.get_cell("A1")
        self.assertEqual(state.current_value, "second")
        self.assertFalse(state.is_conflict)

    def test_lww_lower_hlc_ignored(self):
        mvr = MultiValueRegister(policy=ConflictPolicy.LAST_WRITE_WINS)
        op1 = self._make_op("peer-A", "A1", "first", 2000, 0)
        op2 = self._make_op("peer-B", "A1", "stale", 1000, 0)
        mvr.apply(op1)
        mvr.apply(op2)
        state = mvr.get_cell("A1")
        self.assertEqual(state.current_value, "first")

    def test_mvr_concurrent_writes_produce_conflict(self):
        mvr = MultiValueRegister(policy=ConflictPolicy.MULTI_VALUE)
        # Same HLC = concurrent writes
        op1 = self._make_op("peer-A", "A1", "alice_value", 1000, 0)
        op2 = self._make_op("peer-B", "A1", "bob_value", 1000, 0)
        mvr.apply(op1)
        mvr.apply(op2)
        state = mvr.get_cell("A1")
        self.assertTrue(state.is_conflict)
        self.assertEqual(len(state.candidates), 2)

    def test_mvr_causal_write_resolves_conflict(self):
        mvr = MultiValueRegister(policy=ConflictPolicy.MULTI_VALUE)
        op1 = self._make_op("peer-A", "A1", "alice", 1000, 0)
        op2 = self._make_op("peer-B", "A1", "bob", 1000, 0)
        # op3 causally follows both (higher HLC) — should dominate
        op3 = self._make_op("peer-C", "A1", "resolved", 2000, 0)
        mvr.apply(op1)
        mvr.apply(op2)
        mvr.apply(op3)
        state = mvr.get_cell("A1")
        self.assertFalse(state.is_conflict)
        self.assertEqual(state.current_value, "resolved")

    def test_mvr_clear_removes_all_candidates(self):
        mvr = MultiValueRegister(policy=ConflictPolicy.MULTI_VALUE)
        op1 = self._make_op("peer-A", "A1", "value", 1000, 0)
        mvr.apply(op1)
        factory = OperationFactory(peer_id="peer-A")
        erase = factory.from_socialcalc_command("erase A1", "s")
        erase.payload = {"cell": "A1"}
        mvr.apply(erase)
        state = mvr.get_cell("A1")
        self.assertEqual(len(state.candidates), 0)

    def test_peer_priority_lower_peer_wins(self):
        mvr = MultiValueRegister(policy=ConflictPolicy.PEER_PRIORITY)
        op1 = self._make_op("peer-A", "A1", "alice", 1000, 0)
        op2 = self._make_op("peer-B", "A1", "bob", 1000, 0)
        mvr.apply(op2)
        mvr.apply(op1)
        state = mvr.get_cell("A1")
        # "peer-A" < "peer-B" lexicographically
        self.assertEqual(state.current_value, "alice")

    def test_get_conflicts_empty_initially(self):
        mvr = MultiValueRegister()
        self.assertEqual(mvr.get_conflicts(), [])

    def test_snapshot_export(self):
        mvr = MultiValueRegister(policy=ConflictPolicy.LAST_WRITE_WINS)
        op = self._make_op("peer-A", "B3", "test_val", 1000, 0)
        mvr.apply(op)
        snap = mvr.snapshot()
        self.assertIn("B3", snap)
        self.assertEqual(snap["B3"]["value"], "test_val")


# ---------------------------------------------------------------------------
# CRDT — StructuralCRDT Tests
# ---------------------------------------------------------------------------


class TestStructuralCRDT(unittest.TestCase):
    def _make_row_op(self, op_type, row, peer_id="peer-A", hlc=(1000, 0)):
        factory = OperationFactory(peer_id=peer_id)
        op = factory.from_socialcalc_command(f"insertrow {row} 1", "s")
        op.op_type = op_type
        op.payload = {"row": row, "count": 1}
        op.hlc_physical = hlc[0]
        op.hlc_logical = hlc[1]
        return op

    def test_insert_row_appears_in_visible(self):
        crdt = StructuralCRDT()
        op = self._make_row_op(OpType.INSERT_ROW, 3)
        crdt.apply(op)
        self.assertIn(3, crdt.visible_rows())

    def test_delete_row_tombstoned(self):
        crdt = StructuralCRDT()
        op_ins = self._make_row_op(OpType.INSERT_ROW, 5)
        op_del = self._make_row_op(OpType.DELETE_ROW, 5)
        crdt.apply(op_ins)
        crdt.apply(op_del)
        self.assertNotIn(5, crdt.visible_rows())

    def test_concurrent_inserts_both_appear(self):
        crdt = StructuralCRDT()
        op_a = self._make_row_op(OpType.INSERT_ROW, 3, "peer-A")
        op_b = self._make_row_op(OpType.INSERT_ROW, 3, "peer-B")
        crdt.apply(op_a)
        crdt.apply(op_b)
        rows = crdt.visible_rows()
        self.assertEqual(rows.count(3), 2)

    def test_delete_of_nonexistent_is_noop(self):
        crdt = StructuralCRDT()
        op = self._make_row_op(OpType.DELETE_ROW, 99)
        crdt.apply(op)  # should not raise
        self.assertNotIn(99, crdt.visible_rows())

    def test_snapshot_structure(self):
        crdt = StructuralCRDT()
        crdt.apply(self._make_row_op(OpType.INSERT_ROW, 1))
        snap = crdt.snapshot()
        self.assertIn("rows", snap)
        self.assertIn("cols", snap)


# ---------------------------------------------------------------------------
# SheetCRDT Tests
# ---------------------------------------------------------------------------


class TestSheetCRDT(unittest.TestCase):
    def test_apply_and_dedup(self):
        sheet = SheetCRDT("test-sheet")
        factory = OperationFactory("peer-X")
        op = factory.from_socialcalc_command("set A1 value 10", "test-sheet")
        result1 = sheet.apply(op)
        result2 = sheet.apply(op)  # duplicate
        self.assertTrue(result1)
        self.assertFalse(result2)

    def test_op_log_grows(self):
        sheet = SheetCRDT("test-sheet")
        factory = OperationFactory("peer-X")
        for i in range(5):
            op = factory.from_socialcalc_command(
                f"set A{i + 1} value {i}", "test-sheet"
            )
            sheet.apply(op)
        self.assertEqual(sheet.op_log_length(), 5)

    def test_op_log_since(self):
        sheet = SheetCRDT("test-sheet")
        factory = OperationFactory("peer-X")
        for i in range(5):
            op = factory.from_socialcalc_command(
                f"set A{i + 1} value {i}", "test-sheet"
            )
            sheet.apply(op)
        recent = sheet.op_log_since(3)
        self.assertEqual(len(recent), 2)

    def test_snapshot_roundtrip(self):
        sheet = SheetCRDT("test-sheet")
        factory = OperationFactory("peer-X")
        op = factory.from_socialcalc_command("set B5 value hello", "test-sheet")
        sheet.apply(op)
        snap = sheet.snapshot()
        self.assertEqual(snap["sheet_id"], "test-sheet")
        self.assertIn("cells", snap)
        self.assertIn("B5", snap["cells"])


# ---------------------------------------------------------------------------
# Snapshot Candidate Tests
# ---------------------------------------------------------------------------


class TestSnapshotCandidate(unittest.TestCase):
    def test_completeness_detection(self):
        candidate = SnapshotCandidate(peer_id="peer-A", total_chunks=3, op_log_from=10)
        self.assertFalse(candidate.is_complete)
        candidate.chunks[0] = b"chunk0"
        candidate.chunks[1] = b"chunk1"
        candidate.chunks[2] = b"chunk2"
        self.assertTrue(candidate.is_complete)

    def test_data_assembly(self):
        candidate = SnapshotCandidate(peer_id="peer-A", total_chunks=2, op_log_from=0)
        candidate.chunks[0] = b"hello "
        candidate.chunks[1] = b"world"
        self.assertEqual(candidate.data, b"hello world")

    def test_content_hash_deterministic(self):
        candidate = SnapshotCandidate(peer_id="peer-A", total_chunks=1, op_log_from=0)
        candidate.chunks[0] = b"test data"
        h1 = candidate.content_hash
        h2 = candidate.content_hash
        self.assertEqual(h1, h2)


# ---------------------------------------------------------------------------
# Integration: multi-peer convergence simulation
# ---------------------------------------------------------------------------


class TestConvergence(unittest.TestCase):
    """Simulate two peers editing concurrently and verify convergence."""

    def test_two_peers_same_cell_lww_converges(self):
        sheet_a = SheetCRDT("shared", policy=ConflictPolicy.LAST_WRITE_WINS)
        sheet_b = SheetCRDT("shared", policy=ConflictPolicy.LAST_WRITE_WINS)

        factory_a = OperationFactory("peer-A")
        factory_b = OperationFactory("peer-B")

        # Peer A edits A1 at t=1000
        op_a = factory_a.from_socialcalc_command("set A1 value from_A", "shared")
        op_a.hlc_physical = 1000
        op_a.hlc_logical = 0
        op_a.payload = {"cell": "A1", "value": "from_A"}

        # Peer B edits A1 at t=2000 (later, causally after)
        op_b = factory_b.from_socialcalc_command("set A1 value from_B", "shared")
        op_b.hlc_physical = 2000
        op_b.hlc_logical = 0
        op_b.payload = {"cell": "A1", "value": "from_B"}

        # Both peers receive both ops (in different orders)
        sheet_a.apply(op_a)
        sheet_a.apply(op_b)

        sheet_b.apply(op_b)
        sheet_b.apply(op_a)

        val_a = sheet_a.cells.get_cell("A1").current_value
        val_b = sheet_b.cells.get_cell("A1").current_value

        # Both converge to the same value (op_b wins due to higher HLC)
        self.assertEqual(val_a, val_b)
        self.assertEqual(val_a, "from_B")

    def test_three_peers_distinct_cells_no_conflict(self):
        sheets = [
            SheetCRDT("shared", policy=ConflictPolicy.MULTI_VALUE) for _ in range(3)
        ]
        factories = [OperationFactory(f"peer-{i}") for i in range(3)]

        ops = []
        for i, (factory, sheet) in enumerate(zip(factories, sheets)):
            op = factory.from_socialcalc_command(
                f"set {chr(65 + i)}1 value peer_{i}", "shared"
            )
            op.payload = {"cell": f"{chr(65 + i)}1", "value": f"peer_{i}"}
            ops.append(op)

        # All peers receive all ops
        for sheet in sheets:
            for op in ops:
                sheet.apply(op)

        # No conflicts — each peer edited a different cell
        for sheet in sheets:
            self.assertEqual(sheet.get_conflicts(), [])

        # All sheets have same state
        for sheet in sheets:
            snap = sheet.snapshot()
            for i in range(3):
                coord = f"{chr(65 + i)}1"
                self.assertIn(coord, snap["cells"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
