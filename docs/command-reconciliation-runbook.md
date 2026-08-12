# Command Archive Reconciliation Runbook

This runbook is the production operating contract for the recovered Command and
DocuSign archive. It protects the immutable `crm_archive_artifacts` baseline,
records audit-only reconciliation runs, and controls semantic source-record
writes.

The verified archive target is **12,580 artifacts** and **745,060,261 bytes**.
The bundle fingerprint is intentionally not hard-coded: it must be recomputed
from the database that will receive the reconciliation and passed back to apply
mode exactly.

## Safety state

- `--verify-only` validates every stored byte, declared length, and SHA-256. It
  writes only a reconciliation run and one `archive_integrity` result.
- `--dry-run` parses selected modules and writes reconciliation audit rows. It
  does not create or update semantic source records.
- `--apply` can create or update semantic source records and their artifact
  links. It refuses to start unless `--expect-fingerprint` exactly matches the
  fingerprint recomputed from the current database archive.
- The default parser registry currently contains only `archive_integrity`.
  Domain modules must be registered, tested, reconciled, and reviewed before
  they are selected for apply.
- **Apply is not authorized until every selected domain parser has a reviewed
  reconciliation expectation and a completed, reviewed dry run.**
- Never edit `crm_archive_artifacts` to make a reconciliation pass. Repair the
  ingestion source or parser under a new reviewed change instead.

## Runtime setup

Run from the deployed revision that contains the reconciliation code. Use the
same secret-managed `DATABASE_URL` as the target service; never paste that URL
into tickets, logs, or shell history.

```bash
export REPO_ROOT="$(git rev-parse --show-toplevel)"
export PYTHON="${PYTHON:-python}"
export COMMAND_PARSER_VERSION="command-v1"
cd "$REPO_ROOT/backend"
```

Confirm the intended commit and database target through the deployment system
before continuing. Only one reconciliation process may operate on a run at a
time.

## 1. Schema and archive preflight

The reconciliation schema is additive. The expected single Alembic head is
`2e7f9a0b1c2d`; the pre-foundation revision is `f0c8a6d9e431`.

```bash
"$PYTHON" -m alembic heads
"$PYTHON" -m alembic current
"$PYTHON" -m alembic history --indicate-current
```

`alembic heads` must print exactly:

```text
2e7f9a0b1c2d (head)
```

Before a production migration, take a provider-level database snapshot and
render the exact SQL for review:

```bash
"$PYTHON" -m alembic upgrade f0c8a6d9e431:2e7f9a0b1c2d --sql \
  > /tmp/command-provenance-upgrade.sql
```

Review the SQL and then, under the approved deployment change, migrate:

```bash
"$PYTHON" -m alembic upgrade 2e7f9a0b1c2d
"$PYTHON" -m alembic current
```

Do not run the reconciliation CLI if `crm_reconciliation_runs` or
`crm_reconciliation_results` is absent. All CLI modes create audit rows, so a
database still at `f0c8a6d9e431` must be migrated through the normal deployment
path first.

Use these read-only preflight queries in the database console:

```sql
SELECT version_num FROM alembic_version ORDER BY version_num;

SELECT
  count(*) AS artifact_count,
  coalesce(sum(size_bytes), 0) AS byte_count,
  count(*) FILTER (WHERE content_bytes IS NULL) AS missing_byte_rows
FROM crm_archive_artifacts;

SELECT
  to_regclass('public.crm_source_records') AS source_records,
  to_regclass('public.crm_source_record_artifacts') AS source_artifacts,
  to_regclass('public.crm_entity_sources') AS entity_sources,
  to_regclass('public.crm_reconciliation_runs') AS reconciliation_runs,
  to_regclass('public.crm_reconciliation_results') AS reconciliation_results;
```

The archive catalog query must return `12580`, `745060261`, and `0`. Catalog
totals alone are not a byte/hash verification; the next step performs that
verification.

## 2. Verify the immutable archive and capture its fingerprint

Record the semantic source-record count before verify-only:

```sql
SELECT count(*) AS source_records_before_verify FROM crm_source_records;
```

