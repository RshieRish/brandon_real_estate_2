# Command captured-data presentation repair

This is a follow-up to the completed Task 8/9 rollout, not a new import. It repairs usable mailing-address fields, timeline interpretation, contact-section presentation, Sydney reply/task reads, and browsing of the existing DocuSign archive.

## Safety boundaries

- Do not reapply the contacts archive or run an Alembic migration for this repair. The schema remains at `87a0d9b1e3f2`.
- Preserve original artifacts, source payloads, capture coordinates, later CRM edits, and durable Telegram history. Read-time timeline projections do not rewrite historical timestamps or invent a timezone.
- The original importer sometimes combined several activities in one source row. Display a source-backed activity group with stable IDs and original intervening dates; do not fabricate separate persisted event identities or silently hide embedded activity.
- An unsupported activity-shaped capture is explicitly review-needed, never a verified-empty timeline. Ordinary note text that resembles a date, footer, or Reply control remains content unless archive structure proves otherwise.
- Keep imported and SWS-owned counts separate. Same-title tasks are not deletion or deduplication authority. Captured budgets are not transaction values, and date-only deadlines are not timestamps.
- DocuSign browsing is authenticated archive access, not a live DocuSign connection. ZIP members are addressed by their exact index, names are preserved, unsafe members remain non-downloadable, and verified downloads never execute or extract files on the server.
- Do not send cards, create outreach, sign documents, reconnect providers, or send Telegram test messages as part of this repair. Card fulfillment remains disabled pending a contracted provider connection.

## Release and additive address recovery

1. Require independent reviews, green release CI, and the exact deployed source revision for backend, worker, Atlas, and frontend. The generated Atlas image must match the repository overlay/managed-skill assets and preserve the ordered 27-tool registry.
2. Create a private PostgreSQL custom-format backup outside the repository. Verify its mode, size, SHA-256, and `pg_restore --list` before any production data change. Keep the backup path and checksum in the private operator release record.
3. Run the deployed/reviewed address repair module in dry-run mode from `backend` using the authorized database environment:

   ```text
   python -m scripts.repair_captured_contact_addresses
   ```

4. Review its exact fingerprint, proposed count, structured count, and review-needed contacts. Before this repair, the reviewed production plan contains 207 new addresses: 205 complete structured records and two formatted-only records requiring review. Thirteen of the existing September campaign's fourteen recipients have complete captured addresses; one has none. These are historical source-backed addresses, not independent proof of present deliverability.
5. Apply only that reviewed fingerprint with a new private JSON backup path outside the repository:

   ```text
   python -m scripts.repair_captured_contact_addresses --apply --expected-plan REVIEWED_SHA256 --backup-path /private/operator-backups/new-address-repair.json
   ```

   The module takes a transaction advisory lock, uses READ COMMITTED, verifies contact/source coordinates, writes and verifies the exclusive mode-0600 backup, locks contacts, and checks a fresh plan before adding rows. Any existing address or changed plan wins over the import. Source JSON and original archive bytes are never rewritten. Audit records contain source/backup hashes, not address text.
6. Repeat the dry run: it must propose zero new rows. Re-read all inserted address fields, contact ownership, audit counts, source hashes, and the September audience using installed code.
7. Existing campaign drafts hold frozen address snapshots. Their explicit **Check updated addresses** action fills only missing snapshots, preserves recipients/messages/designs/exclusions, increments the version, and invalidates approval. It neither creates recipients nor approves or sends. GET requests never refresh or write a campaign.

## Acceptance evidence

- Compare every recovered contact's cursor-paginated timeline against its linked, byte-verified capture. Confirm no duplicated keys, no ORM writes, source-precision dates, retained literal text, explicit unsupported states, and valid activity groups.
- Verify contact task dates, opportunity budgets, saved-search criteria, SmartPlan names, and separate internal/recovered counts on desktop and narrow screens.
- Inventory the imported DocuSign folders, bundles, and PDFs; verify content sizes/hashes and sample exact-index member downloads. Do not describe source captures as signed documents or the imported archive as the current external account.
- Recheck Sydney with isolated read-only existing-history probes. Ordinary replies retain actual authorized names and omit technical audience metadata; explicit metadata requests remain possible. Compression and synthetic continuations must preserve the real current-request boundary, and the already-sanitized persisted final reply must also be cleaned without restoring redacted text.
- Default active-task reads include only open/in-progress, nonarchived, non-controlled-test tasks before the limit. History and controlled-test inclusion are explicit options; ordinary titles containing words such as water test must remain visible.
- Keep real Telegram delivery and card-provider connectivity distinct from isolated model/tool checks. Never claim an external delivery receipt from a local test or read-only canary.

Exact execution results and release state belong at the top of `tdtn.md` and project `memory.md`.
