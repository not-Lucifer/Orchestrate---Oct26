"""Evidence extraction: every evidence format -> uniform `Fact`s.

The dataset renders one underlying truth ("what state is resource R in at time T, and which
identifiers does it expose") in many formats: SQL snapshots (primary + replicas), JSON bundles,
service exports, ledger rows, shift-handover text and ~10 log dialects. Each parser below maps its
format onto the same vocabulary used by `deletion_rules.csv` data categories:

    USER_PROFILE         FOUND | NOT_FOUND
    SEARCH_INDEX_ENTRY   FOUND | NOT_FOUND
    SUPPORT_MESSAGE      IDENTIFIABLE | REDACTED
    SUPPORT_ATTACHMENT   FOUND | NOT_FOUND
    ANALYTICS_PROFILE    IDENTIFIABLE | ANONYMIZED
    USER_EXPORT          FOUND | NOT_FOUND
    MARKETING_PROFILE    FOUND | NOT_FOUND
    DATA_FLOW            ACTIVE | DISABLED
    BACKUP_ARCHIVE       ACTIVE | BLOCKED          (ACTIVE = restore still allowed)
    SECURITY_AUDIT_LOG   FOUND
    LEGAL_HOLD_RECORD    FOUND
    ACCOUNT_TOMBSTONE    IDENTIFIABLE | REDACTED

`Coverage` entries record that a snapshot enumerates a whole category, so a resource missing from
that snapshot can be treated as NOT_FOUND (absence by omission).
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\+?\d[\d ()-]{6,}\d")
HASH_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")

PREFIX_CATEGORY = (
    ("account_", "USER_PROFILE"), ("search_", "SEARCH_INDEX_ENTRY"), ("support_", "SUPPORT_MESSAGE"),
    ("analytics_", "ANALYTICS_PROFILE"), ("export_", "USER_EXPORT"), ("data_flow_", "DATA_FLOW"),
    ("backup_", "BACKUP_ARCHIVE"), ("audit_record_", "SECURITY_AUDIT_LOG"),
    ("legal_hold_", "LEGAL_HOLD_RECORD"), ("tombstone_", "ACCOUNT_TOMBSTONE"),
    ("marketing_", "MARKETING_PROFILE"), ("object_", "SUPPORT_ATTACHMENT"),
)
SYSTEM_BY_PREFIX = {"object_": "object_storage"}     # attachments stored in the object store
CATEGORY_SYSTEM = {
    "USER_PROFILE": "account_service", "SEARCH_INDEX_ENTRY": "search_service",
    "SUPPORT_MESSAGE": "support_platform", "SUPPORT_ATTACHMENT": "support_platform",
    "ANALYTICS_PROFILE": "analytics_platform", "USER_EXPORT": "export_service",
    "DATA_FLOW": "integration_service", "BACKUP_ARCHIVE": "backup_service",
    "SECURITY_AUDIT_LOG": "security_service", "LEGAL_HOLD_RECORD": "legal_service",
    "ACCOUNT_TOMBSTONE": "identity_service", "MARKETING_PROFILE": "marketing_platform",
}
SYSTEM_CATEGORIES = {}
for _c, _s in CATEGORY_SYSTEM.items():
    SYSTEM_CATEGORIES.setdefault(_s, []).append(_c)


def category_of(resource_id: str) -> str | None:
    for p, c in PREFIX_CATEGORY:
        if resource_id.startswith(p):
            return c
    return None


def system_of(resource_id: str) -> str:
    """The owning system is named by the resource id prefix (a secondary-identifier record in
    analytics_platform is still `analytics_*`), independent of the record's policy category."""
    for prefix, system in SYSTEM_BY_PREFIX.items():
        if resource_id.startswith(prefix):
            return system
    c = category_of(resource_id)
    return CATEGORY_SYSTEM.get(c, "unknown_service") if c else "unknown_service"


def norm_email(s: str) -> str:
    return s.strip().lower()


def norm_phone(s: str) -> str:
    return re.sub(r"\D", "", s)


def link_keys(*values) -> tuple[str, ...]:
    """Normalise identifier-like values into comparable linking keys (email / phone / hash / user ref)."""
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        v = str(v).strip()
        if not v or v.lower() in {"null", "none", "[redacted]", "no direct identifier"}:
            continue
        if re.fullmatch(r"user_\w+", v, re.I):
            out.append(v.lower())
        elif HASH_RE.fullmatch(v):
            out.append(v.lower())
        elif "@" in v:
            out += [norm_email(m) for m in EMAIL_RE.findall(v)]
        elif len(norm_phone(v)) >= 8 and PHONE_RE.fullmatch(v):
            out.append("tel:" + norm_phone(v))
    return tuple(dict.fromkeys(out))


