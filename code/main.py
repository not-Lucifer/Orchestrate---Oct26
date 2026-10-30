"""Entry point:  python code/main.py  [--requests dataset/deletion_requests.csv] [--out output.csv]

Reads the participant-facing files in dataset/ and writes output.csv (one row per request,
sorted by case_id) at the repository root. Everything is deterministic; the LLM is optional.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from deletion_audit.assessor import RealAssessor  # noqa: E402
from deletion_audit.pipeline import run  # noqa: E402
from deletion_audit.planner import Convention  # noqa: E402
from deletion_audit.validator import validate_citations, validate_output  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(REPO_ROOT / "dataset"))
    ap.add_argument("--requests", default=None, help="default: <dataset>/deletion_requests.csv")
    ap.add_argument("--out", default=str(REPO_ROOT / "output.csv"))
    ap.add_argument("--visual-facts", default=str(CODE_DIR / "data" / "visual_facts.json"))
    ap.add_argument("--llm-intent", action="store_true", help="optional: LLM second opinion for low-confidence intent (needs ANTHROPIC_API_KEY)")
    a = ap.parse_args(argv)
    requests = a.requests or str(Path(a.dataset) / "deletion_requests.csv")

    llm = None
    if a.llm_intent:
        from deletion_audit.llm import LLM
        llm = LLM(REPO_ROOT / ".cache" / "llm", CODE_DIR / "evaluation" / "ledger.jsonl")
    assessor = RealAssessor(a.dataset, a.visual_facts, llm)
    results = run(requests, a.out, assessor, Convention())
    counts = {s: sum(r.status == s for r in results) for s in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")}
    warns = [(r.case_id, w) for r in results for w in r.warnings] + [("-", w) for w in assessor.warnings]
    for cid, w in warns:
        print(f"WARN {cid}: {w}", file=sys.stderr)
    print(f"wrote {a.out}: {len(results)} rows {counts}; {len(warns)} warnings")
    errs = validate_output(requests, a.out) + validate_citations(requests, a.out, Path(a.dataset) / "evidence_files.csv")
    print("validation:", "OK" if not errs else f"{len(errs)} problems")
    for e in errs[:10]:
        print("  ", e)
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
