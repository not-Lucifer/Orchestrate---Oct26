# Architecture

> Principle: **evidence decides, code reasons, the planner formats.** Every claim in `output.csv`
> traces to a cited evidence file captured at or before the case's `audit_at`; every decision is
> deterministic and unit-tested; a model is only an optional reader of pixels or an optional tie-breaker
> for ambiguous prose, and the shipped run uses none.

## 1. Pipeline

```
 deletion_requests.csv row
        │
 ┌──────▼───────┐ request_text ──► NOT_DELETE ──────────────────► NOT_APPLICABLE, []           intent.py
 └──────┬───────┘
        │ DELETE
 ┌──────▼───────┐ user_identities + user_audit_log
 │ 1 Identity   │ request email (current OR historical) -> Person{ emails, phones, sha256 hashes, user_id }   identity.py
 └──────┬───────┘
 ┌──────▼───────┐ 94 evidence files (sql/json/log/txt + screenshot/PDF facts)
 │ 2 Evidence   │ -> Fact(file, time, resource, category, state, linking keys) + Coverage(file, category)       evidence.py
 └──────┬───────┘
 ┌──────▼───────┐ latest file captured <= audit_at that mentions the person (by identifier or catalog link)
 │ 3 Anchor     │ = the case's source of truth and the file that gets cited                                    assessor.py
 └──────┬───────┘
 ┌──────▼───────┐ one resource per data category: anchor rows > older observations; identifier-free records
 │ 4 Linking    │ (404 accounts, anonymised analytics) attributed through the deletion-worker activity batch
 └──────┬───────┘
 ┌──────▼───────┐ state at audit_at = newest observation <= audit_at inside the anchor (+ absence by omission);
 │ 5 State      │ later evidence is ignored for state and citation                                             assessor.py
 └──────┬───────┘
 ┌──────▼───────┐ category -> treatment from deletion_rules.csv (DELETE / REDACT / ANONYMIZE / RETAIN)
 │ 6 Policy     │ => CaseAssessment                      ◄── narrow seam, models.py
 └──────┬───────┘
 ┌──────▼───────┐ status derived (never asserted) + findings -> remediation -> verification, canonical order,
 │ 7 Planner    │ evidence rules                                                                                planner.py
 └──────┬───────┘
 ┌──────▼───────┐ format rules + "never cite evidence captured after audit_at"                                  validator.py
 │ 8 Validate   │
 └──────────────┘
```

## 2. Module map (`code/deletion_audit/`)

| Module | Responsibility |
| --- | --- |
| `intent.py` | Multilingual rules (default: deletion; explicit keep/negation or access/correction/export/opt-out => not). Optional LLM second opinion only when rule confidence < 0.7 (never triggered on this data) |
| `identity.py` | Person = current + historical email/phone/hash (+ `sha256(email)` of every email, since audit-log hashes are logged separately) |
| `evidence.py` | One parser per format family, all emitting the same `Fact` vocabulary (below) |
| `assessor.py` | Anchor, linking, activity-batch attribution, state at `audit_at`, policy mapping -> `CaseAssessment` |
| `planner.py` | `CaseAssessment` -> status + ordered steps (pure, 100% deterministic) |
| `ops.py` | The statement's operation table, canonical ordering, finding->remediation->verification maps |
| `validator.py` | Every format rule + citation timing check |
| `scoring.py`, `profile.py` | Local scorer (status / step / field / sequence / row) and dataset profiler / convention inference |
| `visual.py`, `llm.py`, `usage.py` | Optional vision extraction; content-hash cache + JSONL ledger; usage report |
| `pipeline.py`, `io_utils.py`, `cli.py`, `synthetic.py` | glue, CSV I/O, tooling, planner-level evaluation cases |

## 3. The evidence vocabulary

The dataset renders one truth - "what state is resource R in at time T and which identifiers does it expose" -
in ~25 shapes. All of them are mapped to the vocabulary of `deletion_rules.csv` categories:

| Category | Rule | States | Plan |
| --- | --- | --- | --- |
| USER_PROFILE / SEARCH_INDEX_ENTRY / SUPPORT_ATTACHMENT / USER_EXPORT / MARKETING_PROFILE / SECONDARY_IDENTIFIER | DELETE | FOUND / NOT_FOUND | FOUND -> `REPORT_REMAINING_RECORD`, `DELETE_RECORD`, `VERIFY_RECORD_ABSENT` |
| SUPPORT_MESSAGE, ACCOUNT_TOMBSTONE | REDACT | IDENTIFIABLE / REDACTED | IDENTIFIABLE -> `REPORT_EXPOSED_PII`, `REDACT_RECORD`, `VERIFY_RECORD_REDACTED` |
| ANALYTICS_PROFILE | ANONYMIZE | IDENTIFIABLE / ANONYMIZED | IDENTIFIABLE -> `REPORT_EXPOSED_PII`, `ANONYMIZE_RECORD`, `VERIFY_RECORD_ANONYMIZED` (a *redacted* record is still linkable and does not satisfy ANONYMIZE) |
| SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD | RETAIN | FOUND | `VERIFY_RECORD_PRESENT` |
| DATA_FLOW (process) | - | ACTIVE / DISABLED | ACTIVE -> `REPORT_ACTIVE_DATA_FLOW`, `DISABLE_DATA_FLOW`, `VERIFY_DATA_FLOW_DISABLED` |
| BACKUP_ARCHIVE (restore path) | RETAIN, restore blockable | ACTIVE / BLOCKED | ACTIVE -> `REPORT_RESTORE_RISK`, `BLOCK_RESTORE`, `VERIFY_RESTORE_BLOCKED` |

Format families handled: SQL snapshots (primary + read/regional/reporting/failover replicas; presence in *any* copy
counts, which is how replication drift shows up), JSON snapshot bundles (several internal snapshots per file),
service exports, ledger rows (json / txt / log), single-collection reports, and ten log dialects
(`k=v`, bracketed, pipe-delimited, syslog, JSON-lines, `message="..."` wrappers, with the lookup key on a *started*
line joined to the *completed* line through `trace_id`). Screenshots/PDFs enter through `code/data/visual_facts.json`.

## 4. Key decisions and why

1. **Anchor file.** Snapshots about other people look authoritative (a later empty inventory table "proves" every
   account absent). The case's evidence is the latest file that *mentions the person*; it fixes the cited file and the
   state. Reproduces the cited file in all 26 labelled cases that have one.
2. **Ownership vs state vs citation.** Resource ids never change hands, so any evidence may say *whose* a record is.
   Only evidence captured at or before `audit_at` may say *what state* it is in or be cited. This neutralises the
   "resurrected after the audit" trap and is enforced on the output by `validate_citations`.
3. **One resource per data category per case.** Holds in every labelled case; it removes leakage from a person's other
   scenarios (older observations > 30 days before the anchor are ignored).
4. **Claims are claims.** `reported_status` and `reported_result` never decide the status. They are used for one thing
   only: batch-run deletion events mirror the case's reported status (SUCCESS=COMPLETE, PARTIAL=PARTIALLY_COMPLETE,
   FAILED=NOT_STARTED: 213/214 evidence-identified pairs), which lets identifier-free records be attributed.
5. **Status is derived.** `planner.derive_status` is the four-part completeness definition from the statement: any
   violating copy, any active flow, any restorable backup => INCOMPLETE; there is no code path that returns COMPLETE
   while one of them exists.
6. **Conventions are measured, not guessed.** What the statement leaves open (INCOMPLETE plans also verify already-clean
   records; retained records get `VERIFY_RECORD_PRESENT`; tombstones only `VERIFY_RECORD_REDACTED`) is inferred from
   `sample_output.csv` by `python -m deletion_audit conventions` and pinned by a test.
7. **Ambiguity is explicit.** When the dataset cannot decide (several equally plausible deletion events for several
   cases), the assessor keeps a deterministic guess, records it in the case notes, and the evaluation report counts how
   many cases are touched. A wrong-but-present step also keeps `step_no` alignment for everything after it.
8. **No hidden state, no network.** The run is a pure function of `dataset/` + `code/data/visual_facts.json`: 2 seconds,
   byte-identical output across runs (tested), zero model calls.

## 5. Extending it

- New log dialect / table: add a parser branch in `evidence.py` that emits `Fact`s; nothing else changes.
- New data category: add it to `PREFIX_CATEGORY`, `CATEGORY_SYSTEM` and (if it is a process, not a record) the flow/restore
  branches of `assessor.assess`.
- Different policy: `deletion_rules.csv` is read at run time; treatments are never hard-coded.
- LLM use: `llm.py` caches by content hash and meters every call; `visual.py` (screenshots/PDFs) and the intent second
  opinion are the two wired entry points.
