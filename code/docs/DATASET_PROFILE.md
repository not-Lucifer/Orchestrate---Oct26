# Dataset profile: `D:\Orchestrate\dataset`

## deletion_requests.csv (518 rows)

| column | distinct | values / examples |
| --- | --- | --- |
| case_id | 518 | `case_33`, `case_34`, `case_35` … |
| email | 517 | `ingrid.dahl@outlook.com`, `haruka.s1838@zoho.com`, `g.silva76@gmail.com` … |
| requested_at | 508 | `2026-07-16T08:00:00Z`, `2026-09-24T08:00:00Z`, `2026-08-30T03:00:00Z` … |
| reported_status | 3 | `COMPLETE`×254, `PARTIALLY_COMPLETE`×152, `NOT_STARTED`×112 |
| reported_at | 238 | `2026-07-18T02:00:00Z`, `2026-09-26T02:00:00Z`, `2026-08-31T21:00:00Z` … |
| audit_at | 72 | `2026-07-19T13:00:00Z`, `2026-09-27T13:00:00Z`, `2026-09-02T08:00:00Z` … |
| request_text | 375 | `Please close my account and process the `, `I would like the account associated with`, `Please close my account and process the ` … |

## deletion_rules.csv (15 rows)

| column | distinct | values / examples |
| --- | --- | --- |
| rule_id | 15 | `rule_01`×1, `rule_02`×1, `rule_03`×1, `rule_04`×1, `rule_05`×1, `rule_06`×1, `rule_07`×1, `rule_08`×1, `rule_09`×1, `rule_10`×1, `rule_11`×1, `rule_12`×1, `rule_13`×1, `rule_14`×1, `rule_15`×1 |
| data_category | 15 | `USER_PROFILE`×1, `SECONDARY_IDENTIFIER`×1, `SEARCH_INDEX_ENTRY`×1, `CACHE_ENTRY`×1, `SUPPORT_MESSAGE`×1, `SUPPORT_ATTACHMENT`×1, `ANALYTICS_PROFILE`×1, `PRODUCT_TELEMETRY`×1, `USER_EXPORT`×1, `MARKETING_PROFILE`×1, `EMAIL_DELIVERY_LOG`×1, `SECURITY_AUDIT_LOG`×1, `LEGAL_HOLD_RECORD`×1, `BACKUP_ARCHIVE`×1, `ACCOUNT_TOMBSTONE`×1 |
| condition | 9 | `Always`×6, `Record is still attributable to a user`×2, `Conversation contains shared customer, agent, or order context that must be retained`×1, `Attachment belongs only to the deletion subject`×1, `Log contains a user email address`×1, `Record is within the supplied retention period`×1, `A supplied legal hold is active`×1, `Restore access can be blocked`×1, `Account is deleted and only a stable internal user_id is needed to preserve references to retained records`×1 |
| required_action | 4 | `DELETE`×7, `REDACT`×3, `RETAIN`×3, `ANONYMIZE`×2 |

## evidence_files.csv (94 rows)

| column | distinct | values / examples |
| --- | --- | --- |
| file_id | 94 | `evidence_01`, `evidence_02`, `evidence_03` … |
| file_path | 94 | `evidence/logs/service_events_ap_south_20`, `evidence/records/customer_data_snapshot_`, `evidence/records/customer_account_handov` … |
| origin | 30 | `central_observability_export`, `records_assurance_snapshot_bundle`, `customer_account_service` … |
| captured_at | 93 | `2026-09-15T11:59:39Z`, `2026-09-17T12:00:00Z`, `2026-10-01T12:00:00Z` … |

## output.csv (0 rows)

(empty)

## sample_deletion_requests.csv (32 rows)

| column | distinct | values / examples |
| --- | --- | --- |
| case_id | 32 | `case_01`, `case_02`, `case_03` … |
| email | 32 | `amina.elmasri@gmail.com`, `mateo.rios@outlook.com`, `l.fontaine46@yahoo.com` … |
| requested_at | 30 | `2026-08-18T09:14:00Z`, `2026-08-21T18:06:00Z`, `2026-09-13T11:00:00Z` … |
| reported_status | 3 | `COMPLETE`×17, `NOT_STARTED`×10, `PARTIALLY_COMPLETE`×5 |
| reported_at | 22 | `2026-08-20T16:42:00Z`, `2026-08-22T07:25:00Z`, `2026-09-15T11:00:00Z` … |
| audit_at | 13 | `2026-09-15T12:00:00Z`×15, `2026-09-26T11:00:00Z`×3, `2026-10-01T12:00:00Z`×3, `2026-09-21T10:00:00Z`×2, `2026-09-03T11:30:00Z`×1, `2026-09-04T15:00:00Z`×1, `2026-09-07T10:20:00Z`×1, `2026-09-08T13:40:00Z`×1, `2026-09-10T09:15:00Z`×1, `2026-09-12T08:00:00Z`×1, `2026-09-14T16:10:00Z`×1, `2026-09-16T09:00:00Z`×1, `2026-09-18T12:25:00Z`×1 |
| request_text | 32 | `Hi, I haven’t used this account in years`, `Intenté eliminar mi cuenta ayer, pero la`, `Je demande la suppression définitive du ` … |

