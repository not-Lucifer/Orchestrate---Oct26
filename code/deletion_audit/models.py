"""Normalised in-memory model between "understanding the evidence" and "writing the plan".

The assessor (data/LLM side) fills a CaseAssessment. The planner (pure, deterministic)
turns it into the status + steps_json. Keeping this seam narrow means the plan format,
ordering and evidence-citation rules are tested independently of the messy inputs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Treatment(str, Enum):
    """What deletion_rules.csv requires for a record's data category."""
    DELETE = "DELETE"          # whole record must be gone
    REDACT = "REDACT"          # keep record (e.g. tombstone), strip direct identifiers
    ANONYMIZE = "ANONYMIZE"    # keep record, irreversibly unlink from the user
    RETAIN = "RETAIN"          # legal/policy retention: must still exist, permitted identifiers only


class RecordState(str, Enum):
    """State of a record at audit_at, after weighing evidence (not workflow claims)."""
    ABSENT = "ABSENT"
    INTACT = "INTACT"          # present and still carries direct identifiers
    REDACTED = "REDACTED"      # present, direct identifiers removed, may keep user_id
    ANONYMIZED = "ANONYMIZED"  # present, no longer linkable to the user


@dataclass(frozen=True)
class ResourceAssessment:
    system_id: str
    resource_id: str
    treatment: Treatment
    state: RecordState
    evidence_id: str = ""      # file_id / activity_id / audit_id that proves the state


@dataclass(frozen=True)
class FlowAssessment:
    """A sync/import/export/indexing process that can copy or recreate the user's data."""
    system_id: str
    resource_id: str
    active: bool
    evidence_id: str = ""


@dataclass(frozen=True)
class RestoreAssessment:
    """A backup / restore path that can bring deleted data back."""
    system_id: str
    resource_id: str
    blocked: bool
    evidence_id: str = ""


@dataclass
class CaseAssessment:
    case_id: str
    deletion_requested: bool
    resources: list[ResourceAssessment] = field(default_factory=list)
    flows: list[FlowAssessment] = field(default_factory=list)
    restores: list[RestoreAssessment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # identity chain etc., for audit trail only


@dataclass(frozen=True)
class Step:
    step_no: int
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditResult:
    case_id: str
    status: str
    steps: list[Step]
    warnings: list[str] = field(default_factory=list)
