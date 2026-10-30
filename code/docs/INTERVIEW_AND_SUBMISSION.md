# Submission checklist and interview notes

## Deliverables (HackerRank "Ghost Data Still Exists")

| Item | Where | State |
| --- | --- | --- |
| `output.csv` | repository root (`python code/main.py`) | 518 rows, sorted, valid, citations <= `audit_at` |
| `code.zip` | `README.md` + `code/` (no `dataset/`, no caches, no nested archives) | built by the packaging command in the README |
| `evaluation/evaluation_report.md` | `code/evaluation/` | status / row / step / field / sequence accuracy, 14 extra cases, failures + improvements |
| `evaluation/usage_report.md` | `code/evaluation/` | final run: 0 model calls (deterministic engine); development-time AI assistance disclosed |
| `chat_transcript` | root `log.txt` (appended every turn per `AGENTS.md`) | upload as-is |
| agent trace (optional) | see `agent_trace_instructions.md` (Claude Code: `/export` + `~/.claude/projects/<project>/*.jsonl`) | produce when the session ends |

Before zipping: `python -m unittest discover -s code/tests` (48 tests), `python code/main.py` ("validation: OK"),
`python code/evaluation/main.py --report`, grep for secrets (`sk-`, `ANTHROPIC_API_KEY=`), delete `code/**/__pycache__`.

## 90-second explanation

A deletion audit is a *reconstruction* problem, not a classification problem. For each request the system resolves who
the person was (including old emails and email hashes), finds the one evidence file that actually speaks about that
person at `audit_at`, reads the state of each of their records from it, applies `deletion_rules.csv`, and derives
COMPLETE / INCOMPLETE from the statement's four conditions. Findings, remediation and verification are produced by a
deterministic planner that owns the exact output contract (operation table, ordering, evidence rules), so format errors
are impossible by construction and tested.

## Likely questions

| Question | Answer |
| --- | --- |
| Where is the AI? | The task is dominated by exact reasoning over messy-but-structured evidence, so the core is deterministic code (auditable, 2 s, reproducible). Models are used where they pay for themselves: reading screenshots/PDFs (`visual.py`, facts cached) and a conservative second opinion on ambiguous request prose (`intent.py`), both content-hash cached and metered. The final run needs neither. |
| Why not prompt an LLM with the evidence? | 94 files x 518 cases of PII-bearing context, no determinism, no citation guarantees, no way to prove ordering/format. The planner makes the contract unbreakable; evidence parsing makes every step traceable. |
| How do you avoid trusting claims? | `reported_status` / `reported_result` never set the status. They only help attribute identifier-free records to a case, and that use was validated on 214 evidence-identified pairs (213 agree). |
| How do you handle old emails? | `identity.py` keys: every email in the audit log, `sha256` of each, phones, logged hashes. 100 of 518 requests are historical-only. |
| What is the "anchor file"? | The latest evidence file captured at or before `audit_at` that mentions the person. It fixes both the state and the cited file; it reproduces the labelled citations in 26/26 cases that have one. |
| What about evidence from after the audit? | Ownership may use it (an id never changes hands), state and citations may not. The validator checks every cited id against the manifest and `audit_at`. |
| What can't you get right? | Records with no identifier at all (404 accounts, anonymised analytics profiles) in batches with several equally plausible candidates, and ids that exist nowhere in the dataset. 137 / 508 cases touch the first; we measured that no ordering signal exists and say so. |
| How did you evaluate? | 32 labelled cases (in-sample, disclosed), 14 team-authored cases on a synthetic mini-dataset in the real file formats, a citation/format validator on all 518 outputs, and a failure log with before/after metrics. |
| What would you do with more time? | Learn the batch-attribution prior from more labelled data; extract screenshots with a vision model at scale and confidence-gate them; add active-learning on the ambiguous 137. |

## Honest limitations to volunteer

- Sample metrics are in-sample (heuristics developed while looking at those 32 cases); hidden-set performance is lower, mostly on the ambiguous attributions.
- Facts from the 15 screenshots/PDFs were transcribed during development by Claude Code, not extracted by an API call in the final run (no API key in the environment). The extractor exists and is tested, the shipped JSON is the cache.
- `deletion_requests.csv` has no labels; the checks in section 3 of the evaluation report are consistency checks, not accuracy.