## sample_output.csv (32 rows)

| column | distinct | values / examples |
| --- | --- | --- |
| case_id | 32 | `case_01`, `case_02`, `case_03` … |
| deletion_status | 2 | `INCOMPLETE`×22, `COMPLETE`×10 |
| steps_json | 32 | `[{"evidence_id":"evidence_54","operation`, `[{"evidence_id":"evidence_54","operation`, `[{"step_no":1,"phase":"VERIFICATION","sy` … |

## system_activity.csv (4011 rows)

| column | distinct | values / examples |
| --- | --- | --- |
| activity_id | 4011 | `activity_01`, `activity_02`, `activity_03` … |
| event_time | 4011 | `2026-01-04T14:56:29Z`, `2026-01-04T16:08:26Z`, `2026-01-04T17:14:03Z` … |
| event_type | 17 | `INDEX_RECORD`, `UPDATE_RECORD`, `RETAIN_RECORD` … |
| source_system | 11 | `deletion_worker`×1466, `account_service`×1100, `profile_service`×440, `notification_service`×368, `support_platform`×232, `security_service`×196, `export_service`×155, `integration_service`×31, `data_catalog`×12, `privacy_intake`×10, `backup_service`×1 |
| target_system | 19 | `search_service`, `account_service`, `archive_service` … |
| resource_id | 3948 | `search_9729`, `search_6919`, `search_4613` … |
| reported_result | 3 | `SUCCESS`×2914, `FAILED`×721, `PARTIAL`×376 |
| details | 4011 | `Customer search-index refresh processed `, `Customer search-index refresh processed `, `Customer search-index refresh processed ` … |

## user_audit_log.csv (306 rows)

| column | distinct | values / examples |
| --- | --- | --- |
| audit_id | 306 | `audit_01`, `audit_02`, `audit_03` … |
| user_id | 196 | `user_485`, `user_505`, `user_525` … |
| event_time | 198 | `2024-12-14T16:31:44Z`, `2024-12-25T00:51:04Z`, `2025-01-04T00:11:24Z` … |
| field_name | 3 | `email`×107, `email_hash`×107, `phone`×92 |
| old_value | 306 | `+33 6 24 34 80 16`, `+81 90 6278 6936`, `+46 70 144 08 06` … |
| new_value | 306 | `+33 6 63 29 68 28`, `+81 90 7870 0272`, `+46 70 808 74 05` … |

## user_identities.csv (850 rows)

| column | distinct | values / examples |
| --- | --- | --- |
| user_id | 850 | `user_01`, `user_02`, `user_03` … |
| name | 847 | `Amina El-Masri`, `Mateo Ríos`, `Oliver Bennett` … |
| email | 850 | `amina.elmasri@gmail.com`, `mateo.rios@outlook.com`, `oliver-bennett@gmail.com` … |
| phone | 850 | `+971 50 482 7316`, `+34 612 847 593`, `+1 (202) 555-0103` … |
| email_hash | 850 | `d4e1f59abcf9a1e0cfdc7c27ad6c07ed4ff88b32`, `fad1c282b6b8ff346ee92e617331f69c2b6bb345`, `1fa7764c96e40e8570cbb7569f707f6d84c593ce` … |
| updated_at | 850 | `2026-05-28T04:03:00Z`, `2026-04-24T07:44:00Z`, `2026-03-14T14:21:00Z` … |

## evidence/ (94 files)

By extension: `.json`×28, `.log`×26, `.sql`×24, `.png`×11, `.pdf`×4, `.txt`×1

### SQL snapshot `customer_accounts_failover_replica_20260902.sql`

```
customer_profiles_failover_replica (4 rows): CREATE TABLE customer_profiles_failover_replica (
                resource_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                full_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
                account_status TEXT NOT NULL, updated_at TEXT NOT NULL
            )
customer_profiles_primary (3 rows): CREATE TABLE customer_profiles_primary (
                resource_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                full_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL,
                account_status TEXT NOT NULL, updated_at TEXT NOT NULL
            )
```

### SQL snapshot `customer_data_failover_replica_20260920.sql`

```
customer_data_failover_replica (16 rows): CREATE TABLE customer_data_failover_replica (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        )
customer_data_primary (16 rows): CREATE TABLE customer_data_primary (
            resource_id TEXT PRIMARY KEY,
            origin_system TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            record_json TEXT NOT NULL CHECK (json_valid(record_json)),
            updated_at TEXT NOT NULL
        )
```

### SQL snapshot `customer_data_inventory_20260213.sql`

