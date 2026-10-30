"""Evaluation harness.

    python code/evaluation/main.py            # score the 32 labelled sample requests
    python code/evaluation/main.py --diff     # ... and print gold-vs-predicted steps for each failing case
    python code/evaluation/main.py --report   # (re)write evaluation_report.md and usage_report.md from live runs

Sample answers (`dataset/sample_output.csv`) are used ONLY here, for measurement. The production
pipeline (`code/main.py`) never reads them.
"""
from __future__ import annotations

import argparse
import io
import sys
import tempfile
import tomllib
import unittest
from collections import Counter
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
CODE_DIR = EVAL_DIR.parent
REPO_ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))
sys.path.insert(0, str(CODE_DIR / "tests"))

from deletion_audit.assessor import RealAssessor  # noqa: E402
from deletion_audit.io_utils import read_csv  # noqa: E402
from deletion_audit.pipeline import run  # noqa: E402
from deletion_audit.planner import Convention  # noqa: E402
from deletion_audit.profile import infer_convention  # noqa: E402
from deletion_audit.scoring import load_output, render_markdown, score  # noqa: E402
from deletion_audit.usage import build_usage_report  # noqa: E402
from deletion_audit.validator import validate_citations, validate_output  # noqa: E402

VISUAL = CODE_DIR / "data" / "visual_facts.json"


def run_sample(dataset: Path, out: Path):
    assessor = RealAssessor(dataset, VISUAL)
    results = run(dataset / "sample_deletion_requests.csv", out, assessor, Convention())
    return assessor, results


def fmt(steps):
    return [f"{s['phase'][:4]} {s['operation']:<26} {s['system_id']}/{s['resource_id']} [{s['evidence_id']}]" for s in steps]


# ----------------------------------------------------------------------------------------------
# report sections
# ----------------------------------------------------------------------------------------------
SCENARIO_NOTES = {
    "test_s1_historical_email_finds_record_under_old_identifier":
        "S1 historical identifier: request uses the OLD email; a search entry indexed under it must still be found",
    "test_s2_evidence_after_audit_at_is_ignored":
        "S2 resurrection after audit_at: later evidence shows the account active again; it must not change the answer or be cited",
    "test_s3_non_deletion_request_is_not_applicable":
        "S3 access request (\"do not delete anything\") -> NOT_APPLICABLE with []",
    "test_s4_look_alike_identity_is_not_linked":
        "S4 look-alike person (dan.silva.jr vs dan.silva) must not be merged",
    "test_s5_reported_complete_but_evidence_says_otherwise":
        "S5 workflow says COMPLETE and every activity says SUCCESS, evidence shows identifiable analytics + live flow + restorable backup",
    "test_s6_identifier_free_accounts_get_distinct_resources":
        "S6 two identifier-free deletions in one batch must be attributed to distinct accounts",
    "test_s7_attachment_rendered_as_ticket_row_is_still_an_attachment":
        "S7 an attachment also shown as a plain ticket row in a later snapshot is still an attachment (DELETE, not REDACT)",
    "test_output_is_independent_of_python_hash_seed": "Determinism across processes: PYTHONHASHSEED 1/2/3 give byte-identical output",
    "test_deterministic": "Determinism: two runs give byte-identical output.csv",
    "test_output_is_valid": "Output of the scenario run satisfies every format rule",
}


def scenario_table() -> tuple[str, bool]:
    import test_pipeline_scenarios as t
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(t.ScenarioTests)
    names = sorted(test._testMethodName for test in suite)            # a TestSuite empties itself when run
    result = unittest.TestResult()
    suite.run(result)
    bad = {str(x[0]).split()[0] for x in result.failures + result.errors}
    rows = ["| # | Scenario (what the case probes) | Result |", "| --- | --- | --- |"]
    for i, name in enumerate(names, 1):
        rows.append(f"| {i} | {SCENARIO_NOTES.get(name, name)} | {'FAIL' if name in bad else 'PASS'} |")
    return "\n".join(rows), not bad


def planner_cases() -> tuple[str, bool]:
    from deletion_audit.synthetic import run_synthetic
    return run_synthetic(CODE_DIR / "evaluation" / "cases" / "synthetic_cases.json")


