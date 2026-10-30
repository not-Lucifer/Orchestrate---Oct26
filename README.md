# Ghost Data Still Exists - deletion audit agent

For each deletion request this system decides whether the person's personal data is **really** gone
(`COMPLETE`), still exposed (`INCOMPLETE`), or whether deletion was never requested (`NOT_APPLICABLE`),
and writes the ordered findings -> remediation -> verification plan the contract requires
(`output.csv`, 518 rows).

**Approach in one paragraph.** Evidence decides, code reasons, a planner formats. Identity resolution recovers every
current *and historical* identifier (emails, `sha256` email hashes, phones). Each case is anchored on the latest
evidence file captured at or before `audit_at` that mentions the person; the state of each of their records is read
from that file (claims such as `reported_status` and activity `reported_result` are never trusted), policy comes from
`deletion_rules.csv`, and a deterministic planner derives the status from the statement's four completeness conditions and
emits the plan in the exact operation/ordering/evidence format. The run is deterministic, offline, takes ~2 s and
makes **zero model calls**; a vision model and an LLM intent tie-breaker exist as optional, cached, metered components.

## Run it

```bash
# Python >= 3.11, standard library only. Put the provided files in ./dataset/
python code/main.py                      # -> ./output.csv  (also validates format + citation timing)
python -m unittest discover -s code/tests            # 48 tests
python code/evaluation/main.py           # score the 32 labelled samples (sample_output.csv is used ONLY here)
python code/evaluation/main.py --report  # regenerate code/evaluation/{evaluation,usage}_report.md
python code/evaluation/show_case.py case_34 case_61   # human-readable plan for any case
```

Optional LLM pieces (need `pip install anthropic` and `ANTHROPIC_API_KEY`; never required):
`python code/deletion_audit/visual.py` (re-extract the screenshots/PDFs), `python code/main.py --llm-intent`.
Secrets are read from the environment only.

## Results (details: `code/evaluation/evaluation_report.md`)

| Measure on the 32 labelled samples (in-sample, see caveat) | Value |
| --- | --- |
| Case-level status accuracy | 100% (10/10 COMPLETE, 22/22 INCOMPLETE) |
| Step precision / recall / F1 | 99.5% / 97.9% / 98.7% |
| Exact row match / exact sequence match | 87.5% / 87.5% |
| Field accuracy (phase, operation, state, system, resource, evidence) | 100% on matched steps |
| Full 518-request run | 156 COMPLETE, 352 INCOMPLETE, 10 NOT_APPLICABLE; format + citation validation OK |

Caveat: the heuristics were developed while looking at those 32 cases, so expect the hidden score to be lower;
the report lists exactly which facts the dataset does not contain (ids that appear nowhere; identifier-free records
that several cases could own) and how many cases they touch (137 of 508).

## Repository layout

```
README.md              this file
output.csv             the submission file (python code/main.py)
code/
  main.py              entry point
  deletion_audit/      intent, identity, evidence (parsers), assessor, planner, ops, validator, scoring, visual, llm, usage ...
  data/visual_facts.json   facts read from the 11 screenshots + 4 PDFs (provenance recorded inside)
  prompts/             prompts for the two optional model components
  config/config.toml   models / pricing for the optional components (no secrets)
  docs/                ARCHITECTURE, ANALYSIS (dataset findings), DATASET_PROFILE, INTERVIEW_AND_SUBMISSION
  evaluation/          evaluation_report.md, usage_report.md, failures_and_improvements.md, harness, cases/
  tests/               48 tests incl. an end-to-end mini-dataset builder (fixtures.py)
```

## AI use, disclosed

- **In the final run:** none (0 model calls, 0 tokens, $0; see `code/evaluation/usage_report.md`).
- **During development:** this solution was built with Claude Code (`claude-sonnet-5-5`); the session is logged in `log.txt`.
  The facts in `code/data/visual_facts.json` were read from the screenshots/PDFs by that assistant (no API key was available);
  `visual.py` reproduces the extraction through the API.

## Package for submission (PowerShell, from the repository root)

```powershell
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Remove-Item code\evaluation\ledger.jsonl -ErrorAction SilentlyContinue
Compress-Archive -Path README.md, code -DestinationPath code.zip -Force
```
Do not include `dataset/`, `.cache/`, virtual environments or nested archives. Upload `output.csv`, `code.zip` and `log.txt`.
