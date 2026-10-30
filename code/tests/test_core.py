import csv
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]          # the code/ directory
sys.path.insert(0, str(ROOT))

from deletion_audit.llm import LLM  # noqa: E402
from deletion_audit.models import (  # noqa: E402
    CaseAssessment, FlowAssessment, RecordState as S, ResourceAssessment as R, RestoreAssessment, Treatment as T,
)
from deletion_audit.pipeline import run  # noqa: E402
from deletion_audit.planner import Convention, build_result, derive_status  # noqa: E402
from deletion_audit.profile import infer_convention  # noqa: E402
from deletion_audit.scoring import score  # noqa: E402
from deletion_audit.synthetic import run_synthetic  # noqa: E402
from deletion_audit.usage import build_usage_report  # noqa: E402
from deletion_audit.validator import validate_output, validate_steps  # noqa: E402


def case(**kw):
    return CaseAssessment(case_id=kw.pop("case_id", "c1"), deletion_requested=kw.pop("req", True), **kw)


class PlannerTests(unittest.TestCase):
    def test_not_applicable_is_empty(self):
        r = build_result(case(req=False, resources=[R("a", "1", T.DELETE, S.INTACT, "e")]))
        self.assertEqual((r.status, r.steps), ("NOT_APPLICABLE", []))

    def test_complete_only_cited_verification(self):
        r = build_result(case(resources=[R("a", "1", T.DELETE, S.ABSENT, "e1")]))
        self.assertEqual(r.status, "COMPLETE")
        self.assertEqual([(s.phase, s.operation, s.evidence_id) for s in r.steps],
                         [("VERIFICATION", "VERIFY_RECORD_ABSENT", "e1")])

    def test_complete_without_evidence_warns(self):
        r = build_result(case(resources=[R("a", "1", T.DELETE, S.ABSENT, "")]))
        self.assertTrue(r.warnings)

    def test_active_flow_alone_makes_incomplete(self):
        a = case(resources=[R("a", "1", T.DELETE, S.ABSENT, "e")], flows=[FlowAssessment("sync", "j", True, "x")])
        self.assertEqual(derive_status(a), "INCOMPLETE")

    def test_unblocked_restore_alone_makes_incomplete(self):
        self.assertEqual(derive_status(case(restores=[RestoreAssessment("bk", "b", False, "x")])), "INCOMPLETE")

    def test_redacted_does_not_satisfy_anonymize(self):
        r = build_result(case(resources=[R("a", "1", T.ANONYMIZE, S.REDACTED, "e")]))
        self.assertEqual(r.status, "INCOMPLETE")
        self.assertIn("ANONYMIZE_RECORD", [s.operation for s in r.steps])

    def test_ordering_phase_then_op_then_system_then_resource(self):
        r = build_result(case(resources=[
            R("zz", "1", T.DELETE, S.INTACT, "e"), R("aa", "9", T.DELETE, S.INTACT, "e"),
            R("aa", "2", T.DELETE, S.INTACT, "e")]))
        findings = [(s.system_id, s.resource_id) for s in r.steps if s.phase == "FINDING"]
        self.assertEqual(findings, [("aa", "2"), ("aa", "9"), ("zz", "1")])
        self.assertEqual([s.step_no for s in r.steps], list(range(1, len(r.steps) + 1)))
        self.assertEqual([s.phase for s in r.steps], ["FINDING"] * 3 + ["REMEDIATION"] * 3 + ["VERIFICATION"] * 3)

    def test_incomplete_evidence_rules(self):
        r = build_result(case(resources=[R("a", "1", T.DELETE, S.INTACT, "e1")]))
        self.assertEqual({s.phase: s.evidence_id for s in r.steps},
                         {"FINDING": "e1", "REMEDIATION": "", "VERIFICATION": ""})

    def test_convention_flags(self):
        a = case(resources=[R("a", "1", T.DELETE, S.INTACT, "e"), R("b", "2", T.DELETE, S.ABSENT, "e2")])
        n_default = len(build_result(a).steps)                       # calibrated default: clean items are verified too
        n_strict = len(build_result(a, Convention(verify_already_clean=False)).steps)
        self.assertEqual(n_default, n_strict + 1)

    def test_missing_retained_warns_not_silent(self):
        r = build_result(case(resources=[R("b", "2", T.RETAIN, S.ABSENT, "e")]))
        self.assertTrue(r.warnings)


class ValidatorTests(unittest.TestCase):
    def _steps(self, result):
        return [s.to_dict() for s in result.steps]

    def test_planner_output_always_validates(self):
        a = case(resources=[R("a", "1", T.DELETE, S.INTACT, "e"), R("b", "2", T.RETAIN, S.INTACT, "e")],
                 flows=[FlowAssessment("s", "j", True, "x")], restores=[RestoreAssessment("k", "b", False, "y")])
        r = build_result(a)
        self.assertEqual(validate_steps(r.status, self._steps(r)), [])

    def test_catches_bad_order_and_numbering(self):
        r = build_result(case(resources=[R("a", "1", T.DELETE, S.INTACT, "e")]))
        steps = self._steps(r)[::-1]
        self.assertTrue(validate_steps("INCOMPLETE", steps))

    def test_catches_wrong_state_and_missing_verification(self):
        r = build_result(case(resources=[R("a", "1", T.DELETE, S.INTACT, "e")]))
        steps = self._steps(r)
        steps[0]["state"] = "ACTIVE"
        self.assertTrue(any("state" in e for e in validate_steps("INCOMPLETE", steps)))
        steps = self._steps(r)[:-1]
        self.assertTrue(any("no verification" in e for e in validate_steps("INCOMPLETE", steps)))

    def test_not_applicable_must_be_empty(self):
        self.assertTrue(validate_steps("NOT_APPLICABLE", [{"x": 1}]))