@dataclass(frozen=True)
class Fact:
    file_id: str
    t: str                      # observation time, ISO-8601 Z (lexicographically comparable)
    resource_id: str
    category: str
    state: str
    keys: tuple[str, ...] = ()  # identifiers that tie the record to a person
    src: str = ""               # parser tag, for debugging
    links: tuple[str, ...] = () # other resource ids this record points at (e.g. search doc -> source account)


@dataclass(frozen=True)
class Coverage:
    file_id: str
    t: str
    category: str


@dataclass
class ParsedFile:
    file_id: str
    path: str
    captured_at: str
    facts: list[Fact] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)


def _state_for(category: str, *, found: bool | None = None, identifiable: bool | None = None,
               enabled: bool | None = None, restore_allowed: bool | None = None) -> str | None:
    if category in ("USER_PROFILE", "SEARCH_INDEX_ENTRY", "SUPPORT_ATTACHMENT", "USER_EXPORT",
                    "MARKETING_PROFILE"):
        return None if found is None else ("FOUND" if found else "NOT_FOUND")
    if category in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
        return "FOUND" if found in (None, True) else "NOT_FOUND"
    if category in ("SUPPORT_MESSAGE",):
        return None if identifiable is None else ("IDENTIFIABLE" if identifiable else "REDACTED")
    if category in ("ANALYTICS_PROFILE", "ACCOUNT_TOMBSTONE"):
        if identifiable is None:
            return None
        return "IDENTIFIABLE" if identifiable else ("ANONYMIZED" if category == "ANALYTICS_PROFILE" else "REDACTED")
    if category == "DATA_FLOW":
        return None if enabled is None else ("ACTIVE" if enabled else "DISABLED")
    if category == "BACKUP_ARCHIVE":
        return None if restore_allowed is None else ("ACTIVE" if restore_allowed else "BLOCKED")
    return None


def _truthy(v) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "enabled", "active"):
        return True
    if s in ("false", "0", "no", "disabled", "stopped", "blocked"):
        return False
    return None


def _has_value(*values) -> bool:
    return any(v not in (None, "", "null", "None", "[REDACTED]") for v in values)


# --------------------------------------------------------------------------------------------
# ledger-style rows: (time, system, resource_id, record_type, result, subject) in json/txt/logs
# --------------------------------------------------------------------------------------------
LEDGER_STATE = {
    ("USER_PROFILE", "FOUND"): "FOUND", ("USER_PROFILE", "NOT_FOUND"): "NOT_FOUND",
    ("SEARCH_INDEX_ENTRY", "FOUND"): "FOUND", ("SEARCH_INDEX_ENTRY", "NOT_FOUND"): "NOT_FOUND",
    ("SUPPORT_MESSAGE", "IDENTIFIABLE"): "IDENTIFIABLE", ("SUPPORT_MESSAGE", "REDACTED"): "REDACTED",
    ("SUPPORT_ATTACHMENT", "FOUND"): "FOUND", ("SUPPORT_ATTACHMENT", "NOT_FOUND"): "NOT_FOUND",
    ("ANALYTICS_PROFILE", "IDENTIFIABLE"): "IDENTIFIABLE", ("ANALYTICS_PROFILE", "ANONYMIZED"): "ANONYMIZED",
    ("USER_EXPORT", "FOUND"): "FOUND", ("USER_EXPORT", "NOT_FOUND"): "NOT_FOUND",
    ("DATA_FLOW", "ACTIVE"): "ACTIVE", ("DATA_FLOW", "DISABLED"): "DISABLED",
    ("BACKUP_ARCHIVE", "ACTIVE"): "ACTIVE", ("BACKUP_ARCHIVE", "BLOCKED"): "BLOCKED",
    ("SECURITY_AUDIT_LOG", "FOUND"): "FOUND", ("LEGAL_HOLD_RECORD", "FOUND"): "FOUND",
    ("ACCOUNT_TOMBSTONE", "IDENTIFIABLE"): "IDENTIFIABLE", ("ACCOUNT_TOMBSTONE", "REDACTED"): "REDACTED",
    ("MARKETING_PROFILE", "FOUND"): "FOUND", ("MARKETING_PROFILE", "NOT_FOUND"): "NOT_FOUND",
    ("SECONDARY_IDENTIFIER", "FOUND"): "FOUND", ("SECONDARY_IDENTIFIER", "NOT_FOUND"): "NOT_FOUND",
}