```
snapshot_scope (7 rows): CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL)
customer_profiles (2 rows): CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_search_documents (4 rows): CREATE TABLE customer_search_documents (resource_id TEXT PRIMARY KEY, customer_reference TEXT, display_name TEXT, email TEXT, phone TEXT, email_hash TEXT, index_name TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_analytics_profiles (3 rows): CREATE TABLE customer_analytics_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, email TEXT, phone TEXT, email_hash TEXT, audience_cohort TEXT NOT NULL, updated_at TEXT NOT NULL)
support_records (2 rows): CREATE TABLE support_records (resource_id TEXT PRIMARY KEY, customer_reference TEXT, requester_name TEXT, requester_email TEXT, requester_phone TEXT, message_excerpt TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_exports (0 rows): CREATE TABLE customer_exports (resource_id TEXT PRIMARY KEY, customer_reference TEXT, owner_email TEXT, owner_phone TEXT, object_key TEXT NOT NULL, updated_at TEXT NOT NULL)
connector_subscriptions (1 rows): CREATE TABLE connector_subscriptions (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, connector_name TEXT NOT NULL, enabled INTEGER NOT NULL CHECK (enabled IN (0,1)), last_delivery_status TEXT NOT NULL, updated_at TEXT NOT NULL)
backup_restore_entries (1 rows): CREATE TABLE backup_restore_entries (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, archive_key TEXT NOT NULL, restore_allowed INTEGER NOT NULL CHECK (restore_allowed IN (0,1)), updated_at TEXT NOT NULL)
security_audit_records (4 rows): CREATE TABLE security_audit_records (resource_id TEXT PRIMARY KEY, subject_reference TEXT NOT NULL, event_code TEXT NOT NULL, retention_until TEXT NOT NULL, updated_at TEXT NOT NULL)
```

### SQL snapshot `customer_data_inventory_20260310.sql`

```
snapshot_scope (8 rows): CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL)
customer_profiles (0 rows): CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_search_documents (7 rows): CREATE TABLE customer_search_documents (resource_id TEXT PRIMARY KEY, customer_reference TEXT, display_name TEXT, email TEXT, phone TEXT, email_hash TEXT, index_name TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_analytics_profiles (5 rows): CREATE TABLE customer_analytics_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, email TEXT, phone TEXT, email_hash TEXT, audience_cohort TEXT NOT NULL, updated_at TEXT NOT NULL)
support_records (3 rows): CREATE TABLE support_records (resource_id TEXT PRIMARY KEY, customer_reference TEXT, requester_name TEXT, requester_email TEXT, requester_phone TEXT, message_excerpt TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_exports (1 rows): CREATE TABLE customer_exports (resource_id TEXT PRIMARY KEY, customer_reference TEXT, owner_email TEXT, owner_phone TEXT, object_key TEXT NOT NULL, updated_at TEXT NOT NULL)
connector_subscriptions (4 rows): CREATE TABLE connector_subscriptions (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, connector_name TEXT NOT NULL, enabled INTEGER NOT NULL CHECK (enabled IN (0,1)), last_delivery_status TEXT NOT NULL, updated_at TEXT NOT NULL)
backup_restore_entries (1 rows): CREATE TABLE backup_restore_entries (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, archive_key TEXT NOT NULL, restore_allowed INTEGER NOT NULL CHECK (restore_allowed IN (0,1)), updated_at TEXT NOT NULL)
security_audit_records (2 rows): CREATE TABLE security_audit_records (resource_id TEXT PRIMARY KEY, subject_reference TEXT NOT NULL, event_code TEXT NOT NULL, retention_until TEXT NOT NULL, updated_at TEXT NOT NULL)
```

### SQL snapshot `customer_data_inventory_20260404.sql`

```
snapshot_scope (8 rows): CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL)
customer_profiles (0 rows): CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_search_documents (5 rows): CREATE TABLE customer_search_documents (resource_id TEXT PRIMARY KEY, customer_reference TEXT, display_name TEXT, email TEXT, phone TEXT, email_hash TEXT, index_name TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_analytics_profiles (4 rows): CREATE TABLE customer_analytics_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, email TEXT, phone TEXT, email_hash TEXT, audience_cohort TEXT NOT NULL, updated_at TEXT NOT NULL)
support_records (2 rows): CREATE TABLE support_records (resource_id TEXT PRIMARY KEY, customer_reference TEXT, requester_name TEXT, requester_email TEXT, requester_phone TEXT, message_excerpt TEXT NOT NULL, updated_at TEXT NOT NULL)
customer_exports (1 rows): CREATE TABLE customer_exports (resource_id TEXT PRIMARY KEY, customer_reference TEXT, owner_email TEXT, owner_phone TEXT, object_key TEXT NOT NULL, updated_at TEXT NOT NULL)
connector_subscriptions (2 rows): CREATE TABLE connector_subscriptions (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, connector_name TEXT NOT NULL, enabled INTEGER NOT NULL CHECK (enabled IN (0,1)), last_delivery_status TEXT NOT NULL, updated_at TEXT NOT NULL)
backup_restore_entries (1 rows): CREATE TABLE backup_restore_entries (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, archive_key TEXT NOT NULL, restore_allowed INTEGER NOT NULL CHECK (restore_allowed IN (0,1)), updated_at TEXT NOT NULL)
security_audit_records (3 rows): CREATE TABLE security_audit_records (resource_id TEXT PRIMARY KEY, subject_reference TEXT NOT NULL, event_code TEXT NOT NULL, retention_until TEXT NOT NULL, updated_at TEXT NOT NULL)
```
