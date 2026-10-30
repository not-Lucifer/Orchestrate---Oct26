"""Builds a miniature, fully synthetic dataset (same file formats as dataset/) for pipeline tests.

Every scenario is a *person* with a scripted truth; the builder renders that truth into evidence files
in several formats plus identities / audit log / activity, exactly like the real generator does. Nothing
here is copied from the real dataset: names, ids and emails are invented.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

RULES = [
    ("rule_01", "USER_PROFILE", "Always", "DELETE"), ("rule_02", "SECONDARY_IDENTIFIER", "Always", "DELETE"),
    ("rule_03", "SEARCH_INDEX_ENTRY", "Always", "DELETE"), ("rule_04", "CACHE_ENTRY", "Always", "DELETE"),
    ("rule_05", "SUPPORT_MESSAGE", "shared context", "REDACT"), ("rule_06", "SUPPORT_ATTACHMENT", "only subject", "DELETE"),
    ("rule_07", "ANALYTICS_PROFILE", "attributable", "ANONYMIZE"), ("rule_08", "PRODUCT_TELEMETRY", "attributable", "ANONYMIZE"),
    ("rule_09", "USER_EXPORT", "Always", "DELETE"), ("rule_10", "MARKETING_PROFILE", "Always", "DELETE"),
    ("rule_11", "EMAIL_DELIVERY_LOG", "contains email", "REDACT"), ("rule_12", "SECURITY_AUDIT_LOG", "retention", "RETAIN"),
    ("rule_13", "LEGAL_HOLD_RECORD", "hold", "RETAIN"), ("rule_14", "BACKUP_ARCHIVE", "blockable", "RETAIN"),
    ("rule_15", "ACCOUNT_TOMBSTONE", "stable id", "REDACT"),
]


def sha(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


class MiniDataset:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "evidence").mkdir(parents=True, exist_ok=True)
        self.identities: list[list] = []
        self.audit: list[list] = []
        self.activity: list[list] = []
        self.manifest: list[list] = []
        self.requests: list[list] = []
        self._n_evidence = 0
        self._n_activity = 0

    def person(self, uid, name, email, phone="+1 555 0100"):
        self.identities.append([uid, name, email, phone, sha(email), "2026-01-01T00:00:00Z"])

    def email_change(self, uid, old, new, when="2026-03-01T00:00:00Z"):
        i = len(self.audit) + 1
        self.audit.append([f"audit_{i:02d}", uid, when, "email", old, new])
        self.audit.append([f"audit_{i + 1:02d}", uid, when, "email_hash", sha(old), sha(new)])

    def event(self, when, etype, target, rid, result="SUCCESS", source="deletion_worker", details=""):
        self._n_activity += 1
        self.activity.append([f"activity_{self._n_activity}", when, etype, source, target, rid, result,
                              details or f"event for {rid}"])

    def evidence(self, name, captured_at, content: str | dict, origin="synthetic_capture") -> str:
        self._n_evidence += 1
        fid = f"evidence_{self._n_evidence:02d}"
        rel = f"evidence/{name}"
        text = content if isinstance(content, str) else json.dumps(content, indent=2)
        (self.root / rel).write_text(text, encoding="utf-8")
        self.manifest.append([fid, rel, origin, captured_at])
        return fid

    def request(self, case_id, email, requested, status, reported, audit, text="Please delete my account and personal data."):
        self.requests.append([case_id, email, requested, status, reported, audit, text])

    def write(self) -> Path:
        r = self.root
        write_csv(r / "user_identities.csv", ["user_id", "name", "email", "phone", "email_hash", "updated_at"], self.identities)
        write_csv(r / "user_audit_log.csv", ["audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"], self.audit)
        write_csv(r / "system_activity.csv", ["activity_id", "event_time", "event_type", "source_system", "target_system",
                                              "resource_id", "reported_result", "details"], sorted(self.activity, key=lambda x: x[1]))
        write_csv(r / "deletion_rules.csv", ["rule_id", "data_category", "condition", "required_action"], RULES)
        write_csv(r / "evidence_files.csv", ["file_id", "file_path", "origin", "captured_at"], self.manifest)
        write_csv(r / "deletion_requests.csv", ["case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at",
                                                "request_text"], self.requests)
        return r


def ledger(rows: list[tuple]) -> dict:
    """rows: (recorded_at, system, resource_id, record_type, result, subject_reference)"""
    return {"exported_at": rows[-1][0] if rows else "", "origin": "synthetic", "record_count": len(rows),
            "records": [{"recorded_at": t, "system": s, "resource_id": rid, "record_type": rt, "result": res,
                         "subject_reference": sub} for t, s, rid, rt, res, sub in rows]}


def build_scenarios(root: Path) -> Path:
    """Six scenarios, one per behaviour the real data tests."""
    d = MiniDataset(root)

    # S1 historical email + incomplete: search entry still indexed under the OLD email, audit record retained
    d.person("user_a1", "Ava Stone", "ava.new@example.org")
    d.email_change("user_a1", "ava.old@example.org", "ava.new@example.org")
    d.evidence("s1.json", "2026-05-02T12:00:00Z", ledger([
        ("2026-05-02T12:00:00Z", "account_service", "account_900", "USER_PROFILE", "NOT_FOUND", "ava.new@example.org"),
        ("2026-05-02T12:00:00Z", "search_service", "search_901", "SEARCH_INDEX_ENTRY", "FOUND", "ava.old@example.org"),
        ("2026-05-02T12:00:00Z", "security_service", "audit_record_902", "SECURITY_AUDIT_LOG", "FOUND", "user_a1")]))
    d.request("case_a1", "ava.old@example.org", "2026-05-01T09:00:00Z", "COMPLETE", "2026-05-01T12:00:00Z", "2026-05-02T12:00:00Z")

    # S2 resurrection after audit_at must NOT change the answer (COMPLETE, cite only the earlier file)
    d.person("user_b1", "Ben Reed", "ben.reed@example.org")
    f_ok = d.evidence("s2_before.json", "2026-05-02T11:30:00Z", ledger([
        ("2026-05-02T11:30:00Z", "account_service", "account_910", "USER_PROFILE", "NOT_FOUND", "ben.reed@example.org"),
        ("2026-05-02T11:30:00Z", "security_service", "audit_record_911", "SECURITY_AUDIT_LOG", "FOUND", "user_b1")]))
    d.evidence("s2_after.json", "2026-05-09T12:00:00Z", ledger([
        ("2026-05-09T12:00:00Z", "account_service", "account_910", "USER_PROFILE", "FOUND", "ben.reed@example.org")]))
    d.request("case_b1", "ben.reed@example.org", "2026-05-01T09:00:00Z", "COMPLETE", "2026-05-01T12:00:00Z", "2026-05-02T12:00:00Z")
    d.s2_expected_file = f_ok

    # S3 not a deletion request
    d.person("user_c1", "Cleo Ward", "cleo.ward@example.org")
    d.request("case_c1", "cleo.ward@example.org", "2026-05-01T09:00:00Z", "NOT_STARTED", "2026-05-01T12:00:00Z", "2026-05-02T12:00:00Z",
              "Please send me a copy of my data. Do not delete anything, I still use the account.")

    # S4 look-alike person must not be linked: ".jr" search entry belongs to someone else
    d.person("user_d1", "Dan Silva", "dan.silva@example.org")
    d.person("user_d2", "Dan Silva Jr", "dan.silva.jr@example.org")
    d.evidence("s4.json", "2026-05-03T12:00:00Z", ledger([
        ("2026-05-03T12:00:00Z", "search_service", "search_920", "SEARCH_INDEX_ENTRY", "FOUND", "dan.silva.jr@example.org"),
        ("2026-05-03T12:00:00Z", "account_service", "account_921", "USER_PROFILE", "NOT_FOUND", "dan.silva@example.org"),
        ("2026-05-03T12:00:00Z", "security_service", "audit_record_922", "SECURITY_AUDIT_LOG", "FOUND", "user_d1")]))
    d.request("case_d1", "dan.silva@example.org", "2026-05-02T09:00:00Z", "COMPLETE", "2026-05-02T12:00:00Z", "2026-05-03T12:00:00Z")

    # S5 claims vs truth: workflow says COMPLETE and every activity says SUCCESS, evidence shows identifiable analytics
    # + a live sync flow + a restorable backup
    d.person("user_e1", "Eli Moss", "eli.moss@example.org")
    d.evidence("s5.json", "2026-05-04T12:00:00Z", ledger([
        ("2026-05-04T12:00:00Z", "account_service", "account_930", "USER_PROFILE", "NOT_FOUND", "eli.moss@example.org"),
        ("2026-05-04T12:00:00Z", "analytics_platform", "analytics_931", "ANALYTICS_PROFILE", "IDENTIFIABLE", "eli.moss@example.org"),
        ("2026-05-04T12:00:00Z", "integration_service", "data_flow_932", "DATA_FLOW", "ACTIVE", "user_e1"),
        ("2026-05-04T12:00:00Z", "backup_service", "backup_933", "BACKUP_ARCHIVE", "ACTIVE", "user_e1"),
        ("2026-05-04T12:00:00Z", "security_service", "audit_record_934", "SECURITY_AUDIT_LOG", "FOUND", "user_e1")]))
    d.request("case_e1", "eli.moss@example.org", "2026-05-03T09:00:00Z", "COMPLETE", "2026-05-03T12:00:00Z", "2026-05-04T12:00:00Z")
    for rid, et, tgt in (("analytics_931", "ANONYMIZE_RECORD", "analytics_platform"), ("data_flow_932", "DISABLE_DATA_FLOW", "integration_service")):
        d.event("2026-05-03T11:40:00Z", et, tgt, rid, "SUCCESS", details=f"Policy action completed for {rid}.")

    # S6 identifier-free account: deletion batch with two cases of the same status -> both get a distinct account
    for uid, name, em, case, acc, ts in (("user_f1", "Fay Hall", "fay.hall@example.org", "case_f1", "account_941", "2026-05-05T10:50:00Z"),
                                        ("user_f2", "Gus Hale", "gus.hale@example.org", "case_f2", "account_942", "2026-05-05T11:05:00Z")):
        d.person(uid, name, em)
        d.event(ts, "DELETE_RECORD", "account_service", acc, "SUCCESS",
                details=f"Deletion worker submitted primary profile {acc} to account_service.")
        d.request(case, em, "2026-05-04T12:00:00Z", "COMPLETE", "2026-05-05T12:00:00Z", "2026-05-06T12:00:00Z")
    d.evidence("s6.json", "2026-05-06T11:00:00Z", ledger([
        ("2026-05-06T11:00:00Z", "security_service", "audit_record_943", "SECURITY_AUDIT_LOG", "FOUND", "user_f1"),
        ("2026-05-06T11:00:00Z", "security_service", "audit_record_944", "SECURITY_AUDIT_LOG", "FOUND", "user_f2")]))
    # S7 an attachment is also rendered as a plain ticket row in a later inventory snapshot: it is still an
    # attachment (DELETE -> REMAINING_RECORD), not a message (REDACT -> EXPOSED_PII)
    d.person("user_g1", "Gia Fox", "gia.fox@example.org")
    d.evidence("s7_old.json", "2026-05-06T08:00:00Z", {
        "exported_at": "2026-05-06T08:00:00Z", "source": "synthetic", "snapshots": [{
            "captured_at": "2026-05-06T08:00:00Z", "data_store": "support_platform", "collection": "ticket_attachments",
            "records": [{"resource_id": "support_960", "ticket_id": "CS-1", "file_name": "delivery_confirmation_1.pdf",
                         "uploaded_by": "gia.fox@example.org", "storage_class": "ticket_attachment"}]}]})
    d.evidence("s7_anchor.sql", "2026-05-07T09:00:00Z", """-- Captured at: 2026-05-07T09:00:00Z
CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);
INSERT INTO snapshot_scope VALUES('support_platform','2026-05-07T09:00:00Z');
INSERT INTO snapshot_scope VALUES('account_service','2026-05-07T09:00:00Z');
CREATE TABLE support_records (resource_id TEXT PRIMARY KEY, customer_reference TEXT, requester_name TEXT, requester_email TEXT, requester_phone TEXT, message_excerpt TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO support_records VALUES('support_960',NULL,NULL,'gia.fox@example.org',NULL,'Customer supplied contact details.','2026-05-07T08:00:00Z');
CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
""")
    d.request("case_g1", "gia.fox@example.org", "2026-05-06T09:00:00Z", "PARTIALLY_COMPLETE", "2026-05-06T12:00:00Z", "2026-05-07T12:00:00Z")
    return d.write()
