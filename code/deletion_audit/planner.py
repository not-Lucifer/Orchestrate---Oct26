"""Deterministic planner: CaseAssessment -> (status, ordered steps).

No LLM and no I/O here. Everything the problem statement fixes (phase order, operation
order, evidence-citation rules, NOT_APPLICABLE == []) is implemented once, here.

Things the statement does NOT fix are exposed as `Convention` flags. They are meant to be
calibrated against sample_output.csv (see `cli.py conventions`) and then frozen by tests.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import (
    AuditResult, CaseAssessment, RecordState, ResourceAssessment, Step, Treatment,
)
from .ops import OP_PHASE, OP_STATE, REMEDIATION_TO_VERIFICATION, step_sort_key


@dataclass(frozen=True)
class Convention:
    # INCOMPLETE cases: which "checks that must pass afterward" are emitted.
    # Defaults are frozen from `python -m deletion_audit conventions` on dataset/sample_output.csv
    # (22 INCOMPLETE samples: every remediated target is verified, retained records get
    # VERIFY_RECORD_PRESENT, and already-compliant records/flows/backups are verified too).
    verify_remediated: bool = True            # a check for every remediation step
    verify_retained_present: bool = True      # VERIFY_RECORD_PRESENT for policy-retained records
    verify_already_clean: bool = True         # checks for items that were already compliant
    # COMPLETE cases always verify every relevant item (statement: "checks that prove it").
    # Tombstone (REDACT) records: also emit VERIFY_RECORD_PRESENT besides VERIFY_RECORD_REDACTED?
    redact_also_verify_present: bool = False


# Treatment -> (violating states, finding op, remediation op, verification op when compliant)
_VERIFY_FOR_TREATMENT = {
    Treatment.DELETE: "VERIFY_RECORD_ABSENT",
    Treatment.REDACT: "VERIFY_RECORD_REDACTED",
    Treatment.ANONYMIZE: "VERIFY_RECORD_ANONYMIZED",
    Treatment.RETAIN: "VERIFY_RECORD_PRESENT",
}


def _classify(r: ResourceAssessment) -> str:
    """Return 'violation' | 'ok' | 'missing_retained' for one record."""
    t, s = r.treatment, r.state
    if t is Treatment.DELETE:
        return "ok" if s is RecordState.ABSENT else "violation"
    if t is Treatment.RETAIN:
        return "missing_retained" if s is RecordState.ABSENT else "ok"
    if s is RecordState.ABSENT:
        return "missing_retained"                       # should have been kept (tombstone etc.)
    if t is Treatment.REDACT:
        return "violation" if s is RecordState.INTACT else "ok"
    # ANONYMIZE: a merely-redacted record still links to the user_id
    return "ok" if s is RecordState.ANONYMIZED else "violation"


def _violation_ops(r: ResourceAssessment) -> tuple[str, str]:
    """(finding op, remediation op) for a violating record."""
    if r.treatment is Treatment.DELETE:
        return "REPORT_REMAINING_RECORD", "DELETE_RECORD"
    if r.treatment is Treatment.REDACT:
        return "REPORT_EXPOSED_PII", "REDACT_RECORD"
    return "REPORT_EXPOSED_PII", "ANONYMIZE_RECORD"


def derive_status(a: CaseAssessment) -> str:
    if not a.deletion_requested:
        return "NOT_APPLICABLE"
    bad = (
        any(_classify(r) == "violation" for r in a.resources)
        or any(f.active for f in a.flows)
        or any(not x.blocked for x in a.restores)
    )
    return "INCOMPLETE" if bad else "COMPLETE"


def build_result(a: CaseAssessment, conv: Convention = Convention()) -> AuditResult:
    status = derive_status(a)
    warnings: list[str] = []
    if status == "NOT_APPLICABLE":
        return AuditResult(a.case_id, status, [], warnings)

    complete = status == "COMPLETE"
    raw: dict[tuple[str, str, str, str], tuple[str, str]] = {}   # key -> (state, evidence)

    def add(op: str, system_id: str, resource_id: str, evidence: str):
        raw.setdefault((OP_PHASE[op], op, system_id, resource_id), (OP_STATE[op], evidence))

    def add_check(op: str, system_id: str, resource_id: str, evidence: str):
        # COMPLETE: proof must cite evidence. INCOMPLETE: future check, evidence_id empty.
        if complete and not evidence:
            warnings.append(f"{op} {system_id}/{resource_id}: COMPLETE check has no evidence_id")
        add(op, system_id, resource_id, evidence if complete else "")

    for r in a.resources:
        kind = _classify(r)
        if kind == "missing_retained":
            warnings.append(
                f"{r.system_id}/{r.resource_id}: record that policy requires to keep is ABSENT "
                f"(no allowed operation can restore it) - review manually")
            continue
        if kind == "violation":
            finding, remediation = _violation_ops(r)
            add(finding, r.system_id, r.resource_id, r.evidence_id)
            add(remediation, r.system_id, r.resource_id, "")
            if conv.verify_remediated:
                add_check(REMEDIATION_TO_VERIFICATION[remediation],
                          r.system_id, r.resource_id, r.evidence_id)
            continue
        # compliant record
        wanted = complete or conv.verify_already_clean or (
            r.treatment is Treatment.RETAIN and conv.verify_retained_present)
        if wanted:
            add_check(_VERIFY_FOR_TREATMENT[r.treatment], r.system_id, r.resource_id, r.evidence_id)
            if r.treatment is Treatment.REDACT and conv.redact_also_verify_present:
                add_check("VERIFY_RECORD_PRESENT", r.system_id, r.resource_id, r.evidence_id)

    for f in a.flows:
        if f.active:
            add("REPORT_ACTIVE_DATA_FLOW", f.system_id, f.resource_id, f.evidence_id)
            add("DISABLE_DATA_FLOW", f.system_id, f.resource_id, "")
            if conv.verify_remediated:
                add_check("VERIFY_DATA_FLOW_DISABLED", f.system_id, f.resource_id, f.evidence_id)
        elif complete or conv.verify_already_clean:
            add_check("VERIFY_DATA_FLOW_DISABLED", f.system_id, f.resource_id, f.evidence_id)

    for x in a.restores:
        if not x.blocked:
            add("REPORT_RESTORE_RISK", x.system_id, x.resource_id, x.evidence_id)
            add("BLOCK_RESTORE", x.system_id, x.resource_id, "")
            if conv.verify_remediated:
                add_check("VERIFY_RESTORE_BLOCKED", x.system_id, x.resource_id, x.evidence_id)
        elif complete or conv.verify_already_clean:
            add_check("VERIFY_RESTORE_BLOCKED", x.system_id, x.resource_id, x.evidence_id)

    ordered = sorted(raw, key=lambda k: step_sort_key(*k))
    steps = [
        Step(i, phase, system_id, resource_id, op, raw[(phase, op, system_id, resource_id)][0],
             raw[(phase, op, system_id, resource_id)][1])
        for i, (phase, op, system_id, resource_id) in enumerate(ordered, start=1)
    ]
    return AuditResult(a.case_id, status, steps, warnings)
