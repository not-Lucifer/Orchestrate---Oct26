# Visual evidence extractor (`deletion_audit/visual.py`)

Used for the screenshots (PNG) and PDFs under `dataset/evidence/`. One call per file, cached by content
hash (`.cache/llm`), metered in `evaluation/ledger.jsonl`. The model **reads**; it does not decide
deletion status. Its output is the same `Fact` shape every other evidence parser produces, so the
deterministic engine treats it like any other source.

Run: `ANTHROPIC_API_KEY=... python code/deletion_audit/visual.py --dataset dataset --out code/data/visual_facts.json`

The shipped `code/data/visual_facts.json` was produced this way by hand during development (the build
environment had no API key); the file records that provenance.

## System

```
You extract verifiable facts from one business artifact (an application screenshot or a PDF) for a
privacy audit. Output a single JSON object and nothing else. Copy identifiers exactly as printed.
Never infer a resource id: only use ids that are printed in the artifact (e.g. "account_5762",
"support_1034", "backup_9287", "audit_record_003", "export_1260") or that the caller lists in
`catalog_hints`. If something is unreadable, omit it. Do not decide whether a deletion is complete.
```

## User template (the file is attached)

```
file_id: {file_id}
captured_at (from the evidence manifest): {captured_at}
catalog_hints (resource ids the data catalog links to a person; a document label such as a statement
number may stand for one of them): {catalog_hints}

Return:
{"describes": "<one sentence>",
 "facts": [
   {"resource_id": "<id printed in the artifact or from catalog_hints>",
    "category": "USER_PROFILE | SEARCH_INDEX_ENTRY | SUPPORT_MESSAGE | SUPPORT_ATTACHMENT | ANALYTICS_PROFILE |
                 USER_EXPORT | MARKETING_PROFILE | DATA_FLOW | BACKUP_ARCHIVE | SECURITY_AUDIT_LOG |
                 LEGAL_HOLD_RECORD | ACCOUNT_TOMBSTONE",
    "state": "FOUND | NOT_FOUND | IDENTIFIABLE | REDACTED | ANONYMIZED | ACTIVE | BLOCKED | DISABLED",
    "keys": ["<every identifier printed next to that resource: email, phone, user_id>"]}]}

State guidance:
- A record that is displayed with its data  -> FOUND (profile, search hit, export "Ready", attachment listed).
- Support ticket / analytics profile / tombstone showing a name, email or phone -> IDENTIFIABLE;
  showing only a stable user_id or no identifier -> REDACTED (support, tombstone) / ANONYMIZED (analytics).
- Connector "healthy / continuous sync" -> ACTIVE; stopped/disabled -> DISABLED.
- Backup archive listed as restorable -> ACTIVE; restore denied/blocked -> BLOCKED.
- Only emit facts about the resources of the person the document is about; ignore unrelated rows.
```

## Post-processing (deterministic)

`visual.py` validates the JSON (allowed category/state values, resource id prefix matches the category),
stamps `t = captured_at`, and merges it into `EvidenceStore` through `code/data/visual_facts.json`.
