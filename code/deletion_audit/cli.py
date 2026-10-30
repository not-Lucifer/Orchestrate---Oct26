"""Command line entry point:  python -m deletion_audit <command> ...  (run with PYTHONPATH=src)"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .io_utils import read_csv
from .pipeline import load_assessor, run
from .planner import Convention
from .profile import conventions_from_file, profile_dataset
from .scoring import load_output, render_markdown, score
from .synthetic import run_synthetic
from .usage import build_usage_report
from .validator import validate_output


CODE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_DIR.parent
DS = str(REPO_ROOT / "dataset")
EV = str(CODE_DIR / "evaluation")


def _conv(path: str | None) -> Convention:
    if not path:
        return Convention()
    conv, report = conventions_from_file(path)
    print(report)
    return conv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deletion_audit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profile", help="profile dataset/ (schemas, enums, evidence types)")
    p.add_argument("--dataset", default=DS); p.add_argument("--out", default=str(CODE_DIR / "docs" / "DATASET_PROFILE.md"))

    p = sub.add_parser("conventions", help="infer planner conventions from labelled output")
    p.add_argument("--gold", default=DS + "/sample_output.csv")

    p = sub.add_parser("run", help="audit every request and write output.csv")
    p.add_argument("--requests", default=DS + "/deletion_requests.csv")
    p.add_argument("--out", default=str(REPO_ROOT / "output.csv"))
    p.add_argument("--assessor", required=True, help="package.module:ClassName")
    p.add_argument("--conventions-from", default=DS + "/sample_output.csv")

    p = sub.add_parser("validate", help="structural validation of output.csv")
    p.add_argument("--requests", default=DS + "/deletion_requests.csv"); p.add_argument("--output", default=str(REPO_ROOT / "output.csv"))

    p = sub.add_parser("score", help="score a prediction file against labelled output")
    p.add_argument("--pred", required=True); p.add_argument("--gold", default=DS + "/sample_output.csv")

    p = sub.add_parser("eval-synthetic", help="run team-authored planner-level cases")
    p.add_argument("--cases", default=EV + "/cases/synthetic_cases.json")

    p = sub.add_parser("eval-report", help="write evaluation/evaluation_report.md")
    p.add_argument("--pred", help="prediction file for the labelled sample requests (optional)")
    p.add_argument("--gold", default=DS + "/sample_output.csv")
    p.add_argument("--cases", default=EV + "/cases/synthetic_cases.json")
    p.add_argument("--failures", default=EV + "/failures_and_improvements.md")
    p.add_argument("--out", default=EV + "/evaluation_report.md")

    p = sub.add_parser("usage-report", help="write evaluation/usage_report.md from the LLM ledger")
    p.add_argument("--ledger", default=EV + "/ledger.jsonl"); p.add_argument("--cases", type=int, required=True)
    p.add_argument("--config", default=str(CODE_DIR / "config" / "config.toml")); p.add_argument("--out", default=EV + "/usage_report.md")

    a = ap.parse_args(argv)

    if a.cmd == "profile":
        md = profile_dataset(a.dataset)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(md)
    elif a.cmd == "conventions":
        print(conventions_from_file(a.gold)[1])
    elif a.cmd == "run":
        conv = _conv(a.conventions_from if Path(a.conventions_from).exists() else None)
        res = run(a.requests, a.out, load_assessor(a.assessor), conv)
        warn = [(r.case_id, w) for r in res for w in r.warnings]
        for cid, w in warn:
            print(f"WARN {cid}: {w}", file=sys.stderr)
        counts = {s: sum(r.status == s for r in res) for s in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")}
        print(f"wrote {a.out}: {len(res)} rows {counts}, {len(warn)} warnings")
    elif a.cmd == "validate":
        errs = validate_output(a.requests, a.output)
        print("\n".join(errs) if errs else f"OK: {a.output} is well-formed")
        return 1 if errs else 0
    elif a.cmd == "score":
        print(render_markdown(score(load_output(a.pred), load_output(a.gold)), "Sample score"))
    elif a.cmd == "eval-synthetic":
        md, ok = run_synthetic(a.cases)
        print(md)
        return 0 if ok else 1
    elif a.cmd == "eval-report":
        parts = ["# Evaluation Report", ""]
        if a.pred:
            gold = load_output(a.gold)
            pred = {k: v for k, v in load_output(a.pred).items() if k in gold}
            parts += ["## 1. Labelled sample requests (`sample_output.csv`)", "",
                      render_markdown(score(pred, gold), "Sample requests"), ""]
        else:
            parts += ["## 1. Labelled sample requests", "", "_Not run: pass `--pred` with predictions for the sample requests._", ""]
        md, ok = run_synthetic(a.cases)
        parts += ["## 2. Additional team-authored cases", "", md, ""]
        f = Path(a.failures)
        parts += ["## 3. Failures found and improvements made", "",
                  f.read_text(encoding="utf-8") if f.exists() else "_(none logged yet)_", ""]
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text("\n".join(parts), encoding="utf-8")
        print(f"wrote {a.out}")
        return 0 if ok else 1
    elif a.cmd == "usage-report":
        cfg = tomllib.loads(Path(a.config).read_text(encoding="utf-8"))
        md = build_usage_report(a.ledger, a.cases, cfg.get("pricing", {}), cfg.get("provider", "Anthropic"))
        Path(a.out).write_text(md, encoding="utf-8")
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
