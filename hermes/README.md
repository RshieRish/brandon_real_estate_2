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
authoritative receipts reach the local WAL.

Rollout order is master write-only, exact backfill/reconciliation, retrieval,
projection, then controlled retry. Rollback disables retry/projection/retrieval
before the master switch and preserves PostgreSQL, `state.db`, and the spool.
