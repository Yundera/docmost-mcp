#!/bin/bash
set -e

# On first start, generate /data/config.json from env vars. Once written, the
# file is the source of truth — re-running with different env vars does NOT
# overwrite it. Delete /data/config.json (or edit it via the UI) to change
# credentials later.
if [ ! -f /data/config.json ]; then
  echo "[entrypoint] /data/config.json not found — generating from env vars."

  CLEAR_PARENT="${DOCMOST_CLEAR_PARENT_ON_SPACE_MOVE:-true}"

  cat > /data/config.json <<EOF
{
  "base_url": "${DOCMOST_BASE_URL:-http://docmost}",
  "email": "${DOCMOST_EMAIL:-}",
  "password": "${DOCMOST_PASSWORD:-}",
  "timeout": ${DOCMOST_TIMEOUT:-30},
  "page_content_format": "${DOCMOST_PAGE_CONTENT_FORMAT:-markdown}",
  "create_space_conflict_policy": "${DOCMOST_CREATE_SPACE_CONFLICT_POLICY:-return_existing}",
  "duplicate_page_conflict_policy": "${DOCMOST_DUPLICATE_PAGE_CONFLICT_POLICY:-auto_suffix}",
  "clear_parent_on_space_move": ${CLEAR_PARENT}
}
EOF

  if [ -z "${DOCMOST_EMAIL}" ] || [ -z "${DOCMOST_PASSWORD}" ]; then
    echo "[entrypoint] WARNING: DOCMOST_EMAIL or DOCMOST_PASSWORD is empty."
    echo "[entrypoint] The MCP will start but Docmost API calls will fail until"
    echo "[entrypoint] credentials are entered via the UI at /."
  fi
fi

# Ensure JWT cache file exists so the symlink target resolves.
touch /data/token.json

# Start mcp-proxy bound to loopback so only the UI process can reach it.
echo "[entrypoint] starting mcp-proxy on 127.0.0.1:8001"
mcp-proxy --port=8001 --host=127.0.0.1 -- python /app/src/mcp_server.py &
MCP_PID=$!

# Start the UI / public proxy on PORT (default 8000).
echo "[entrypoint] starting UI on 0.0.0.0:${PORT}"
python /app/ui/server.py &
UI_PID=$!

# If either process exits, bail so Docker restarts the container.
wait -n
echo "[entrypoint] one of the child processes exited; shutting down."
kill $MCP_PID $UI_PID 2>/dev/null || true
exit 1