def _ledger_fact(file_id, t, resource_id, record_type, result, subject, src) -> Fact | None:
    state = LEDGER_STATE.get((record_type, result))
    if state is None:
        return None
    return Fact(file_id, t, resource_id, record_type, state, link_keys(subject), src)


def parse_ledger_json(file_id, d, captured_at):
    pf = []
    for r in d.get("records", []):
        f = _ledger_fact(file_id, r.get("recorded_at", captured_at), r["resource_id"], r["record_type"],
                         r["result"], r.get("subject_reference") or r.get("lookup_value"), "ledger.json")
        if f:
            pf.append(f)
    return pf


_TXT_ROW = re.compile(r"^-\s+(\S+)\s+\|\s+(\S+)\s+\|\s+(\S+)\s+\|\s+(\S+)\s+\|\s+(\S+)\s+\|\s+(.*?)\s*$")


def parse_handover_txt(file_id, text, captured_at):
    out = []
    for line in text.splitlines():
        m = _TXT_ROW.match(line)
        if m:
            t, _sys, rid, rtype, result, subj = m.groups()
            f = _ledger_fact(file_id, t, rid, rtype, result, subj, "handover.txt")
            if f:
                out.append(f)
    return out


# --------------------------------------------------------------------------------------------
# JSON bundles / exports
# --------------------------------------------------------------------------------------------
COLLECTION_CATEGORIES = {
    "customer_profiles": ["USER_PROFILE"], "customer_search_documents": ["SEARCH_INDEX_ENTRY"],
    "customer_analytics_reports": ["ANALYTICS_PROFILE"], "support_conversations": ["SUPPORT_MESSAGE"],
    "ticket_attachments": ["SUPPORT_ATTACHMENT"], "customer_export_jobs": ["USER_EXPORT"],
    "connector_configurations": ["DATA_FLOW"], "backup_catalog": ["BACKUP_ARCHIVE"],
    "security_audit_events": ["SECURITY_AUDIT_LOG"], "retained_order_records": ["LEGAL_HOLD_RECORD"],
    "deleted_customer_references": ["ACCOUNT_TOMBSTONE"],
}


def record_fact(file_id, t, collection, r, src) -> Fact | None:
    """One record of a collection (bundle / replica record_json / bespoke json) -> Fact."""
    rid = r.get("resource_id")
    if not rid:
        return None
    if collection == "customer_profiles":
        return Fact(file_id, t, rid, "USER_PROFILE", "FOUND",
                    link_keys(r.get("email"), r.get("phone"), r.get("customer_reference"), r.get("email_hash")), src)
    if collection == "customer_search_documents":
        doc = r.get("document") or {}
        return Fact(file_id, t, rid, "SEARCH_INDEX_ENTRY", "FOUND",
                    link_keys(doc.get("email"), doc.get("phone"), doc.get("customer_reference"), doc.get("email_hash")), src)
    if collection == "customer_analytics_reports":
        ident = _has_value(r.get("user_id"), r.get("email"), r.get("phone"), r.get("email_hash"))
        return Fact(file_id, t, rid, "ANALYTICS_PROFILE", "IDENTIFIABLE" if ident else "ANONYMIZED",
                    link_keys(r.get("user_id"), r.get("email"), r.get("phone"), r.get("email_hash")), src)
    if collection == "support_conversations":
        text = r.get("message_text") or ""
        ident = bool(EMAIL_RE.search(text)) or bool(PHONE_RE.search(text))
        return Fact(file_id, t, rid, "SUPPORT_MESSAGE", "IDENTIFIABLE" if ident else "REDACTED",
                    link_keys(r.get("subject_reference"), text), src)
    if collection == "ticket_attachments":
        return Fact(file_id, t, rid, "SUPPORT_ATTACHMENT", "FOUND", link_keys(r.get("uploaded_by")), src)
    if collection == "customer_export_jobs":
        avail = _truthy(r.get("download_available"))
        return Fact(file_id, t, rid, "USER_EXPORT", "NOT_FOUND" if avail is False else "FOUND",
                    link_keys(r.get("owner_email"), r.get("owner_phone")), src)
    if collection == "connector_configurations":
        en = _truthy(r.get("enabled"))
        return Fact(file_id, t, rid, "DATA_FLOW", "ACTIVE" if en else "DISABLED",
                    link_keys(r.get("subject_selector")), src)
    if collection == "backup_catalog":
        ra = _truthy(r.get("restore_allowed"))
        return Fact(file_id, t, rid, "BACKUP_ARCHIVE", "ACTIVE" if ra else "BLOCKED",
                    link_keys(r.get("subject_reference")), src)
    if collection == "security_audit_events":
        return Fact(file_id, t, rid, "SECURITY_AUDIT_LOG", "FOUND", link_keys(r.get("subject_reference")), src)
    if collection == "retained_order_records":
        return Fact(file_id, t, rid, "LEGAL_HOLD_RECORD", "FOUND", link_keys(r.get("subject_reference")), src)
    if collection == "deleted_customer_references":
        ident = _has_value(r.get("name"), r.get("email"), r.get("phone"), r.get("email_hash"))
        return Fact(file_id, t, rid, "ACCOUNT_TOMBSTONE", "IDENTIFIABLE" if ident else "REDACTED",
                    link_keys(r.get("subject_reference"), r.get("email"), r.get("phone"), r.get("email_hash")), src)
    return None


