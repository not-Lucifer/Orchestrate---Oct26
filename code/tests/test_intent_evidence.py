import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from deletion_audit.evidence import (  # noqa: E402
    link_keys, parse_handover_txt, parse_json_file, parse_log_file, parse_log_line, parse_sql_file, system_of,
)
from deletion_audit.intent import classify  # noqa: E402


class IntentTests(unittest.TestCase):
    def test_deletion_requests_in_several_languages(self):
        for t in ("Please permanently delete the account associated with this email address.",
                  "Je demande la suppression définitive du compte associé à cette adresse e-mail.",
                  "Solicito a exclusão permanente da conta associada a este e-mail.",
                  "このメールアドレスに関連するアカウントの完全な削除を依頼します。",
                  "이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다."):
            self.assertTrue(classify(t).deletion, t)

    def test_verification_only_requests_still_count_as_deletion_audits(self):
        self.assertTrue(classify("Please check the latest state and confirm that the profile is gone.").deletion)

    def test_negated_or_other_purpose_requests_are_not_deletion(self):
        for t in ("Please leave the account active and replace the mobile number.",
                  "I want a copy of my data. Please don't delete anything.",
                  "Please remove me from marketing lists only. I still want receipts.",
                  "Can you tell me what personal information you hold? This is not a request to erase it.",
                  "Please keep the account as it is. I'd like to download my account information in a portable format."):
            self.assertFalse(classify(t).deletion, t)

    def test_complaint_that_data_was_deleted_is_not_a_deletion_request(self):
        for t in ("Why was my order deleted? Please restore my account data immediately.",
                  "My account was removed by mistake, please bring it back."):
            self.assertFalse(classify(t).deletion, t)
        # an explicit request still wins, even when restore/backups are mentioned
        self.assertTrue(classify("Please delete my account and make sure backups cannot restore my data.").deletion)
        self.assertTrue(classify("My data was deleted last year, but I want my data erased from the exports too.").deletion)

    def test_deletion_with_scoping_remarks_is_still_deletion(self):
        self.assertTrue(classify("I'm deleting my account. You can keep anonymous statistics.").deletion)
        self.assertTrue(classify("Close this account. You may retain backups if required.").deletion)


class IntentLLMTests(unittest.TestCase):
    class Fake:
        def __init__(self, answer):
            self.answer, self.calls = answer, 0

        def complete(self, **_):
            self.calls += 1
            return self.answer

    def test_confident_rule_results_never_call_the_model(self):
        fake = self.Fake('{"intent": "NOT_DELETE", "confidence": 0.99}')
        self.assertTrue(classify("Please delete my account.", fake).deletion)
        self.assertEqual(fake.calls, 0)

    def test_low_confidence_uses_model_and_falls_back_safely(self):
        vague = "Hello, regarding my profile."
        self.assertTrue(classify(vague, self.Fake('{"intent": "DELETE", "confidence": 0.9, "reason": "x"}')).deletion is True)
        self.assertFalse(classify(vague, self.Fake("not json")).deletion)                       # conservative default
        self.assertFalse(classify(vague, self.Fake('{"intent": "DELETE", "confidence": 0.3}')).deletion)


