"""Structural validation of output.csv against every rule in problem_statement.md.

Run before every submission. It cannot say an answer is *right*, only that it is *well-formed*
and internally consistent (each finding has a remediation, each remediation a check, ...).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .ops import (
    FINDING_TO_REMEDIATION, OP_PHASE, OP_STATE, REMEDIATION_TO_VERIFICATION, STATUSES,
    step_sort_key,
)

STEP_KEYS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}


def validate_steps(status: str, steps: list) -> list[str]:
    errs: list[str] = []
    if status == "NOT_APPLICABLE":
        return ["NOT_APPLICABLE must have steps_json == []"] if steps else []
    if not steps:
        return [f"{status} must have at least one step"]

    for i, s in enumerate(steps, start=1):
        if not isinstance(s, dict) or set(s) != STEP_KEYS:
            errs.append(f"step {i}: keys must be exactly {sorted(STEP_KEYS)}")
            continue
        if s["step_no"] != i:
            errs.append(f"step {i}: step_no is {s['step_no']}, expected {i}")
        op = s["operation"]
        if op not in OP_PHASE:
            errs.append(f"step {i}: unknown operation {op!r}")
            continue
        if s["phase"] != OP_PHASE[op]:
            errs.append(f"step {i}: phase {s['phase']} does not match operation {op}")
        if s["state"] != OP_STATE[op]:
            errs.append(f"step {i}: state {s['state']} does not match operation {op}")
        if not s["system_id"] or not s["resource_id"]:
            errs.append(f"step {i}: empty system_id/resource_id")

    if errs:
        return errs

    keys = [step_sort_key(s["phase"], s["operation"], s["system_id"], s["resource_id"]) for s in steps]
    if keys != sorted(keys):
        errs.append("steps are not in canonical order (phase, operation order, system_id, resource_id)")
    if len(set(keys)) != len(keys):
        errs.append("duplicate (phase, operation, system_id, resource_id) steps")

    phases = {s["phase"] for s in steps}
    if status == "COMPLETE":
        if phases != {"VERIFICATION"}:
            errs.append("COMPLETE must contain only VERIFICATION steps")
        errs += [f"step {s['step_no']}: COMPLETE verification must cite evidence_id"
                 for s in steps if not s["evidence_id"]]
    elif status == "INCOMPLETE":
        if "FINDING" not in phases or "REMEDIATION" not in phases:
            errs.append("INCOMPLETE must contain FINDING and REMEDIATION steps")
        for s in steps:
            if s["phase"] == "FINDING" and not s["evidence_id"]:
                errs.append(f"step {s['step_no']}: FINDING must cite evidence_id")
            if s["phase"] != "FINDING" and s["evidence_id"]:
                errs.append(f"step {s['step_no']}: {s['phase']} must have empty evidence_id")

        have = {(s["operation"], s["system_id"], s["resource_id"]) for s in steps}
        for s in steps:
            tgt = (s["system_id"], s["resource_id"])
            if s["phase"] == "FINDING":
                if not any((r, *tgt) in have for r in FINDING_TO_REMEDIATION[s["operation"]]):
                    errs.append(f"step {s['step_no']}: finding {s['operation']} {tgt} has no remediation")
            elif s["phase"] == "REMEDIATION":
                if (REMEDIATION_TO_VERIFICATION[s["operation"]], *tgt) not in have:
                    errs.append(f"step {s['step_no']}: remediation {s['operation']} {tgt} has no verification")
    return errs


def validate_output(requests_csv: str | Path, output_csv: str | Path) -> list[str]:
    with open(requests_csv, newline="", encoding="utf-8-sig") as fh:
        expected = [r["case_id"] for r in csv.DictReader(fh)]
    with open(output_csv, newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        if rd.fieldnames != ["case_id", "deletion_status", "steps_json"]:
            return [f"header must be case_id,deletion_status,steps_json (got {rd.fieldnames})"]
        rows = list(rd)

    errs: list[str] = []
    ids = [r["case_id"] for r in rows]
    if ids != sorted(ids):
        errs.append("rows are not sorted by case_id")
    if len(ids) != len(set(ids)):
        errs.append("duplicate case_id rows")
    if set(ids) != set(expected):
        errs.append(f"case_id mismatch: missing={sorted(set(expected) - set(ids))[:5]} "
                    f"extra={sorted(set(ids) - set(expected))[:5]}")
    if len(rows) != len(expected):
        errs.append(f"row count {len(rows)} != {len(expected)} requests")

    for r in rows:
        cid, status = r["case_id"], r["deletion_status"]
        if status not in STATUSES:
            errs.append(f"{cid}: invalid deletion_status {status!r}")
            continue
        try:
            steps = json.loads(r["steps_json"])
        except json.JSONDecodeError as e:
            errs.append(f"{cid}: steps_json is not valid JSON ({e})")
            continue
        if not isinstance(steps, list):
            errs.append(f"{cid}: steps_json must be a JSON array")
            continue
        errs += [f"{cid}: {e}" for e in validate_steps(status, steps)]
    return errs


def validate_citations(requests_csv: str | Path, output_csv: str | Path, manifest_csv: str | Path) -> list[str]:
    """Every cited evidence_id must exist in the manifest and have been captured at or before the
    case's audit_at ("never cite an evidence item captured after the case's audit_at")."""
    with open(manifest_csv, newline="", encoding="utf-8-sig") as fh:
        captured = {r["file_id"]: r["captured_at"] for r in csv.DictReader(fh)}
    with open(requests_csv, newline="", encoding="utf-8-sig") as fh:
        audit_at = {r["case_id"]: r["audit_at"] for r in csv.DictReader(fh)}
    errs: list[str] = []
    with open(output_csv, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            for st in json.loads(r["steps_json"]):
                ev = st["evidence_id"]
                if not ev:
                    continue
                if ev not in captured:
                    errs.append(f"{r['case_id']}: step {st['step_no']} cites unknown evidence {ev!r}")
                elif captured[ev] > audit_at.get(r["case_id"], "9999"):
                    errs.append(f"{r['case_id']}: step {st['step_no']} cites {ev} captured {captured[ev]} after audit_at")
    return errs