def parse_json_file(file_id, path: Path, captured_at) -> ParsedFile:
    d = json.loads(path.read_text(encoding="utf-8"))
    pf = ParsedFile(file_id, str(path), captured_at)
    if "snapshots" in d:                                   # snapshot bundle
        for s in d["snapshots"]:
            t = s.get("captured_at", captured_at)
            coll = s["collection"]
            if coll == "operational_record_history":
                pf.facts += [f for f in (
                    _ledger_fact(file_id, r.get("recorded_at", t), r["resource_id"], r["record_type"], r["result"],
                                 r.get("lookup_value"), "bundle.ledger") for r in s["records"]) if f]
                continue
            for c in COLLECTION_CATEGORIES.get(coll, []):
                pf.coverage.append(Coverage(file_id, t, c))
            for r in s["records"]:
                f = record_fact(file_id, t, coll, r, "bundle")
                if f:
                    pf.facts.append(f)
    elif "service_exports" in d:                           # service resource export (A family)
        pf = _parse_service_export(file_id, d, path, captured_at)
    elif "records" in d and d["records"] and "record_type" in d["records"][0]:   # ledger json
        pf.facts += parse_ledger_json(file_id, d, captured_at)
    elif "records" in d and d.get("collection"):           # bespoke single-collection reports
        coll = d["collection"]
        t = d.get("captured_at", captured_at)
        for c in COLLECTION_CATEGORIES.get(coll, []):
            pf.coverage.append(Coverage(file_id, t, c))
        for r in d["records"]:
            f = record_fact(file_id, t, coll, r, "report.json")
            if f:
                pf.facts.append(f)
    return pf


def _parse_service_export(file_id, d, path, captured_at) -> ParsedFile:
    pf = ParsedFile(file_id, str(path), captured_at)
    se = d["service_exports"]
    for r in se.get("account_service", {}).get("profile_lookups", []):
        t = r.get("observed_at", captured_at)
        prof = r.get("profile")
        found = prof is not None and r.get("status_code") == 200
        keys = link_keys(*(prof or {}).values()) if prof else ()
        pf.facts.append(Fact(file_id, t, r["resource_id"], "USER_PROFILE", "FOUND" if found else "NOT_FOUND", keys, "export.A"))
    for r in se.get("search_service", {}).get("index_queries", []):
        t = r.get("observed_at", captured_at)
        docs = (r.get("hits") or {}).get("documents") or []
        keys = link_keys(r.get("query"), *[x for doc in docs for x in (doc.get("email"), doc.get("customer_reference"), doc.get("phone"))])
        pf.facts.append(Fact(file_id, t, r["resource_id"], "SEARCH_INDEX_ENTRY", "FOUND" if docs else "NOT_FOUND", keys, "export.A"))
    for r in se.get("analytics_platform", {}).get("profiles", []):
        ident = _has_value(r.get("customer_reference"), r.get("email"), r.get("phone"), r.get("email_hash"))
        pf.facts.append(Fact(file_id, r.get("observed_at", captured_at), r["resource_id"], "ANALYTICS_PROFILE",
                             "IDENTIFIABLE" if ident else "ANONYMIZED",
                             link_keys(r.get("customer_reference"), r.get("email"), r.get("phone"), r.get("email_hash")), "export.A"))
    for r in se.get("backup_service", {}).get("restore_entries", []):
        pf.facts.append(Fact(file_id, r.get("observed_at", captured_at), r["resource_id"], "BACKUP_ARCHIVE",
                             "ACTIVE" if _truthy(r.get("restore_allowed")) else "BLOCKED",
                             link_keys(r.get("customer_reference"), r.get("customer_email")), "export.A"))
    for r in se.get("export_service", {}).get("exports", []):
        pf.facts.append(Fact(file_id, r.get("observed_at", captured_at), r["resource_id"], "USER_EXPORT", "FOUND",
                             link_keys(r.get("customer_reference"), r.get("owner_email"), r.get("owner_phone")), "export.A"))
    for r in se.get("integration_service", {}).get("connectors", []):
        pf.facts.append(Fact(file_id, r.get("observed_at", captured_at), r["resource_id"], "DATA_FLOW",
                             "ACTIVE" if _truthy(r.get("enabled")) else "DISABLED",
                             link_keys(r.get("customer_reference"), r.get("customer_email")), "export.A"))
    for r in se.get("security_service", {}).get("audit_records", []):
        pf.facts.append(Fact(file_id, r.get("observed_at", captured_at), r["resource_id"], "SECURITY_AUDIT_LOG", "FOUND",
                             link_keys(r.get("subject_reference")), "export.A"))
    for r in se.get("support_platform", {}).get("tickets", []):
        ident = _has_value(r.get("requester_email"), r.get("requester_name"), r.get("requester_phone"))
        pf.facts.append(Fact(file_id, r.get("observed_at", captured_at), r["resource_id"], "SUPPORT_MESSAGE",
                             "IDENTIFIABLE" if ident else "REDACTED",
                             link_keys(r.get("customer_reference"), r.get("requester_email"), r.get("requester_phone")), "export.A"))
    return pf


