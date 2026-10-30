# Dataset and problem analysis (what the data actually contains)

Everything here was measured on the participant-facing files in `dataset/`; none of it uses organizer-only
material. `docs/DATASET_PROFILE.md` is the raw column/enum profile produced by `python -m deletion_audit profile`.

## 1. The files

| File | Size | Notes |
| --- | --- | --- |
| `deletion_requests.csv` | 518 | 418 request emails are current, 100 are **historical only** (resolved through the audit log); all 518 resolve to exactly one person; one person appears twice (two audits of the same user) |
| `user_identities.csv` / `user_audit_log.csv` | 850 / 306 | `email_hash` = `sha256(lower(email))`; the audit log changes `email`, `email_hash`, `phone` |
| `system_activity.csv` | 4011 | 17 event types; a **global stream with decoys**: its `reported_result` is a claim |
| `deletion_rules.csv` | 15 | DELETE x7, REDACT x3, RETAIN x3, ANONYMIZE x2 (`BACKUP_ARCHIVE` is RETAIN: the archive stays, *restore* must be blockable) |
| `evidence/` | 94 files | 28 json, 26 log, 24 sql, 11 png, 4 pdf, 1 txt |

## 2. How the data was generated (inferred; this is what the design exploits)

- **Clusters.** Cases come in groups of ~10 that share one evidence capture time (`audit_at` sits within an hour after a
  capture). A case's source of truth is exactly one file, the *latest file mentioning the person*; the labelled answers cite it
  in 26 of 26 cases that have one.
- **Families.** The plans of the labelled cases fall into a few shapes (account only; account+audit+analytics;
  the six-resource family with support/flow/backup; INCOMPLETE variants with search/export/support/analytics/flow/backup;
  tombstone cases). In all of them there is **at most one resource per data category**.
- **Special cases (~12).** The odd report times (cases 33-63 subset) are anchored on screenshots/PDFs and linked to people
  through `LINK_RESOURCE_IDENTITY` events of a data catalog.
- **Identifier-free records.** 404 accounts and anonymised analytics profiles carry no identifier by construction; they can only
  be attributed through the deletion-worker batch in `system_activity.csv` (same reporting batch, result mirrors the reported
  status). Event order inside a batch is **not** informative (tested against case number, user id, email, name, hash, requested_at,
  resource id: all ~50% concordant on 214 evidence-resolved pairs).

## 3. The traps (and where each is handled)

| Trap | Evidence in the data | Handled by |
| --- | --- | --- |
| Reported status lies | `reported_status=COMPLETE` while evidence still shows the record | status derived from evidence only (`planner.derive_status`) |
| Historical identifiers | 100 requests use an old email; old email hashes appear in analytics / contact indexes | `identity.py` keys = all emails, phones, sha256(emails), logged hashes |
| Replication drift | account present only in a failover/read replica | any copy in the anchor counts as present |
| Evidence about someone else looks authoritative | later empty inventory tables, look-alike emails (`g.silva76@` vs `g.silva76.jr@`) | anchor file; exact-token linking (no substring/name matching) |
| Resurrection after the audit | account active again in a snapshot dated after `audit_at` | state/citation use only evidence <= `audit_at`; ownership may use any evidence |
| Stale history of another scenario | same person, an older scenario months earlier | one resource per category + 30-day staleness cut-off |
| Secondary identifiers | legacy contact index keyed by the old email / old hash, logged as `contact_*` events | `SECONDARY_IDENTIFIER` category (DELETE) |
| Restore/flow phrased differently per system | `restore_policy_read_completed`, `restore_candidate_evaluated`, `restore_authorization_completed`; `connector_config_*`, `connector_heartbeat` | per-event parsers in `evidence.py` |
| Non-deletion requests | 10 requests keep the account / ask for a copy / opt out of marketing | `intent.py`; cross-checked with 10 `CLASSIFY_REQUEST` events |
| Tombstones | stable `user_id` may stay, name/email/phone/hash must go | `ACCOUNT_TOMBSTONE` -> REDACT: identifiable if any direct identifier is non-null |
| Redacted is not anonymized | analytics still linkable through `user_id` | planner: ANONYMIZE requires state ANONYMIZED |
| Visual evidence | 11 screenshots + 4 PDFs, some of other people (a marketing console shows a different person than the catalog link) | `visual_facts.json`; the explicit catalog link is authoritative |

## 4. What cannot be known from the data

- 3 of the 32 labelled plans contain a resource id that exists nowhere in `dataset/`; about 113 of 508 deletion cases show
  no retained audit record in their evidence.
- 137 cases involve an account or analytics profile chosen among equally plausible activity records.

These are reported, not hidden: see `evaluation/evaluation_report.md` sections 1 and 3.
