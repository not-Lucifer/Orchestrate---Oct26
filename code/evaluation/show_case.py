"""Human-readable view of the plan produced for given case ids (debugging / interview aid).

    python code/evaluation/show_case.py case_34 case_61 [--sample]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from deletion_audit.assessor import RealAssessor  # noqa: E402
from deletion_audit.planner import Convention, build_result  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="+")
    ap.add_argument("--sample", action="store_true", help="read sample_deletion_requests.csv instead")
    a = ap.parse_args(argv)
    ds = REPO_ROOT / "dataset"
    with open(ds / ("sample_deletion_requests.csv" if a.sample else "deletion_requests.csv"), newline="", encoding="utf-8") as fh:
        reqs = list(csv.DictReader(fh))
    asr = RealAssessor(ds, CODE_DIR / "data" / "visual_facts.json")
    asr.prepare(reqs)
    for r in reqs:
        if r["case_id"] not in a.cases:
            continue
        ca = asr.assess(r)
        res = build_result(ca, Convention())
        print("=" * 100)
        print(r["case_id"], r["email"], "| reported", r["reported_status"], "| audit_at", r["audit_at"])
        print("  text:", r["request_text"][:150])
        print("  notes:", ca.notes)
        print("  status:", res.status, "| warnings:", res.warnings)
        for s in res.steps:
            print(f"   {s.step_no:>2} {s.phase[:4]} {s.operation:<26} {s.system_id}/{s.resource_id} [{s.evidence_id}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
