"""CSV helpers and output.csv serialisation."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import AuditResult

OUTPUT_COLUMNS = ["case_id", "deletion_status", "steps_json"]


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def steps_to_json(result: AuditResult) -> str:
    return json.dumps([s.to_dict() for s in result.steps], separators=(",", ":"), ensure_ascii=False)


def write_output(results: list[AuditResult], path: str | Path) -> None:
    """Exactly one row per case, sorted by case_id (statement requirement)."""
    rows = sorted(results, key=lambda r: r.case_id)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(OUTPUT_COLUMNS)
        for r in rows:
            w.writerow([r.case_id, r.status, steps_to_json(r)])