class PipelineTests(unittest.TestCase):
    def test_end_to_end_with_fake_assessor_sorted_and_valid(self):
        class Fake:
            def assess(self, req):
                if req["case_id"] == "case_002":
                    return case(case_id="case_002", req=False)
                if req["case_id"] == "case_boom":
                    raise RuntimeError("bad evidence")
                return case(case_id=req["case_id"], resources=[R("a", "1", T.DELETE, S.INTACT, "e")])

        with tempfile.TemporaryDirectory() as d:
            req, out = Path(d, "req.csv"), Path(d, "out.csv")
            req.write_text("case_id,email\ncase_003,x\ncase_001,y\ncase_002,z\n", encoding="utf-8")
            run(req, out, Fake())
            with open(out, encoding="utf-8") as fh:
                ids = [r["case_id"] for r in csv.DictReader(fh)]
            self.assertEqual(ids, ["case_001", "case_002", "case_003"])
            self.assertEqual(validate_output(req, out), [])
            self.assertIn("case_002,NOT_APPLICABLE,[]", out.read_text(encoding="utf-8"))

    def test_assessor_crash_is_isolated_and_flagged_by_validator(self):
        class Boom:
            def assess(self, _req):
                raise RuntimeError("x")

        with tempfile.TemporaryDirectory() as d:
            req, out = Path(d, "req.csv"), Path(d, "out.csv")
            req.write_text("case_id\ncase_001\n", encoding="utf-8")
            res = run(req, out, Boom())
            self.assertIn("ASSESSOR FAILED", res[0].warnings[0])
            self.assertTrue(validate_output(req, out))   # the broken row must not pass silently

    def test_validator_catches_unsorted_and_missing_rows(self):
        with tempfile.TemporaryDirectory() as d:
            req, out = Path(d, "req.csv"), Path(d, "out.csv")
            req.write_text("case_id\ncase_001\ncase_002\n", encoding="utf-8")
            out.write_text("case_id,deletion_status,steps_json\ncase_002,NOT_APPLICABLE,[]\n", encoding="utf-8")
            self.assertTrue(validate_output(req, out))


class ScoringTests(unittest.TestCase):
    def test_perfect_and_degraded(self):
        step = lambda op, ph, ev="": {"step_no": 1, "phase": ph, "system_id": "a", "resource_id": "1",
                                      "operation": op, "state": "X", "evidence_id": ev}
        gold = {"c1": ("INCOMPLETE", [step("REPORT_REMAINING_RECORD", "FINDING", "e")]),
                "c2": ("NOT_APPLICABLE", [])}
        self.assertEqual(score(gold, gold)["status_accuracy"], 1.0)
        bad = {"c1": ("COMPLETE", []), "c2": ("NOT_APPLICABLE", [])}
        m = score(bad, gold)
        self.assertEqual(m["status_accuracy"], 0.5)
        self.assertEqual(m["step_recall"], 0.0)
        self.assertEqual(len(m["failures"]), 1)


class ConventionInferenceTests(unittest.TestCase):
    def test_infers_flags_from_labelled_data(self):
        def st(n, ph, op, sy, rs, ev=""):
            return {"step_no": n, "phase": ph, "operation": op, "system_id": sy, "resource_id": rs, "state": "", "evidence_id": ev}
        gold = {"c": ("INCOMPLETE", [
            st(1, "FINDING", "REPORT_REMAINING_RECORD", "a", "1", "e"),
            st(2, "REMEDIATION", "DELETE_RECORD", "a", "1"),
            st(3, "VERIFICATION", "VERIFY_RECORD_ABSENT", "a", "1"),
            st(4, "VERIFICATION", "VERIFY_RECORD_PRESENT", "b", "2"),
        ])}
        conv, _ = infer_convention(gold)
        self.assertTrue(conv.verify_remediated and conv.verify_retained_present)
        self.assertFalse(conv.verify_already_clean or conv.redact_also_verify_present)


class LLMTests(unittest.TestCase):
    def _fake(self):
        calls = []

        class C:
            class messages:
                @staticmethod
                def create(**kw):
                    calls.append(kw)
                    return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")],
                                           usage=SimpleNamespace(input_tokens=100, output_tokens=10))
        return C, calls

    def test_cache_hit_not_billed_and_report_totals(self):
        client, calls = self._fake()
        with tempfile.TemporaryDirectory() as d:
            llm = LLM(Path(d, "cache"), Path(d, "ledger.jsonl"), client=client)
            for _ in range(2):
                self.assertEqual(llm.complete(model="m", system="s", prompt="p", tag="t"), "ok")
            self.assertEqual(len(calls), 1)
            md = build_usage_report(Path(d, "ledger.jsonl"), 2, {"m": {"input_per_mtok": 1.0, "output_per_mtok": 5.0}})
            self.assertIn("| Anthropic | m | 1 | 100 | 10 | 110 |", md)
            self.assertIn("Average tokens per request: **55.0**", md)
            with self.assertRaises(ValueError):
                build_usage_report(Path(d, "ledger.jsonl"), 2, {})


class SyntheticCaseTests(unittest.TestCase):
    def test_all_synthetic_cases_pass(self):
        md, ok = run_synthetic(ROOT / "evaluation" / "cases" / "synthetic_cases.json")
        self.assertTrue(ok, md)


if __name__ == "__main__":
    unittest.main()