def whole_dataset(dataset: Path) -> tuple[str, dict]:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "output.csv"
        asr = RealAssessor(dataset, VISUAL)
        reqs = read_csv(dataset / "deletion_requests.csv")
        results = run(dataset / "deletion_requests.csv", out, asr, Convention())
        errs = validate_output(dataset / "deletion_requests.csv", out) + validate_citations(
            dataset / "deletion_requests.csv", out, dataset / "evidence_files.csv")
    counts = Counter(r.status for r in results)
    plans = asr.plans
    guessed = sum(any(v == "activity-guess" for v in p.resources.values()) for p in plans.values())
    unanchored = sum(1 for p in plans.values() if p.deletion and p.anchor is None)
    no_acct = sum(1 for r in results if r.status != "NOT_APPLICABLE" and not any(s.system_id == "account_service" for s in r.steps))
    no_audit = sum(1 for r in results if r.status != "NOT_APPLICABLE" and not any(s.system_id == "security_service" for s in r.steps))
    md = "\n".join([
        f"- Rows: **{len(results)}** (COMPLETE {counts['COMPLETE']}, INCOMPLETE {counts['INCOMPLETE']}, NOT_APPLICABLE {counts['NOT_APPLICABLE']})",
        f"- Format + citation validation (`validator.py`): **{'OK' if not errs else f'{len(errs)} problems'}** "
        "(518 rows, sorted, valid JSON, step order, consecutive step numbers, every cited `evidence_id` exists and was captured at or before that case's `audit_at`)",
        f"- Cases whose evidence anchor file was found: **{sum(1 for p in plans.values() if p.anchor)}** / {sum(1 for p in plans.values() if p.deletion)}; "
        f"no anchor (resolved from catalog/visual facts or empty): {unanchored}",
        f"- Cases where an identifier-free account/analytics record had to be chosen among equally plausible activity records: **{guessed}** "
        "(the dataset contains no information to resolve these; they are the main source of expected loss)",
        f"- Cases with no account_service step: {no_acct}; with no security_service (retained audit record) step: {no_audit} "
        "(the retained audit record is simply not present in the evidence for those cases)",
    ])
    return md, {"errors": errs}


def build_report(dataset: Path) -> str:
    pred_path = EVAL_DIR / "sample_predictions.csv"
    run_sample(dataset, pred_path)
    gold, pred = load_output(dataset / "sample_output.csv"), load_output(pred_path)
    m = score(pred, gold)
    conv, _ = infer_convention(gold)
    sc_md, sc_ok = scenario_table()
    pl_md, pl_ok = planner_cases()
    ds_md, _ = whole_dataset(dataset)
    failures = (EVAL_DIR / "failures_and_improvements.md").read_text(encoding="utf-8")

    per_case = ["| case | gold | pred | missing steps | extra steps |", "| --- | --- | --- | --- | --- |"]
    for f in m["failures"]:
        miss = "; ".join(f"{o} {r}" for _, o, _, r in f["missing"]) or "-"
        extra = "; ".join(f"{o} {r}" for _, o, _, r in f["extra"]) or "-"
        per_case.append(f"| {f['case_id']} | {f['gold_status']} | {f['pred_status']} | {miss} | {extra} |")

    return "\n".join([
        "# Evaluation Report", "",
        "Generated by `python code/evaluation/main.py --report` from live runs; nothing below is typed in by hand "
        "except section 5 (the failure log) and the interpretation notes.", "",
        "## 1. Labelled sample requests (`dataset/sample_output.csv`, 32 cases)", "",
        render_markdown(m, "Sample requests"),
        f"Planner conventions inferred from the labelled data match the frozen defaults: **{conv == Convention()}**.", "",
        "### Cases that are not an exact match", "", *per_case, "",
        "### Why the misses are (mostly) not recoverable", "",
        "- `case_04` (account_004), `case_18` (audit_record_6645), `case_20` (audit_record_5569): the gold plan contains a resource "
        "id that appears **nowhere** in `dataset/` (not in any evidence file or activity row), so no method can name it.",
        "- `case_23` (account_410 vs account_7015): two deletion events with the same result are equally plausible for "
        "two cases reported in the same batch; the activity ordering carries no case information (tested: event order vs case number, "
        "requested_at, user id, email, name, hash, resource id all ~50% concordant). The pipeline picks deterministically.", "",
        "### Threats to validity (read this before trusting the numbers)", "",
        "- **In-sample.** The heuristics were developed while looking at these 32 cases, so the figures above are optimistic for the "
        "hidden 518. To limit overfitting every rule was kept to a general, explainable principle (anchor file, per-category "
        "resource, status/result mirroring, absence by omission) rather than a case-specific fix, and the rules were also checked "
        "for self-consistency on all 518 unlabelled requests (see section 3).",
        "- **Ambiguity is inherent.** Identifier-free records (404 accounts, anonymised analytics profiles) can only be attributed "
        "through the deletion-worker activity batch. Where elimination cannot settle it, the pipeline keeps a best guess so that "
        "step numbering stays aligned; expect those steps to be right roughly half the time.", "",
        "## 2. Where the score comes from (field / sequence view)", "",
        "- `phase`, `operation`, `state`, `system_id`, `resource_id` agree on every matched step: the planner is deterministic and "
        "format-exact (also covered by the unit tests in `code/tests`).",
        "- `step_no` differs only when a step is missing/extra earlier in the same array (numbering is consecutive by contract).",
        "- `evidence_id` agrees on every matched step: the anchor-file rule reproduces the cited file in every labelled case "
        "that has one.", "",
        "## 3. Whole-dataset sanity checks (518 unlabelled requests; no gold available)", "", ds_md, "",
        "## 4. Additional evaluation cases created by the team", "",
        "Built by `code/tests/fixtures.py` (a miniature dataset with invented people/ids in the same file formats as `dataset/`) "
        "and run through the **real** assessor + planner + validator:", "",
        sc_md, "",
        f"Plus four planner-level cases (`code/evaluation/cases/synthetic_cases.json`: NOT_APPLICABLE, COMPLETE with tombstone and "
        f"retention, a full ghost-user INCOMPLETE exercising every finding/remediation/verification operation, and a "
        f"redacted-is-not-anonymized case with a missing retained record): all pass = **{pl_ok}**.", "",
        "```", pl_md.strip().split("### Synthetic")[0].strip(), "```", "",
        "## 5. Failures found and improvements made", "", failures, "",
    ])