Run verify-only and retain its single JSON result as deployment evidence:

```bash
VERIFY_JSON="$(
  "$PYTHON" -m scripts.reconcile_command_archive \
    --verify-only \
    --parser-version "$COMMAND_PARSER_VERSION"
)"
printf '%s\n' "$VERIFY_JSON" | "$PYTHON" -m json.tool
```

Enforce the archive contract and extract the fingerprint:

```bash
printf '%s' "$VERIFY_JSON" | "$PYTHON" -c '
import json, re, sys
p = json.load(sys.stdin)
assert p["status"] == "completed", p
assert re.fullmatch(r"[0-9a-f]{64}", p["bundle_fingerprint"]), p
m = next(x for x in p["modules"] if x["module"] == "archive_integrity")
assert m["details"]["artifacts"] == 12580, m
assert m["details"]["bytes"] == 745060261, m
assert m["error_count"] == 0, m
print("COMMAND_ARCHIVE_VERIFY_OK")
'

export VERIFIED_COMMAND_ARCHIVE_FINGERPRINT="$(
  printf '%s' "$VERIFY_JSON" | "$PYTHON" -c \
    'import json,sys; print(json.load(sys.stdin)["bundle_fingerprint"])'
)"
```

Store the verify-only JSON, run ID, deployed commit, database identifier,
operator, and approval record together. Do not store database credentials.

Verify that no semantic source records were added:

```sql
SELECT count(*) AS source_records_after_verify FROM crm_source_records;
```

The before and after counts must match. One new `verify_only` run and one
`archive_integrity` result are expected.

## 3. Dry-run domain parsers

First list the domain modules approved in the release notes and confirm they
exist in the default parser registry. An unknown `--module` must fail; do not
remove the module bound to bypass that failure.

Run one parser when reviewing it in isolation:

```bash
DRY_JSON="$(
  "$PYTHON" -m scripts.reconcile_command_archive \
    --dry-run \
    --parser-version "$COMMAND_PARSER_VERSION" \
    --module contacts
)"
printf '%s\n' "$DRY_JSON" | "$PYTHON" -m json.tool
```

Run an explicitly reviewed group by repeating `--module`:

```bash
DRY_JSON="$(
  "$PYTHON" -m scripts.reconcile_command_archive \
    --dry-run \
    --parser-version "$COMMAND_PARSER_VERSION" \
    --module contacts \
    --module tasks
)"
printf '%s\n' "$DRY_JSON" | "$PYTHON" -m json.tool
```

Omitting `--module` selects every parser registered in that deployed revision:

```bash
DRY_JSON="$(
  "$PYTHON" -m scripts.reconcile_command_archive \
    --dry-run \
    --parser-version "$COMMAND_PARSER_VERSION"
)"
printf '%s\n' "$DRY_JSON" | "$PYTHON" -m json.tool
```

Do not use the unbounded form unless every registered parser is in the same
approved change. Each selected module needs a signed reconciliation expectation
containing:

- source system and module name;
- expected observed, rendered, normalized, evidence-only, unmatched, duplicate
  content, and error totals;
- fixture and parser test evidence;
- dry-run ID, bundle fingerprint, parser version, and exact module set;
- disposition for every nonzero unmatched or error total; and
- reviewer and approval timestamp.

The dry-run fingerprint must equal
`$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT`. `status` must be `completed`, and every
metric must match its reviewed expectation. A dry-run creates reconciliation
audit rows but zero semantic source records.

## 4. Apply with the production fingerprint guard

Before apply, rerun verify-only if the deployment, database, archive artifact
count, byte count, or parser revision changed. Apply must use the fingerprint
from that database's most recent accepted verification.

The mandatory production guard is:

```bash
"$PYTHON" -m scripts.reconcile_command_archive \
  --apply \
  --parser-version command-v1 \
  --expect-fingerprint "$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT"
```

For a bounded rollout, name every approved module:

```bash
APPLY_JSON="$(
  "$PYTHON" -m scripts.reconcile_command_archive \
    --apply \
    --parser-version "$COMMAND_PARSER_VERSION" \
    --module contacts \
    --expect-fingerprint "$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT"
)"
printf '%s\n' "$APPLY_JSON" | "$PYTHON" -m json.tool
```

