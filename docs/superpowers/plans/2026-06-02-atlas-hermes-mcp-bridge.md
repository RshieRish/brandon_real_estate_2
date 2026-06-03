# Atlas Hermes MCP Bridge Plan

## Goal

Wire Hermes/Atlas to the existing protected FastAPI `agent-control` action surface without duplicating authorization or Workspace safety rules inside Hermes.

## Constraints

- Keep `railway login` untouched; use `scripts/railway-sweeney`.
- Do not commit secrets.
- Use the existing backend bearer token gate and confirmation checks.
- Avoid adding the official MCP Python package to the backend environment because it conflicts with the current FastAPI dependency pins.
- Update `tdtn.md` and `memory.md` when the task is complete.

## Plan

1. Add tests for a stdio MCP bridge module:
   - publishes the 15 backend action tools plus action catalog read
   - maps tool calls to the correct backend paths and query/body payloads
   - returns MCP-compatible JSON-RPC responses
   - preserves backend errors in a tool-call error payload
2. Implement a stdlib-only `hermes/atlas_backend_mcp.py` bridge:
   - reads `BRANDON_BACKEND_URL` and `BRANDON_AGENT_CONTROL_TOKEN`
   - exposes `tools/list` and `tools/call`
   - calls the FastAPI bridge with bearer auth
   - never logs or prints secrets
3. Document the Hermes config snippet and live installation process.
4. Run focused local tests and backend smoke tests.
5. Install the bridge script into the Hermes persistent volume and add `mcp_servers.atlas_backend` to `/data/.hermes/config.yaml` if the live service allows SSH/config access.
6. Restart or reload Hermes and verify health/config without printing credentials.