class KeyTests(unittest.TestCase):
    def test_normalisation(self):
        self.assertEqual(link_keys("  A.B@Example.COM ", "user_7", "+1 (202) 555-0103", None, "null", "[REDACTED]"),
                         ("a.b@example.com", "user_7", "tel:12025550103"))
        h = "a" * 64
        self.assertEqual(link_keys(h.upper()), (h,))
        self.assertEqual(link_keys("Please send it to Bob@x.org today"), ("bob@x.org",))

    def test_system_comes_from_resource_prefix(self):
        self.assertEqual(system_of("analytics_9"), "analytics_platform")
        self.assertEqual(system_of("data_flow_3"), "integration_service")
        self.assertEqual(system_of("object_19"), "object_storage")


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_dialects_are_normalised(self):
        kv = '2026-01-01T10:00:00Z level=INFO service=search_service trace_id=t1 resource_id=search_1 event=index_query_completed result=hit email=A@B.CO'
        br = '2026-01-01T10:00:00Z [INFO] [account_service] [t2] profile_lookup_completed: resource_id="account_2" rows="0" http_status="404"'
        pipe = '2026-01-01T10:00:00Z | DEBUG | security_service | t3 | audit_record_read_completed | resource_id="audit_record_3" subject_reference="user_9"'
        js = '2026-01-01T10:00:00Z {"event":"index_query_completed","resource_id":"search_4","result":"miss"}'
        for line, event in ((kv, "index_query_completed"), (br, "profile_lookup_completed"),
                            (pipe, "audit_record_read_completed"), (js, "index_query_completed")):
            self.assertEqual(parse_log_line(line)["event"], event)
        p = self.dir / "x.log"
        p.write_text("\n".join([kv, br, pipe, js]) + "\n", encoding="utf-8")
        facts = {f.resource_id: f for f in parse_log_file("e1", p, "2026-01-01T10:00:00Z").facts}
        self.assertEqual(facts["search_1"].state, "FOUND")
        self.assertEqual(facts["search_1"].keys, ("a@b.co",))
        self.assertEqual(facts["account_2"].state, "NOT_FOUND")
        self.assertEqual(facts["audit_record_3"].keys, ("user_9",))
        self.assertEqual(facts["search_4"].state, "NOT_FOUND")

    def test_lookup_key_on_started_line_is_joined_by_trace_id(self):
        p = self.dir / "t.log"
        p.write_text("2026-01-01T10:00:00Z level=DEBUG service=a trace_id=tr1 event=profile_lookup_started resource_id=account_5 lookup_key=z@y.org\n"
                     "2026-01-01T10:00:01Z level=INFO service=a trace_id=tr1 event=profile_lookup_completed resource_id=account_5 rows=0 http_status=404\n",
                     encoding="utf-8")
        (f,) = [x for x in parse_log_file("e1", p, "2026-01-01T10:00:00Z").facts if x.state == "NOT_FOUND"]
        self.assertEqual(f.keys, ("z@y.org",))

    def test_handover_txt_and_ledger_json(self):
        facts = parse_handover_txt("e1", "- 2026-01-01T12:00:00Z | analytics_platform | analytics_7 | ANALYTICS_PROFILE | ANONYMIZED | no direct identifier\n"
                                         "- 2026-01-01T12:00:00Z | backup_service | backup_8 | BACKUP_ARCHIVE | ACTIVE | user_3\n", "2026-01-01T12:00:00Z")
        self.assertEqual([(f.resource_id, f.state, f.keys) for f in facts],
                         [("analytics_7", "ANONYMIZED", ()), ("backup_8", "ACTIVE", ("user_3",))])

    def test_sql_snapshot_primary_vs_replica_and_scope(self):
        sql = """-- Captured at: 2026-02-02T00:00:00Z
CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);
INSERT INTO snapshot_scope VALUES('account_service','2026-02-02T00:00:00Z');
CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO customer_profiles VALUES('account_1','user_1',NULL,'q@w.org',NULL,NULL,'ACTIVE','2026-02-01T00:00:00Z');
CREATE TABLE customer_analytics_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, email TEXT, phone TEXT, email_hash TEXT, audience_cohort TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO customer_analytics_profiles VALUES('analytics_2',NULL,NULL,NULL,NULL,'x','2026-02-01T00:00:00Z');
"""
        p = self.dir / "s.sql"
        p.write_text(sql, encoding="utf-8")
        pf = parse_sql_file("e1", p, "2026-02-02T00:00:00Z")
        by = {f.resource_id: f for f in pf.facts}
        self.assertEqual((by["account_1"].state, by["account_1"].keys), ("FOUND", ("q@w.org", "user_1")))
        self.assertEqual(by["analytics_2"].state, "ANONYMIZED")
        self.assertIn("USER_PROFILE", {c.category for c in pf.coverage})

    def test_export_unavailable_is_not_a_remaining_record(self):
        p = self.dir / "j.json"
        p.write_text(json.dumps({"captured_at": "2026-01-01T00:00:00Z", "collection": "customer_export_jobs", "records": [
            {"resource_id": "export_1", "owner_email": "a@b.co", "download_available": True},
            {"resource_id": "export_2", "owner_email": "c@d.co", "download_available": False}]}), encoding="utf-8")
        st = {f.resource_id: f.state for f in parse_json_file("e1", p, "2026-01-01T00:00:00Z").facts}
        self.assertEqual(st, {"export_1": "FOUND", "export_2": "NOT_FOUND"})


class VisualExtractorTests(unittest.TestCase):
    def test_response_is_validated_against_the_vocabulary(self):
        from deletion_audit.visual import parse_response
        raw = 'Here you go: {"describes": "x", "facts": ['               '{"resource_id": "export_1", "category": "USER_EXPORT", "state": "FOUND", "keys": ["a@b.co"]},'               '{"resource_id": "export_2", "category": "MADE_UP", "state": "FOUND"},'               '{"resource_id": "export_3", "category": "USER_EXPORT", "state": "MAYBE"}]}'
        out = parse_response(raw, "2026-01-01T00:00:00Z")
        self.assertEqual([f["resource_id"] for f in out["facts"]], ["export_1"])
        self.assertEqual(out["facts"][0]["t"], "2026-01-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
