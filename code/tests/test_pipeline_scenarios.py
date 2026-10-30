"""End-to-end behaviour of the real assessor on a miniature synthetic dataset (see fixtures.py)."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "tests"))

from deletion_audit.assessor import RealAssessor  # noqa: E402
from deletion_audit.pipeline import run  # noqa: E402
from deletion_audit.planner import Convention  # noqa: E402
from deletion_audit.validator import validate_output  # noqa: E402
from fixtures import build_scenarios  # noqa: E402


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = build_scenarios(Path(cls._tmp.name))
        cls.out = cls.root / "output.csv"
        cls.results = {r.case_id: r for r in run(cls.root / "deletion_requests.csv", cls.out,
                                                 RealAssessor(cls.root), Convention())}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def ops(self, cid):
        return [(s.phase[:4], s.operation, s.resource_id, s.evidence_id) for s in self.results[cid].steps]

    def test_output_is_valid(self):
        self.assertEqual(validate_output(self.root / "deletion_requests.csv", self.out), [])

    def test_s1_historical_email_finds_record_under_old_identifier(self):
        r = self.results["case_a1"]
        self.assertEqual(r.status, "INCOMPLETE")
        self.assertIn(("FIND", "REPORT_REMAINING_RECORD", "search_901", "evidence_01"), self.ops("case_a1"))
        self.assertIn(("VERI", "VERIFY_RECORD_PRESENT", "audit_record_902", ""), self.ops("case_a1"))
        self.assertIn(("VERI", "VERIFY_RECORD_ABSENT", "account_900", ""), self.ops("case_a1"))

    def test_s2_evidence_after_audit_at_is_ignored(self):
        r = self.results["case_b1"]
        self.assertEqual(r.status, "COMPLETE")
        self.assertEqual({s.evidence_id for s in r.steps}, {"evidence_02"})        # never evidence_03 (captured later)

    def test_s3_non_deletion_request_is_not_applicable(self):
        self.assertEqual((self.results["case_c1"].status, self.results["case_c1"].steps), ("NOT_APPLICABLE", []))

    def test_s4_look_alike_identity_is_not_linked(self):
        r = self.results["case_d1"]
        self.assertEqual(r.status, "COMPLETE")
        self.assertNotIn("search_920", [s.resource_id for s in r.steps])

    def test_s5_reported_complete_but_evidence_says_otherwise(self):
        r = self.results["case_e1"]
        self.assertEqual(r.status, "INCOMPLETE")
        got = {s.operation for s in r.steps}
        self.assertTrue({"REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK",
                         "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "ANONYMIZE_RECORD"} <= got)
        phases = [s.phase for s in r.steps]
        self.assertEqual(phases, sorted(phases, key=["FINDING", "REMEDIATION", "VERIFICATION"].index))
        self.assertEqual([s.step_no for s in r.steps], list(range(1, len(r.steps) + 1)))

    def test_s6_identifier_free_accounts_get_distinct_resources(self):
        a = {s.resource_id for s in self.results["case_f1"].steps if s.resource_id.startswith("account_")}
        b = {s.resource_id for s in self.results["case_f2"].steps if s.resource_id.startswith("account_")}
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertNotEqual(a, b)
        self.assertEqual(a | b, {"account_941", "account_942"})

    def test_s7_attachment_rendered_as_ticket_row_is_still_an_attachment(self):
        ops = {(s.operation, s.resource_id) for s in self.results["case_g1"].steps}
        self.assertIn(("REPORT_REMAINING_RECORD", "support_960"), ops)
        self.assertIn(("DELETE_RECORD", "support_960"), ops)
        self.assertNotIn(("REDACT_RECORD", "support_960"), ops)

    def test_output_is_independent_of_python_hash_seed(self):
        import os
        import subprocess
        outs = []
        for seed in ("1", "2", "3"):
            o = self.root / f"seed{seed}.csv"
            subprocess.run([sys.executable, "-B", str(CODE / "main.py"), "--dataset", str(self.root), "--out", str(o),
                            "--visual-facts", str(self.root / "none.json")], check=True, capture_output=True,
                           env={**os.environ, "PYTHONHASHSEED": seed})
            outs.append(o.read_text(encoding="utf-8"))
        self.assertEqual(len(set(outs)), 1)

    def test_deterministic(self):
        again = run(self.root / "deletion_requests.csv", self.root / "again.csv", RealAssessor(self.root), Convention())
        self.assertEqual((self.root / "output.csv").read_text(encoding="utf-8"),
                         (self.root / "again.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