# --------------------------------------------------------------------------------------------
# SQL snapshots
# --------------------------------------------------------------------------------------------
_HDR_CAPTURED = re.compile(r"--\s*Captured at:\s*(\S+)")
ORIGIN_COLLECTION = {  # snapshot_scope origin_system -> categories enumerated by the inventory tables
    "account_service": ["USER_PROFILE"], "search_service": ["SEARCH_INDEX_ENTRY"],
    "analytics_platform": ["ANALYTICS_PROFILE"], "support_platform": ["SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT"],
    "export_service": ["USER_EXPORT"], "integration_service": ["DATA_FLOW"],
    "backup_service": ["BACKUP_ARCHIVE"], "security_service": ["SECURITY_AUDIT_LOG"],
}


def parse_sql_file(file_id, path: Path, captured_at) -> ParsedFile:
    text = path.read_text(encoding="utf-8")
    m = _HDR_CAPTURED.search(text)
    t_file = m.group(1) if m else captured_at
    pf = ParsedFile(file_id, str(path), captured_at)
    con = sqlite3.connect(":memory:")
    con.executescript(text)
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]

    scope: dict[str, str] = {}
    if "snapshot_scope" in tables:
        scope = dict(con.execute("select origin_system, captured_at from snapshot_scope"))
        for origin, ts in scope.items():
            for c in ORIGIN_COLLECTION.get(origin, []):
                pf.coverage.append(Coverage(file_id, ts, c))

    def rows(table):
        cur = con.execute(f'select * from "{table}"')
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    for t in tables:
        if t == "snapshot_scope":
            continue
        rs = rows(t)
        cols = rs[0].keys() if rs else [r[1] for r in con.execute(f'pragma table_info("{t}")')]
        if "record_json" in cols:
            seen_cats: set[str] = set()
            for r in rs:
                rec = json.loads(r["record_json"])
                coll = r["collection_name"]
                for c in COLLECTION_CATEGORIES.get(coll, []):
                    seen_cats.add(c)
                f = record_fact(file_id, r.get("updated_at") or t_file, coll, rec, f"sql.{t}")
                if f:
                    pf.facts.append(f)
            for c in seen_cats:
                pf.coverage.append(Coverage(file_id, t_file, c))
        elif t.startswith("customer_profiles_") or t == "customer_profiles":
            pf.coverage.append(Coverage(file_id, scope.get("account_service", t_file), "USER_PROFILE"))
            for r in rs:
                pf.facts.append(Fact(file_id, scope.get("account_service", t_file), r["resource_id"], "USER_PROFILE", "FOUND",
                                     link_keys(r.get("email"), r.get("phone"), r.get("user_id") or r.get("customer_reference"),
                                               r.get("email_hash")), f"sql.{t}"))
        elif t == "customer_search_documents":
            for r in rs:
                pf.facts.append(Fact(file_id, scope.get("search_service", t_file), r["resource_id"], "SEARCH_INDEX_ENTRY", "FOUND",
                                     link_keys(r.get("email"), r.get("phone"), r.get("customer_reference"), r.get("email_hash")), f"sql.{t}"))
        elif t == "search_documents_primary":
            pf.coverage.append(Coverage(file_id, t_file, "SEARCH_INDEX_ENTRY"))
            for r in rs:
                src_res = r.get("source_resource_id")
                pf.facts.append(Fact(file_id, t_file, r["resource_id"], "SEARCH_INDEX_ENTRY", "FOUND",
                                     link_keys(r.get("email")), f"sql.{t}", (src_res,) if src_res else ()))
        elif t == "customer_analytics_profiles":
            for r in rs:
                ident = _has_value(r.get("customer_reference"), r.get("email"), r.get("phone"), r.get("email_hash"))
                pf.facts.append(Fact(file_id, scope.get("analytics_platform", t_file), r["resource_id"], "ANALYTICS_PROFILE",
                                     "IDENTIFIABLE" if ident else "ANONYMIZED",
                                     link_keys(r.get("customer_reference"), r.get("email"), r.get("phone"), r.get("email_hash")), f"sql.{t}"))
        elif t == "support_records":
            for r in rs:
                ident = _has_value(r.get("requester_name"), r.get("requester_email"), r.get("requester_phone"))
                pf.facts.append(Fact(file_id, scope.get("support_platform", t_file), r["resource_id"], "SUPPORT_MESSAGE",
                                     "IDENTIFIABLE" if ident else "REDACTED",
                                     link_keys(r.get("customer_reference"), r.get("requester_email"), r.get("requester_phone")), f"sql.{t}"))
        elif t == "customer_exports":
            for r in rs:
                pf.facts.append(Fact(file_id, scope.get("export_service", t_file), r["resource_id"], "USER_EXPORT", "FOUND",
                                     link_keys(r.get("customer_reference"), r.get("owner_email"), r.get("owner_phone")), f"sql.{t}"))
        elif t == "connector_subscriptions":
            for r in rs:
                pf.facts.append(Fact(file_id, scope.get("integration_service", t_file), r["resource_id"], "DATA_FLOW",
                                     "ACTIVE" if _truthy(r.get("enabled")) else "DISABLED",
                                     link_keys(r.get("customer_reference"), r.get("customer_email")), f"sql.{t}"))
        elif t == "backup_restore_entries":
            for r in rs:
                pf.facts.append(Fact(file_id, scope.get("backup_service", t_file), r["resource_id"], "BACKUP_ARCHIVE",
                                     "ACTIVE" if _truthy(r.get("restore_allowed")) else "BLOCKED",
                                     link_keys(r.get("customer_reference"), r.get("customer_email")), f"sql.{t}"))
        elif t == "security_audit_records":
            for r in rs:
                pf.facts.append(Fact(file_id, scope.get("security_service", t_file), r["resource_id"], "SECURITY_AUDIT_LOG", "FOUND",
                                     link_keys(r.get("subject_reference")), f"sql.{t}"))
    con.close()
    return pf


