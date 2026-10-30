"""Regression guard on the 32 labelled sample requests (skipped when dataset/ is not present).

Thresholds sit slightly below the current measured values so genuine regressions fail while harmless
tie-break noise does not. The samples were used to develop the heuristics, so these numbers are
in-sample; see evaluation/evaluation_report.md for how that is handled.
"""
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))
DATASET = CODE.parent / "dataset"

from deletion_audit.assessor import RealAssessor  # noqa: E402
from deletion_audit.pipeline import run  # noqa: E402
from deletion_audit.planner import Convention  # noqa: E402
from deletion_audit.scoring import load_output, score  # noqa: E402
from deletion_audit.validator import validate_output  # noqa: E402


@unittest.skipUnless((DATASET / "sample_output.csv").exists(), "dataset/ not available")
class SampleRegression(unittest.TestCase):
    def test_sample_scores_do_not_regress(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "pred.csv"
            run(DATASET / "sample_deletion_requests.csv", out, RealAssessor(DATASET, CODE / "data" / "visual_facts.json"), Convention())
            self.assertEqual(validate_output(DATASET / "sample_deletion_requests.csv", out), [])
            m = score(load_output(out), load_output(DATASET / "sample_output.csv"))
        self.assertGreaterEqual(m["status_accuracy"], 0.96)
        self.assertGreaterEqual(m["step_precision"], 0.97)
        self.assertGreaterEqual(m["step_recall"], 0.95)

    def test_full_run_is_valid_and_complete(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "output.csv"
            run(DATASET / "deletion_requests.csv", out, RealAssessor(DATASET, CODE / "data" / "visual_facts.json"), Convention())
            self.assertEqual(validate_output(DATASET / "deletion_requests.csv", out), [])
            rows = load_output(out)
        self.assertEqual(len(rows), 518)
        self.assertEqual(sum(s == "NOT_APPLICABLE" for s, _ in rows.values()), 10)


if __name__ == "__main__":
    unittest.main()
