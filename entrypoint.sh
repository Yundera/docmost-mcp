#!/bin/sh
set -e

# On first start, generate /data/config.json from env vars. Once written, the
# file is the source of truth — re-running with different env vars does NOT
# overwrite it. Delete /data/config.json to force regeneration.
if [ ! -f /data/config.json ]; then
  echo "[entrypoint] /data/config.json not found — generating from env vars."

  # Booleans must be unquoted in JSON; default to true.
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
    echo "[entrypoint] /data/config.json is filled in (via the UI or directly)."
  fi
fi

# Ensure JWT cache file exists so the symlink target resolves.
touch /data/token.json

exec mcp-proxy --port=${PORT} --host=0.0.0.0 -- python /app/src/mcp_server.py