def build_usage(dataset: Path) -> str:
    cfg = tomllib.loads((CODE_DIR / "config" / "config.toml").read_text(encoding="utf-8"))
    n = len(read_csv(dataset / "deletion_requests.csv"))
    notes = "\n".join([
        "## How this run was produced", "",
        "The final `output.csv` is produced by `python code/main.py`, a **deterministic engine**: identity resolution, evidence "
        "parsing (SQL, JSON, logs, text), state reconstruction, policy application and plan generation are ordinary code. "
        "It made **zero model calls**, so tokens and cost are zero and the usage ledger "
        "(`code/evaluation/ledger.jsonl`) is empty.", "",
        "Model-assisted steps exist but are not part of the final run:",
        "",
        "- `code/data/visual_facts.json` (facts read from 11 screenshots + 4 PDFs) was produced during development by Claude Code "
        "(`claude-sonnet-5-5`) viewing each file; `code/deletion_audit/visual.py` can regenerate it through the Anthropic API "
        "(cached, metered). Token counts for the development session are not available to the code and are therefore not reported here.",
        "- The LLM wrapper (`llm.py`) caches by content hash and logs every call to the ledger; if `visual.py` is run, "
        "`python code/evaluation/main.py --report` reports the real per-model calls/tokens/cost (prices from `config/config.toml`).", "",
        "No API keys or credentials are stored in this repository (`ANTHROPIC_API_KEY` is read from the environment only)."])
    return build_usage_report(EVAL_DIR / "ledger.jsonl", n, cfg.get("pricing", {}), cfg.get("provider", "Anthropic"),
                              tuple(cfg.get("models", {}).values()), notes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(REPO_ROOT / "dataset"))
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)
    ds = Path(a.dataset)
    if a.report:
        (EVAL_DIR / "evaluation_report.md").write_text(build_report(ds), encoding="utf-8")
        (EVAL_DIR / "usage_report.md").write_text(build_usage(ds), encoding="utf-8")
        print("wrote evaluation_report.md and usage_report.md in", EVAL_DIR)
        return 0
    pred_path = EVAL_DIR / "sample_predictions.csv"
    assessor, results = run_sample(ds, pred_path)
    gold, pred = load_output(ds / "sample_output.csv"), load_output(pred_path)
    m = score(pred, gold)
    print(render_markdown(m, "Sample requests (32)"))
    if a.diff or a.only:
        for f in m["failures"]:
            if a.only and f["case_id"] not in a.only:
                continue
            cid = f["case_id"]
            print("=" * 100)
            print(cid, "gold", gold[cid][0], "| pred", pred[cid][0])
            g, p = fmt(gold[cid][1]), fmt(pred[cid][1])
            for line in sorted(set(g) - set(p)):
                print("  MISSING ", line)
            for line in sorted(set(p) - set(g)):
                print("  EXTRA   ", line)
            for w in next(x for x in results if x.case_id == cid).warnings:
                print("  WARN    ", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
