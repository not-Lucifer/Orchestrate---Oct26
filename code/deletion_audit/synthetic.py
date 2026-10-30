"""Team-authored evaluation cases (planner-level) + the runner that scores them."""
from __future__ import annotations

import json
from pathlib import Path

from .models import (
    CaseAssessment, FlowAssessment, RecordState, ResourceAssessment, RestoreAssessment, Treatment,
)
from .ops import OP_STATE
from .planner import Convention, build_result
from .scoring import render_markdown, score
from .validator import validate_steps


def assessment_from_dict(d: dict) -> CaseAssessment:
    return CaseAssessment(
        case_id=d["case_id"], deletion_requested=d["deletion_requested"],
        resources=[ResourceAssessment(r["system_id"], r["resource_id"], Treatment(r["treatment"]),
                                      RecordState(r["state"]), r.get("evidence_id", ""))
                   for r in d.get("resources", [])],
        flows=[FlowAssessment(**f) for f in d.get("flows", [])],
        restores=[RestoreAssessment(**x) for x in d.get("restores", [])])


def _expected_steps(rows: list[list[str]]) -> list[dict]:
    return [{"step_no": i, "phase": ph, "system_id": sy, "resource_id": rs, "operation": op,
             "state": OP_STATE[op], "evidence_id": ev} for i, (ph, op, sy, rs, ev) in enumerate(rows, 1)]


def run_synthetic(path: str | Path, conv: Convention = Convention()) -> tuple[str, bool]:
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    pred, gold, lines, ok = {}, {}, [], True
    for c in cases:
        res = build_result(assessment_from_dict(c["assessment"]), conv)
        cid = c["assessment"]["case_id"]
        pred[cid] = (res.status, [s.to_dict() for s in res.steps])
        gold[cid] = (c["expected_status"], _expected_steps(c["expected_steps"]))
        problems = validate_steps(res.status, pred[cid][1])
        if len(res.warnings) != c.get("expected_warnings", 0):
            problems.append(f"expected {c.get('expected_warnings', 0)} warnings, got {res.warnings}")
        match = pred[cid] == gold[cid] and not problems
        ok &= match
        lines.append(f"- `{cid}` **{c['name']}** - {'PASS' if match else 'FAIL'}. {c['why']}"
                     + ("" if match else f" Problems: {problems}"))
    return "\n".join(lines) + "\n\n" + render_markdown(score(pred, gold), "Synthetic cases (planner level)"), ok