# --------------------------------------------------------------------------------------------
# logs
# --------------------------------------------------------------------------------------------
_KV = re.compile(r'([A-Za-z_]\w*)=("(?:[^"\\]|\\.)*"|[^\s"]+)')
_TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)\s*(.*)$")
_BRACKET = re.compile(r"^\[(\w+)\] \[(\w+)\] \[([\w-]+)\] (\w+): (.*)$")
_PIPE = re.compile(r"^\|?\s*(\w+) \| (\w+) \| ([\w-]+) \| (\w+) \| (.*)$")
KEY_FIELDS = ("lookup_key", "match_key", "subject_key", "subject_ref", "correlation_key", "scan_key", "owner_key")


def _unq(v: str) -> str:
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1].replace('\\"', '"')
    return v


def parse_log_line(line: str) -> dict | None:
    m = _TS.match(line.strip())
    if not m:
        return None
    ts, rest = m.groups()
    d = {"ts": ts}
    if rest.startswith("{"):
        try:
            d.update({k: ("" if v is None else str(v)) for k, v in json.loads(rest).items()})
            return d
        except json.JSONDecodeError:
            pass
    mb = _BRACKET.match(rest)
    if mb:
        d.update(level=mb[1], service=mb[2], trace_id=mb[3], event=mb[4])
        rest = mb[5]
    mp = _PIPE.match(rest)
    if mp:
        d.update(level=mp[1], service=mp[2], trace_id=mp[3], event=mp[4])
        rest = mp[5]
    for k, v in _KV.findall(rest):
        v = _unq(v)
        if k == "message":
            for k2, v2 in _KV.findall(v):
                d[k2] = _unq(v2)
        else:
            d[k] = v
    return d


def _null(v):
    return None if v in (None, "", "null", "None") else v