If the expected fingerprint differs by even one character, the CLI refuses
before it creates a reconciliation run or writes a semantic source record. Do
not replace the expected value with the newly reported value without a fresh
verify-only review.

Each successful module is committed as a transaction boundary. Stop on the
first error; preserve the run ID and use the resume procedure after fixing the
cause under a reviewed code or data change.

## 5. Resume a failed or abandoned run

A run can be resumed only while its status is `failed` or `running`, and only
with the identical database bundle fingerprint, parser version, mode, and
module set. Completed runs cannot be resumed. A live worker owns a 30-minute
claim lease; do not start a second worker or manually clear its claim.

Inspect the run before resuming:

```sql
SELECT
  id,
  mode,
  status,
  parser_version,
  bundle_fingerprint,
  requested_modules_json,
  error_text,
  claimed_at,
  started_at,
  completed_at
FROM crm_reconciliation_runs
WHERE id = 42;
```

Resume the same dry run:

```bash
"$PYTHON" -m scripts.reconcile_command_archive \
  --dry-run \
  --parser-version "$COMMAND_PARSER_VERSION" \
  --module contacts \
  --module tasks \
  --resume 42
```

Resume the same apply run, retaining the production guard:

```bash
"$PYTHON" -m scripts.reconcile_command_archive \
  --apply \
  --parser-version "$COMMAND_PARSER_VERSION" \
  --module contacts \
  --module tasks \
  --resume 42 \
  --expect-fingerprint "$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT"
```

Replace `42` with the recorded failed run ID. Already committed successful
module results are skipped; the remaining selected modules continue. If a
`running` run has no live worker, wait for the claim lease to expire and record
the incident before resuming. Never modify claim columns directly.

## 6. Post-run reconciliation queries

Run these queries after verify-only, dry-run, and apply. Archive and run totals
are exact; module-specific totals must match the approved expectation for that
parser version.

Latest run and module results:

```sql
WITH latest AS (
  SELECT id
  FROM crm_reconciliation_runs
  ORDER BY id DESC
  LIMIT 1
)
SELECT
  r.id,
  r.mode,
  r.status,
  r.parser_version,
  r.bundle_fingerprint,
  r.requested_modules_json,
  r.error_text,
  r.started_at,
  r.completed_at
FROM crm_reconciliation_runs r
JOIN latest ON latest.id = r.id;

WITH latest AS (
  SELECT id
  FROM crm_reconciliation_runs
  ORDER BY id DESC
  LIMIT 1
)
SELECT
  rr.source_system,
  rr.module,
  rr.expected_count,
  rr.observed_count,
  rr.rendered_count,
  rr.normalized_count,
  rr.evidence_only_count,
  rr.unmatched_count,
  rr.duplicate_content_count,
  rr.error_count,
  rr.details_json::jsonb AS details
FROM crm_reconciliation_results rr
JOIN latest ON latest.id = rr.run_id
ORDER BY rr.source_system, rr.module;
```

Archive-integrity evidence for the latest verify-only run:

```sql
SELECT
  r.id AS run_id,
  r.status,
  r.bundle_fingerprint,
  rr.details_json::jsonb ->> 'artifacts' AS artifacts,
  rr.details_json::jsonb ->> 'bytes' AS bytes,
  rr.details_json::jsonb -> 'domains' AS domains,
  rr.duplicate_content_count,
  rr.error_count
FROM crm_reconciliation_runs r
JOIN crm_reconciliation_results rr ON rr.run_id = r.id
WHERE r.mode = 'verify_only'
  AND rr.module = 'archive_integrity'
ORDER BY r.id DESC
LIMIT 1;
```

Semantic source-record totals by evidence class:

```sql
SELECT
  source_system,
  module,
  record_kind,
  evidence_level,
  capture_quality,
  parser_version,
  count(*) AS records
FROM crm_source_records
GROUP BY
  source_system,
  module,
  record_kind,
  evidence_level,
  capture_quality,
  parser_version
ORDER BY source_system, module, record_kind, evidence_level, capture_quality;
```

