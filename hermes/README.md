# Atlas Hermes Bridge

This folder contains Brandon's Hermes-side bridge into the protected FastAPI
`agent-control` API.

## Bridge

`atlas_backend_mcp.py` is a stdlib-only stdio MCP server. Hermes exposes its
tools as `mcp_atlas_backend_<tool_name>` after the server is listed in
`mcp_servers`.

Required runtime env vars:

- `BRANDON_BACKEND_URL`
- `BRANDON_AGENT_CONTROL_TOKEN`

Both live on the Railway `atlas-agent` service. Do not commit or print the
token.

## Sydney's model-visible business tools

The exact private Sydney identity receives only `skill_view`, the scoped durable
history tool, and the approved Atlas business schemas. The filter runs after
Hermes finishes registering native, memory, and context-engine schemas and is
reapplied before each inbound request, including cached-agent reuse. The shared
Hermes registry and other identities are not modified. The execution guard and
server-counted invocation limit remain separate fail-closed defenses.

When this removes obsolete native tools, the existing conversation's cached
system prompt is rebuilt and persisted without deleting messages, changing the
session identity, or firing a new-session hook. Brandon does not need a reset
to receive the new tool instructions. A policy-halt explanation is recorded as
a terminal failure after delivery, never as a successful business run.

Do not use `tools/list` alone as proof of Sydney routing. The exact-version gate
also constructs a real `AIAgent`, inspects its model-visible schemas, and resumes
it against `SessionDB` containing obsolete tool instructions. A deployed routing
check must distinguish isolated read-only model verification from a real
Telegram request and must never fake a delivery receipt.

## Railway Template Overlay

The overlay is reproducible and refuses moving or dirty source trees:

- template repository commit: `7224d7c1a4dcffe9304f49bc843f55716f5561b4`
- official Hermes tag: `v2026.5.29.2`
- official Hermes commit: `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`
- patched upstream files: hash-pinned in `overlay/manifest.json`

Apply it to a detached template checkout with:

```bash
python hermes/overlay/apply_overlay.py --source /path/to/exact-template
```

The generated Dockerfile copies the Sydney installer before the official Hermes
clone, validates the official source hashes, installs the memory provider,
spool, retry policy, backfill, gateway watcher, and runtime hooks, then installs
Hermes. Applying either layer twice is a byte-for-byte no-op. Unrelated dirty or
partially patched inputs fail closed.

Sydney's canonical history is PostgreSQL. `${HERMES_HOME}/state.db` remains the
Hermes transcript and `${HERMES_HOME}/sydney_spool.db` is a private mode-0600 WAL
outbox/cache that survives process and provider failures. Only visible user,
assistant, tool-call, and tool-result content is retained; hidden reasoning is
omitted and common credentials are irreversibly redacted before local enqueue.

In addition to the two bridge variables, the Atlas service requires:

- `SYDNEY_DURABLE_CONTEXT_ENABLED`
- `SYDNEY_DURABLE_CONTEXT_RETRIEVAL_ENABLED`
- `SYDNEY_DURABLE_CONTEXT_RETRY_ENABLED`
- `SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID`
- `SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID`
- `SYDNEY_DURABLE_CONTEXT_ALLOWED_USER_IDS`
- optional `SYDNEY_DURABLE_CONTEXT_DISPLAY_LABEL`

The provider is registered only when the master flag, backend URL/token, and
configured external identity all pass the allowlist. Other identities cannot
write to the Sydney spool. Runtime configuration fixes session reset to `none`,
turns to 16, recall to 16,000 tokens, rolling input to 500,000 tokens/minute,
compression/loop limits to the reviewed values, and persists longer provider
waits for automatic continuation. Brandon never needs to issue `/new`, `/reset`,
or `/compact` for recovery.

## Managed Atlas Skill and Guarded Recovery

The authoritative operations skill lives at
`hermes/skills/atlas-backend-operations/SKILL.md`. The overlay copies it into the
image and the bootstrap verifies the SHA-256 pinned in `overlay/manifest.json`
before atomically installing it at
`${HERMES_HOME}/skills/productivity/atlas-backend-operations/SKILL.md`. A second
install is a no-op, unrelated skills are preserved, and a source or installed
hash mismatch stops startup. The skill routes Command contacts only through
`command_contacts_search` and `command_contact_audience_preview`; a Command URL
is a navigation locator, Google Contacts is a different source, and the old KW
roster is historical unless Brandon explicitly requests it.

Legacy recovery is explicit and dry-run-first. Resolve the three selectors at
action time without printing or storing the prompt text, then run inside Atlas:

```bash
cd /opt/hermes-agent
python -m plugins.memory.sydney.sydney_recovery \
  --state-db /data/.hermes/state.db \
  --spool /data/.hermes/sydney_spool.db \
  --session-id "$RECOVERY_SESSION_ID" \
  --message-id "$RECOVERY_MESSAGE_ID" \
  --expected-content-sha256 "$RECOVERY_CONTENT_SHA256"
```

Accept only content-free output with `eligible=true`, `enqueued=false`, and
`recovery_policy=review_only`. After independently checking those selectors,
repeat the exact command with `--enqueue` once. Replaying the same command is
idempotent; different content or lineage is rejected.

A recovered run may use current read-only context and Command tools. It must
return the audience count, checksum/reference, masked sample, and proposed
subject/body, state that nothing was sent, and stop for fresh Brandon approval.
The runtime blocks and records every draft, send, Docs, Sheets, Calendar, CRM,
Command, or other mutating tool before execution, including after restart.
Historical wording such as “send this” is not fresh approval. Do not create a
new session or ask Brandon to use a slash command.

There is no background recovery scanner. Rollback means do not invoke admission
again; if a run is already queued, disable Sydney retry and preserve its original
event, spool record, claimed-run evidence, and canonical history. Never delete a
recovery record merely to stop it.

## Backfill and Reconciliation

Run the installed backfill inside Atlas against the persistent transcript and
spool. With `--reconcile`, it drains only `backfill:` rows through the protected
backend, uses authoritative ingest receipts, and exits nonzero on any count or
hash mismatch:

```bash
cd /opt/hermes-agent
python -m plugins.memory.sydney.sydney_backfill \
  --state-db /data/.hermes/state.db \
  --spool /data/.hermes/sydney_spool.db \
  --platform telegram \
  --user-id "$SYDNEY_DURABLE_CONTEXT_EXTERNAL_USER_ID" \
  --chat-id "$SYDNEY_DURABLE_CONTEXT_EXTERNAL_CHAT_ID" \
  --display-label "${SYDNEY_DURABLE_CONTEXT_DISPLAY_LABEL:-Brandon}" \
  --reconcile
```

The JSON report is content-free. Accept it only when `matched=true`,
`unacknowledged_count=0`, source and acknowledged counts/global hashes agree,
and every opaque session entry matches. Normal new events invalidate the prior
backend reconciliation marker and are re-reconciled automatically after their
authoritative receipts reach the local WAL. Periodic reconciliation reads only a
bounded dirty-session queue backed by persisted per-session aggregates;
compacted inbound tombstones retain a content-free terminal disposition so
platform redelivery is never described as newly queued.

Rollout order is master write-only, exact backfill/reconciliation, retrieval,
projection, then controlled retry. Rollback disables retry/projection/retrieval
before the master switch and preserves PostgreSQL, `state.db`, and the spool.
The bootstrap restores Sydney-owned Hermes config from its private sidecar even
when bridge credentials are missing during rollback.