def parse_log_file(file_id, path: Path, captured_at) -> ParsedFile:
    pf = ParsedFile(file_id, str(path), captured_at)
    lines = [d for d in (parse_log_line(l) for l in path.read_text(encoding="utf-8").splitlines()) if d]
    by_trace: dict[str, list[dict]] = {}
    for d in lines:
        if d.get("trace_id"):
            by_trace.setdefault(d["trace_id"], []).append(d)

    def trace_keys(d) -> tuple[str, ...]:
        vals = [d.get(k) for k in KEY_FIELDS]
        for x in by_trace.get(d.get("trace_id", ""), []):
            vals += [x.get(k) for k in KEY_FIELDS]
        return link_keys(*(_null(v) for v in vals))

    for d in lines:
        ev, rid, t = d.get("event", ""), d.get("resource_id"), d["ts"]
        if ev == "record_lookup" and rid:                       # ledger-style log lines
            f = _ledger_fact(file_id, t, rid, d.get("record_type", ""), d.get("result", ""), d.get("subject_reference"), "log.ledger")
            if f:
                pf.facts.append(f)
            continue
        if not rid:
            continue
        cat = category_of(rid)
        if ev == "profile_lookup_completed":
            found = d.get("rows") not in ("0",) and d.get("http_status") != "404"
            keys = link_keys(d.get("email"), d.get("phone"), d.get("customer_reference")) + trace_keys(d)
            pf.facts.append(Fact(file_id, t, rid, "USER_PROFILE", "FOUND" if found else "NOT_FOUND", tuple(dict.fromkeys(keys)), "log"))
        elif ev == "index_query_completed":
            hit = d.get("result") == "hit"
            keys = link_keys(d.get("email"), d.get("customer_reference")) + trace_keys(d)
            pf.facts.append(Fact(file_id, t, rid, "SEARCH_INDEX_ENTRY", "FOUND" if hit else "NOT_FOUND", tuple(dict.fromkeys(keys)), "log"))
        elif ev == "support_ticket_read_completed":
            ident = _has_value(d.get("requester_email"), d.get("requester_name"), d.get("requester_phone"))
            keys = link_keys(d.get("customer_reference"), d.get("requester_email"), d.get("requester_phone")) + trace_keys(d)
            pf.facts.append(Fact(file_id, t, rid, "SUPPORT_MESSAGE", "IDENTIFIABLE" if ident else "REDACTED", tuple(dict.fromkeys(keys)), "log"))
        elif ev == "message_pii_scan":
            pf.facts.append(Fact(file_id, t, rid, "SUPPORT_MESSAGE", "IDENTIFIABLE", link_keys(d.get("matched_value")) + trace_keys(d), "log"))
        elif ev == "message_read":
            ident = bool(EMAIL_RE.search(d.get("message_text", "")))
            pf.facts.append(Fact(file_id, t, rid, "SUPPORT_MESSAGE", "IDENTIFIABLE" if ident else "REDACTED",
                                 link_keys(d.get("subject_ref"), d.get("message_text")), "log"))
        elif ev == "attachment_pii_scan":
            pf.facts.append(Fact(file_id, t, rid, "SUPPORT_ATTACHMENT", "FOUND", link_keys(d.get("matched_value")) + trace_keys(d), "log"))
        elif ev == "analytics_profile_read_completed":
            ident = _has_value(d.get("customer_reference"), d.get("email"), d.get("phone"), d.get("email_hash"))
            keys = link_keys(d.get("customer_reference"), d.get("email"), d.get("phone"), d.get("email_hash")) + trace_keys(d)
            pf.facts.append(Fact(file_id, t, rid, "ANALYTICS_PROFILE", "IDENTIFIABLE" if ident else "ANONYMIZED", tuple(dict.fromkeys(keys)), "log"))
        elif ev in ("analytics_profile_read", "analytics_identity_scan"):
            n = d.get("direct_identifiers")
            ident = (n not in (None, "0")) or _has_value(d.get("email"), d.get("phone"), d.get("matched_value"))
            keys = link_keys(d.get("email"), d.get("phone"), d.get("matched_value")) + trace_keys(d)
            pf.facts.append(Fact(file_id, t, rid, "ANALYTICS_PROFILE", "IDENTIFIABLE" if ident else "ANONYMIZED", tuple(dict.fromkeys(keys)), "log"))
        elif ev in ("connector_config_read_completed", "connector_heartbeat", "connector_config_loaded"):
            en = _truthy(d.get("enabled"))
            keys = link_keys(d.get("customer_email"), d.get("customer_reference")) + trace_keys(d)
            if en is not None:
                pf.facts.append(Fact(file_id, t, rid, "DATA_FLOW", "ACTIVE" if en else "DISABLED", tuple(dict.fromkeys(keys)), "log"))
        elif ev == "restore_policy_read_completed":
            ra = _truthy(d.get("restore_allowed"))
            keys = link_keys(d.get("customer_email"), d.get("customer_reference")) + trace_keys(d)
            if ra is not None:
                pf.facts.append(Fact(file_id, t, rid, "BACKUP_ARCHIVE", "ACTIVE" if ra else "BLOCKED", tuple(dict.fromkeys(keys)), "log"))
        elif ev == "audit_record_read_completed":
            keys = link_keys(d.get("subject_reference"), d.get("correlation_key")) + trace_keys(d)
            pf.facts.append(Fact(file_id, t, rid, "SECURITY_AUDIT_LOG", "FOUND", tuple(dict.fromkeys(keys)), "log"))
        elif ev == "restore_candidate_evaluated":
            risky = _truthy(d.get("eligible")) and not _truthy(d.get("deletion_block"))
            pf.facts.append(Fact(file_id, t, rid, "BACKUP_ARCHIVE", "ACTIVE" if risky else "BLOCKED", trace_keys(d), "log"))
        elif ev == "restore_authorization_completed":
            allowed = (d.get("decision") or "").lower() in ("allow", "allowed", "grant", "granted", "permit")
            pf.facts.append(Fact(file_id, t, rid, "BACKUP_ARCHIVE", "ACTIVE" if allowed else "BLOCKED", trace_keys(d), "log"))
        elif ev == "export_metadata_read_completed":
            keys = link_keys(d.get("owner_email")) + trace_keys(d)
            avail = _truthy(d.get("available"))
            pf.facts.append(Fact(file_id, t, rid, "USER_EXPORT", "NOT_FOUND" if avail is False else "FOUND",
                                 tuple(dict.fromkeys(keys)), "log"))
        elif ev == "export_download_check_completed":
            avail = _truthy(d.get("available"))
            pf.facts.append(Fact(file_id, t, rid, "USER_EXPORT", "NOT_FOUND" if avail is False else "FOUND",
                                 trace_keys(d), "log"))
        elif ev in ("contact_lookup_completed", "contact_query_completed"):
            # a legacy contact index entry reachable through an old identifier: SECONDARY_IDENTIFIER (DELETE)
            found = d.get("rows") not in ("0", None)
            keys = link_keys(d.get("correlation_key"), d.get("lookup_key")) + trace_keys(d)
            pf.facts.append(Fact(file_id, t, rid, "SECONDARY_IDENTIFIER", "FOUND" if found else "NOT_FOUND",
                                 tuple(dict.fromkeys(keys)), "log"))
    return pf