Identity and evidence-link integrity checks:

```sql
SELECT
  source_system,
  module,
  record_kind,
  source_key,
  parser_version,
  count(*) AS duplicate_rows
FROM crm_source_records
GROUP BY source_system, module, record_kind, source_key, parser_version
HAVING count(*) > 1;

SELECT
  sr.id,
  sr.source_system,
  sr.module,
  sr.record_kind,
  sr.source_key,
  sr.evidence_level
FROM crm_source_records sr
LEFT JOIN crm_source_record_artifacts sra ON sra.source_record_id = sr.id
WHERE sr.evidence_level <> 'displayed_aggregate'
GROUP BY sr.id
HAVING count(sra.id) = 0
ORDER BY sr.source_system, sr.module, sr.source_key;

SELECT
  sr.source_system,
  sr.module,
  count(DISTINCT sr.id) AS source_records,
  count(DISTINCT sra.id) AS artifact_links,
  count(DISTINCT es.id) AS entity_links
FROM crm_source_records sr
LEFT JOIN crm_source_record_artifacts sra ON sra.source_record_id = sr.id
LEFT JOIN crm_entity_sources es ON es.source_record_id = sr.id
GROUP BY sr.source_system, sr.module
ORDER BY sr.source_system, sr.module;
```

The duplicate query and non-aggregate missing-link query must return zero rows.
Entity-link counts and displayed-aggregate artifact links may legitimately be
zero when the reviewed parser expectation says the evidence was not
materialized as a business entity.

Confirm no failed or actively claimed run was overlooked:

```sql
SELECT
  id,
  mode,
  status,
  requested_modules_json,
  error_text,
  claimed_at,
  started_at,
  completed_at
FROM crm_reconciliation_runs
WHERE status <> 'completed' OR claim_token <> ''
ORDER BY id DESC;
```

## 7. Rollback and recovery

An application rollback does not require a database downgrade because the
foundation migrations are additive. Prefer this order:

1. stop all reconciliation workers;
2. record the last run ID and preserve its JSON output;
3. deploy the previous application revision;
4. leave the additive provenance and audit tables intact; and
5. diagnose from the immutable archive and reconciliation ledger.

Do not manually delete source records, artifact links, entity links, run rows,
or result rows. The implemented importer has no general semantic undo command;
after an apply, data rollback requires an approved provider snapshot restore or
a separately reviewed compensating migration.

If no apply has occurred and an approved schema-only rollback is required, take
a fresh snapshot and render the downgrade SQL first:

```bash
"$PYTHON" -m alembic downgrade 2e7f9a0b1c2d:1d6e7f8a9b10 --sql \
  > /tmp/command-reconciliation-claim-downgrade.sql
"$PYTHON" -m alembic downgrade 1d6e7f8a9b10
```

That removes only the worker-claim columns. A full pre-foundation downgrade is
destructive to all semantic provenance and reconciliation audit rows:

```bash
"$PYTHON" -m alembic downgrade 2e7f9a0b1c2d:f0c8a6d9e431 --sql \
  > /tmp/command-provenance-full-downgrade.sql
"$PYTHON" -m alembic downgrade f0c8a6d9e431
```

Run the full downgrade only with explicit data-loss approval and a verified
snapshot. It drops the provenance/reconciliation tables but does not drop or
rewrite `crm_archive_artifacts`. After any rollback, rerun the schema and
archive preflight queries and compare them with the stored deployment evidence.

## Recorded compatibility audit: 2026-08-12

A read-only transaction against the configured database found:

- current revision: `f0c8a6d9e431`;
- `crm_archive_artifacts`: 12,580 rows, 745,060,261 declared bytes, zero rows
  missing `content_bytes`; and
- the three provenance/link tables and two reconciliation tables introduced by
  this foundation were not present.

Therefore verify-only was deliberately not executed during this audit. It is
blocked until the normal deployment migration reaches `2e7f9a0b1c2d`; running
verify-only before then would attempt to write audit rows into absent tables.
No migration or semantic reconciliation write was performed by this audit.
