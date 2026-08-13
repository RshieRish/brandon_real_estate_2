# Command Archive Reconciliation Runbook

This runbook is the production operating contract for the recovered Command and
DocuSign archive. It protects the immutable `crm_archive_artifacts` baseline,
records audit-only reconciliation runs, and controls semantic source-record
writes.

The verified archive target is **12,580 artifacts** and **745,060,261 bytes**.
The bundle fingerprint is intentionally not hard-coded: it must be recomputed
from the database that will receive the reconciliation and passed back to apply
mode exactly.

## Current executable safety state

- `--verify-only` validates every stored byte, declared length, and SHA-256. It
  writes only a reconciliation run and one `archive_integrity` result.
- `--dry-run` parses selected modules and writes reconciliation audit rows. It
  does not create or update semantic source records.
- The current default parser registry contains `archive_integrity` and
  `contacts`. `--verify-only` still selects only `archive_integrity`; an
  unbounded `--dry-run` selects both registered modules.
- The current CLI exposes `--apply` and its `--expect-fingerprint` guard, but it
  does not yet implement `--contact-overlap-manifest`, its loader/validator,
  reviewed-link staging, or the Contacts materializer. Therefore **no Contacts
  apply—and no unbounded apply that would include Contacts—is currently
  authorized**. Passing `--contact-overlap-manifest` currently fails as an
  unknown argument.
- The manifest-backed apply/resume commands later in this document are the
  planned Task 4 operating contract, clearly marked **NOT AVAILABLE**. They do
  not become executable merely because they appear in this runbook.
- No module apply is authorized until its parser, materializer, reconciliation
  expectation, and reviewed dry run are all complete for the deployed revision.
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
export CONTACTS_PARSER_VERSION="contacts-v1"
cd "$REPO_ROOT/backend"
```

Confirm the intended commit and database target through the deployment system
before continuing. Only one reconciliation process may operate on a run at a
time.

## 1. Schema and archive preflight

The reconciliation/contact schema is additive. The expected and currently
verified single Alembic head is `4a8c0d1e2f3b`. The relevant linear chain is
`f0c8a6d9e431 -> 1d6e7f8a9b10 -> 2e7f9a0b1c2d -> 4a8c0d1e2f3b`; operators must
upgrade through the chain to the sole head and must not stop at the
intermediate reconciliation-claims revision.

```bash
"$PYTHON" -m alembic heads
"$PYTHON" -m alembic current
"$PYTHON" -m alembic history --indicate-current
```

`alembic heads` must print exactly:

```text
4a8c0d1e2f3b (head)
```

Before a production migration, take a provider-level database snapshot and
render the exact SQL for review:

```bash
"$PYTHON" -m alembic upgrade f0c8a6d9e431:4a8c0d1e2f3b --sql \
  > /tmp/command-contact-parity-upgrade.sql
