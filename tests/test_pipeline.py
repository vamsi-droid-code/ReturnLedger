import os
import re
import shutil
import tempfile
import unittest

from returnledger import storage
from returnledger.audit import run_audit
from returnledger.evaluate import evaluate
from returnledger.generator import generate
from returnledger.validate import Validator

SCALE = 0.05


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="returnledger_")
        cls.gen = generate(scale=SCALE)
        cls.manifest = storage.export(cls.gen, cls.tmp, formats=("csv", "sqlite"))
        cls.tables = storage.load_tables(cls.tmp)
        cls.gt, cls.labels = storage.load_ground_truth(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_exact_volumes(self):
        t = self.tables
        self.assertEqual(sum(o["order_type"] == "SALE" for o in t["orders"]), 1500)
        self.assertEqual(len(t["return_request"]), 250)
        self.assertEqual(len(t["return_line"]), 400)

    def test_id_conventions(self):
        t = self.tables
        self.assertTrue(all(re.fullmatch(r"ORD-2026-\d{6}", o["order_id"]) for o in t["orders"]))
        self.assertTrue(all(re.fullmatch(r"RMA-2026-\d{6}", r["rma_id"]) for r in t["return_request"]))
        self.assertTrue(all(rl["return_line_id"].startswith(f"RMAL-{rl['rma_id']}-") for rl in t["return_line"]))
        self.assertTrue(all(re.fullmatch(r"RTS-2026-\d{6}", s["shipment_id"]) for s in t["return_shipment"]))
        self.assertTrue(all(re.fullmatch(r"REF-2026-\d{6}", r["refund_id"]) for r in t["refund"]))

    def test_validation_passes(self):
        summary = Validator(self.tables, self.gt, self.tmp, self.manifest["target_volume"]).run()
        failing = [c for c in summary["checks"] if c["status"] == "FAIL"]
        self.assertEqual(failing, [])

    def test_audit_detects_every_anomaly(self):
        ev = evaluate(self.tables, run_audit(self.tables), self.gt, self.labels)
        micro = ev["anomaly_detection"]["micro"]
        self.assertEqual((micro["fp"], micro["fn"]), (0, 0))
        self.assertEqual(ev["decision_conformance"]["clean_match_rate"], 1.0)

    def test_ground_truth_not_leaked(self):
        input_cols = {c for rows in self.tables.values() for c in (rows[0] if rows else {})}
        self.assertFalse(input_cols & {"issue_type", "is_anomaly", "anomaly_issue_types", "expected_value"})

    def test_every_anomaly_type_present(self):
        types = {a["issue_type"] for a in self.gt}
        self.assertEqual(types, {"QTY_EXCEEDS_PURCHASED", "REFUND_EXCEEDS_PAID", "RESTOCK_BEFORE_INSPECTION",
                                 "LATE_APPROVED_WITHOUT_OVERRIDE", "DUPLICATE_REFUND"})

    def test_same_seed_same_data_and_new_seed_differs(self):
        again = generate(scale=SCALE)
        self.assertEqual(again.t, self.gen.t)
        self.assertEqual(again.gt_anomalies, self.gen.gt_anomalies)
        other = generate(seed=12345, scale=SCALE)
        self.assertNotEqual(other.t["orders"], self.gen.t["orders"])


if __name__ == "__main__":
    unittest.main()
