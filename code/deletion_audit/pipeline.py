"""Glue: requests -> assessor -> planner -> output.csv.

The assessor is the only dataset-specific component. It implements:

    class Assessor:
        def assess(self, request: dict[str, str]) -> CaseAssessment: ...

(`request` is one row of deletion_requests.csv.) Everything downstream is schema-independent.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Protocol

from .io_utils import read_csv, write_output
from .models import AuditResult, CaseAssessment
from .planner import Convention, build_result


class Assessor(Protocol):
    def assess(self, request: dict[str, str]) -> CaseAssessment: ...


def load_assessor(spec: str, **kwargs) -> Assessor:
    """spec = 'package.module:ClassName'"""
    mod, _, cls = spec.partition(":")
    return getattr(importlib.import_module(mod), cls)(**kwargs)


def run(requests_csv: str | Path, output_csv: str | Path, assessor: Assessor,
        conv: Convention = Convention()) -> list[AuditResult]:
    results: list[AuditResult] = []
    requests = read_csv(requests_csv)
    if hasattr(assessor, "prepare"):          # optional whole-batch pre-pass (cross-case elimination)
        assessor.prepare(requests)
    for req in requests:
        try:
            results.append(build_result(assessor.assess(req), conv))
        except Exception as e:      # one bad case must never sink the 518-row file
            results.append(AuditResult(req["case_id"], "INCOMPLETE", [], [f"ASSESSOR FAILED: {e!r}"]))
    write_output(results, output_csv)
    return results