# --------------------------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------------------------
class EvidenceStore:
    """All parsed evidence plus the manifest. Visual evidence (PDF/PNG) is merged from a facts cache."""

    def __init__(self, dataset: Path, visual_facts: Path | None = None):
        self.dataset = Path(dataset)
        self.manifest: dict[str, dict] = {}
        with open(self.dataset / "evidence_files.csv", newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                self.manifest[r["file_id"]] = r
        self.files: dict[str, ParsedFile] = {}
        for fid, m in self.manifest.items():
            p = self.dataset / m["file_path"]
            ext = p.suffix.lower()
            if ext == ".json":
                pf = parse_json_file(fid, p, m["captured_at"])
            elif ext == ".sql":
                pf = parse_sql_file(fid, p, m["captured_at"])
            elif ext == ".log":
                pf = parse_log_file(fid, p, m["captured_at"])
            elif ext == ".txt":
                pf = ParsedFile(fid, str(p), m["captured_at"])
                pf.facts = parse_handover_txt(fid, p.read_text(encoding="utf-8"), m["captured_at"])
            else:
                pf = ParsedFile(fid, str(p), m["captured_at"])
            self.files[fid] = pf
        if visual_facts and Path(visual_facts).exists():
            self._merge_visual(json.loads(Path(visual_facts).read_text(encoding="utf-8")))

    def _merge_visual(self, data: dict):
        for fid, entry in data.get("files", {}).items():
            pf = self.files.get(fid)
            if pf is None:
                continue
            for f in entry.get("facts", []):
                pf.facts.append(Fact(fid, f["t"], f["resource_id"], f["category"], f["state"],
                                     link_keys(*f.get("keys", [])), "visual"))

    def captured_at(self, file_id: str) -> str:
        return self.manifest[file_id]["captured_at"]

    def all_facts(self):
        for pf in self.files.values():
            yield from pf.facts

    def all_coverage(self):
        for pf in self.files.values():
            yield from pf.coverage
