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

The current live `atlas-agent` service is based on
`praveen-ks-2001/hermes-agent-template` and was redeployed from a patched staging
copy because Railway SSH requires a higher project role.

Overlay steps used for deployment:

1. Copy `hermes/atlas_backend_mcp.py` into the template root as
   `atlas_backend_mcp.py`.
2. Add this Dockerfile line after `COPY server.py /app/server.py`:

   ```dockerfile
   COPY atlas_backend_mcp.py /app/atlas_backend_mcp.py
   ```

3. Patch the template `write_config_yaml` path so it adds
   `mcp_servers.atlas_backend` when `BRANDON_BACKEND_URL` and
   `BRANDON_AGENT_CONTROL_TOKEN` are present.
4. Deploy with:

   ```bash
   scripts/railway-sweeney up /tmp/hermes-agent-template-inspect \
     --service atlas-agent \
     --environment production \
     --path-as-root \
     --detach \
     --message "Deploy atlas backend MCP bridge" \
     --json
   ```

The live deployment that first included this bridge was
`8dcd567b-0c27-4eda-a7ef-46104aff91fe`.
