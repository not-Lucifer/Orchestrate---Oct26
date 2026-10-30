# Intent second opinion (`deletion_audit/intent.py`, optional)

The decision "does `request_text` authorise deletion?" is made by deterministic multilingual rules
(`classify_rules`): default **deletion**, unless the text explicitly keeps the account/data ("do not
close", "leave the account active", "marketing lists only", ...) or is plainly an access / correction /
export / opt-out request. On the supplied dataset every request is decided with confidence >= 0.9, so
the model below is **never called**; the rules yield exactly the 10 non-deletion requests
(`case_533`..`case_542`), which also equals the number of `CLASSIFY_REQUEST` events in the activity log
(used only as a cross-check).

If a future request is ambiguous (rule confidence < 0.7), `classify(text, llm)` asks the model once
(cached by content hash, metered in `evaluation/ledger.jsonl`). A malformed or unsure answer falls back to
**NOT_DELETE**: authorising a destructive plan on a guess is the worse error.

Enable with `python code/main.py --llm-intent` (needs `ANTHROPIC_API_KEY`).

## System

```
You classify customer privacy requests for an e-commerce company. Output JSON only.
```

## User template

```
Request text:
"""
{text}
"""

Does the customer ask for their account and/or personal data to be deleted, erased, forgotten or
verified as deleted? Judge the final stated wish ("please don't delete my account" is NOT_DELETE).
Return exactly: {"intent": "DELETE" | "NOT_DELETE", "reason": "<=25 words", "confidence": 0.0-1.0}
```