```

Review the SQL and then, under the approved deployment change, migrate:

```bash
"$PYTHON" -m alembic upgrade 4a8c0d1e2f3b
"$PYTHON" -m alembic current
```

`alembic current` must also report `4a8c0d1e2f3b`. Do not run the reconciliation
CLI if the database is below that sole deployed head or if required provenance,
reconciliation, or contact-parity tables are absent. All CLI modes create audit
rows, so a database at an intermediate revision is not an approved operating
state.

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
  to_regclass('public.crm_reconciliation_results') AS reconciliation_results,
  to_regclass('public.crm_contact_capture_positions') AS contact_positions,
  to_regclass('public.crm_contact_section_captures') AS contact_sections;
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

### Planned Task 4 Contacts private-overlap preflight — NOT AVAILABLE

The following manifest setup and validation contract is **not executable yet**.
The current CLI has no `--contact-overlap-manifest` argument or loader, and this
section does not authorize Contacts apply. It becomes operational only after
Task 4 lands, its tests pass, and the deployed CLI help lists the flag.

After Task 4 is deployed, provision the approved manifest for a manifest-aware
Contacts dry-run, apply, or resume as a
regular access-controlled file outside the repository, deployment bundle,
frontend/static paths, and acceptance-artifact directory. Never paste its
contents into a command, environment variable, ticket, or log. The path may be
an environment variable, but CLI output and errors must never echo it.

```bash
# NOT AVAILABLE — planned Task 4 preflight; do not use to authorize apply.
export CONTACT_OVERLAP_MANIFEST="<absolute-private-path-outside-repository>"
test -n "$CONTACT_OVERLAP_MANIFEST"
test -f "$CONTACT_OVERLAP_MANIFEST"
test ! -L "$CONTACT_OVERLAP_MANIFEST"
case "$CONTACT_OVERLAP_MANIFEST" in
  "$REPO_ROOT"/*) echo "manifest must be outside the repository" >&2; exit 1 ;;
esac
```

The loader requires schema `command-contact-overlaps-v1`, the exact verified
bundle fingerprint, the selected parser version, and exactly two unique rows.
Each row contains only a hashed strong source-provider identity, one positive
existing `CRMContact.id`, a non-PII target-row fingerprint, and a
strong-evidence hash. V1 has no alternate target key. It rejects raw name,
email, phone, provider ID, address, payload, and unknown fields. Validation
resolves each hash to one parsed source identity, requires each target ID to be
an existing `lead_id IS NOT NULL` contact, checks the target-row fingerprint
again immediately before staging, and independently recomputes the approved
strong-email evidence. Record only the canonical manifest digest, row count
`2`, validation state, and audit/run IDs.

## 3. Dry-run domain parsers

The current default registry contains exactly `archive_integrity` and
`contacts`. An unknown `--module` must fail; do not remove the module bound to
bypass that failure.

Run one parser when reviewing it in isolation:

```bash
DRY_JSON="$(
  "$PYTHON" -m scripts.reconcile_command_archive \
    --dry-run \
    --parser-version "$CONTACTS_PARSER_VERSION" \
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
    --module archive_integrity \
    --module contacts
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

The unbounded form currently selects `archive_integrity` and `contacts`; it does
not validate the future overlap manifest. Do not use it unless both registered
parsers are in the same approved dry-run review. Each selected module needs a signed reconciliation expectation
containing:

- source system and module name;
- expected observed, rendered, normalized, evidence-only, unmatched, duplicate
  content, and error totals;
- fixture and parser test evidence;
- dry-run ID, bundle fingerprint, parser version, and exact module set;
- disposition for every nonzero unmatched or error total; and
- reviewer and approval timestamp.

Current Contacts dry-run validates parser/archive truth only; the future
manifest validation is **not available** until Task 4. The dry-run fingerprint must equal
`$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT`. `status` must be `completed`, and every
metric must match its reviewed expectation. A dry-run creates reconciliation
audit rows but zero semantic source records.

After Task 4 is deployed, the additional manifest-aware dry-run command will be:

```bash
# NOT AVAILABLE — planned Task 4 command; the current CLI rejects this flag.
"$PYTHON" -m scripts.reconcile_command_archive \
  --dry-run \
  --parser-version "$CONTACTS_PARSER_VERSION" \
  --module contacts \
  --contact-overlap-manifest "$CONTACT_OVERLAP_MANIFEST"
```

## 4. Planned Task 4 Contacts apply — NOT AVAILABLE; DO NOT RUN

The current CLI lacks the manifest loader, reviewed-link service, and Contacts
materializer. Although it exposes a generic `--apply`, running it for Contacts
would persist incomplete source-only state. **Every Contacts apply and every
unbounded apply is blocked until Task 4 is implemented, reviewed, and deployed.**
The commands in this section are future acceptance commands, not current
operator instructions.

Before apply, rerun verify-only if the deployment, database, archive artifact
count, byte count, or parser revision changed. Apply must use the fingerprint
from that database's most recent accepted verification.

The mandatory production guard is:

```bash
# NOT AVAILABLE — planned Task 4 production command; do not run today.
"$PYTHON" -m scripts.reconcile_command_archive \
  --apply \
  --parser-version "$CONTACTS_PARSER_VERSION" \
  --module contacts \
  --contact-overlap-manifest "$CONTACT_OVERLAP_MANIFEST" \
  --expect-fingerprint "$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT"
```

For a bounded rollout, name every approved module:

```bash
# NOT AVAILABLE — planned Task 4 production command; do not run today.
APPLY_JSON="$(
  "$PYTHON" -m scripts.reconcile_command_archive \
    --apply \
    --parser-version "$CONTACTS_PARSER_VERSION" \
    --module contacts \
    --contact-overlap-manifest "$CONTACT_OVERLAP_MANIFEST" \
    --expect-fingerprint "$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT"
)"
printf '%s\n' "$APPLY_JSON" | "$PYTHON" -m json.tool
```

If the expected fingerprint differs by even one character, the CLI refuses
before it creates a reconciliation run or writes a semantic source record. Do
not replace the expected value with the newly reported value without a fresh
verify-only review.

Each successful module is committed as a transaction boundary. For Contacts,
the transaction order is: persist and flush exact source records; revalidate
the manifest against those records, existing lead-backed contacts, and strong
evidence; create two reviewed `crm_entity_sources` links and append-only contact
audit events; run the materializer, which creates the other 315 mappings and
four missing recovered contacts; write the result; commit. Any failure rolls
back every Contacts module write. Stop on the first error; preserve the run ID
and use the resume procedure after fixing the cause under a reviewed code or
data change.

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

Resume a current parser-only Contacts dry run:

```bash
"$PYTHON" -m scripts.reconcile_command_archive \
  --dry-run \
  --parser-version "$CONTACTS_PARSER_VERSION" \
  --module contacts \
  --resume 42
```

The future manifest-aware dry-run resume and Contacts apply resume are **not
available** until Task 4 is deployed:

```bash
# NOT AVAILABLE — planned Task 4 dry-run resume; current CLI rejects the flag.
"$PYTHON" -m scripts.reconcile_command_archive \
  --dry-run \
  --parser-version "$CONTACTS_PARSER_VERSION" \
  --module contacts \
  --contact-overlap-manifest "$CONTACT_OVERLAP_MANIFEST" \
  --resume 42

# NOT AVAILABLE — planned Task 4 apply resume; do not run today.
"$PYTHON" -m scripts.reconcile_command_archive \
  --apply \
  --parser-version "$CONTACTS_PARSER_VERSION" \
  --module contacts \
  --contact-overlap-manifest "$CONTACT_OVERLAP_MANIFEST" \
  --resume 42 \
  --expect-fingerprint "$VERIFIED_COMMAND_ARCHIVE_FINGERPRINT"
```

Replace `42` with the recorded failed run ID. Once Task 4 exists, a
manifest-aware Contacts resume must use the
same approved private file and must revalidate its exact source/target/evidence
set against the run's identical fingerprint/parser version; never substitute a
newly reviewed mapping into an existing run. Already committed successful
module results are skipped; the remaining selected modules continue. If a
`running` run has no live worker, wait for the claim lease to expire and record
the incident before resuming. Never modify claim columns directly.

## 6. Post-run reconciliation queries

Run these queries after currently supported verify-only and dry-run operations.
After Task 4 is deployed, the same general ledger queries also apply to an
authorized apply. Archive and run totals are exact; module-specific totals must
match the approved expectation for that parser version.

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

The following Contacts-repair acceptance block is **NOT AVAILABLE** until Task
4's manifest loader, reviewed-link service, and materializer are deployed. At
that future checkpoint, the result details and database must agree on these
non-private totals:

```text
preexisting contacts                         362
reviewed overlap links staged                  2
source/entity links created by materializer  315
final recovered contact mappings             317
recovered contacts newly created               4
final contacts                               366
lead-backed contacts                          51
lead-backed legacy-only contacts              49
```

```sql
-- NOT AVAILABLE — planned Task 4 post-apply acceptance queries.
SELECT count(*) FROM crm_contacts; -- 366
SELECT count(*), count(DISTINCT lead_id)
FROM crm_contacts WHERE lead_id IS NOT NULL; -- 51, 51
SELECT count(*) FROM crm_entity_sources WHERE entity_type = 'contact'; -- 317
SELECT count(*) FROM crm_contact_capture_positions; -- 317
SELECT count(*) FROM crm_contact_section_captures; -- 2536
```

The Contacts result must report only the canonical manifest digest, manifest
row count `2`, validation state, `reviewed_overlap_links_staged=2`,
`source_entity_links_created_by_materializer=315`,
`source_entity_links_final=317`, and `expected_combined_contact_total=366`.
Never include the private manifest path, its selectors, raw identity evidence,
or source payloads. Repeat the same apply once and prove it creates zero
contacts, source/entity links, audit events, source artifacts, and contact
extension rows.

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

If no apply has occurred and an explicitly approved schema-only rollback from
the current sole head is required, take a fresh snapshot and render the entire
requested downgrade chain first. The following rollback removes both the
`4a8c0d1e2f3b` contact-parity schema and the `2e7f9a0b1c2d` worker-claim change,
ending at `1d6e7f8a9b10`:

```bash
"$PYTHON" -m alembic downgrade 4a8c0d1e2f3b:1d6e7f8a9b10 --sql \
  > /tmp/command-contact-and-claim-downgrade.sql
"$PYTHON" -m alembic downgrade 1d6e7f8a9b10
```

Do not treat the intermediate `2e7f9a0b1c2d` revision as a supported stopping
point. A full pre-foundation downgrade from the sole head is destructive to the
contact-parity schema and all semantic provenance/reconciliation audit rows:

```bash
"$PYTHON" -m alembic downgrade 4a8c0d1e2f3b:f0c8a6d9e431 --sql \
  > /tmp/command-provenance-full-downgrade.sql
"$PYTHON" -m alembic downgrade f0c8a6d9e431
```

Run either downgrade only with explicit data-loss approval and a verified
snapshot. The full downgrade drops the contact-parity and
provenance/reconciliation tables but does not drop or rewrite
`crm_archive_artifacts`. After any rollback, rerun the schema and archive
preflight queries and compare them with the stored deployment evidence.

## Recorded compatibility audit: 2026-08-12

A read-only transaction against the configured database found:

- current revision: `f0c8a6d9e431`;
- `crm_archive_artifacts`: 12,580 rows, 745,060,261 declared bytes, zero rows
  missing `content_bytes`; and
- the three provenance/link tables and two reconciliation tables introduced by
  this foundation were not present.

Therefore verify-only was deliberately not executed during this audit. The
normal deployment must now traverse the full chain to the sole head
`4a8c0d1e2f3b`; operators must not stop at `2e7f9a0b1c2d`. Running verify-only
before the full approved migration would attempt to write audit rows into an
unsupported schema state. No migration or semantic reconciliation write was
performed by this audit.
