"""Operation table from problem_statement.md ("Allowed Operations").

This is the single source of truth for phase/operation/state triples and for the
canonical step ordering. The row order below IS the required operation order.
"""
from __future__ import annotations

PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")

# (phase, operation, state) in the exact order the problem statement lists them.
OPERATION_TABLE: tuple[tuple[str, str, str], ...] = (
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
)

OP_PHASE = {op: phase for phase, op, _ in OPERATION_TABLE}
OP_STATE = {op: state for _, op, state in OPERATION_TABLE}
PHASE_RANK = {p: i for i, p in enumerate(PHASES)}
OP_RANK = {op: i for i, (_, op, _) in enumerate(OPERATION_TABLE)}

STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")

# Which remediation answers which finding, and which check proves each remediation.
FINDING_TO_REMEDIATION = {
    "REPORT_REMAINING_RECORD": ("DELETE_RECORD",),
    "REPORT_EXPOSED_PII": ("REDACT_RECORD", "ANONYMIZE_RECORD"),
    "REPORT_ACTIVE_DATA_FLOW": ("DISABLE_DATA_FLOW",),
    "REPORT_RESTORE_RISK": ("BLOCK_RESTORE",),
}
REMEDIATION_TO_VERIFICATION = {
    "DELETE_RECORD": "VERIFY_RECORD_ABSENT",
    "REDACT_RECORD": "VERIFY_RECORD_REDACTED",
    "ANONYMIZE_RECORD": "VERIFY_RECORD_ANONYMIZED",
    "DISABLE_DATA_FLOW": "VERIFY_DATA_FLOW_DISABLED",
    "BLOCK_RESTORE": "VERIFY_RESTORE_BLOCKED",
}


def step_sort_key(phase: str, operation: str, system_id: str, resource_id: str):
    """Order: phase, then operation order from the table, then system_id, resource_id ascending."""
    return (PHASE_RANK[phase], OP_RANK[operation], system_id, resource_id)
