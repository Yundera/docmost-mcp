FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG DOCMOST_MCP_REF=107b06bed2d1e6808346a093f2fa48a529348e9a
RUN git clone https://github.com/aleksvin8888/local-docmost-mcp.git src \
    && cd src && git checkout ${DOCMOST_MCP_REF}

RUN pip install --no-cache-dir -r src/requirements.txt mcp-proxy==0.12.0 \
    fastapi httpx

# Persist config.json and token.json on a mounted volume.
# Upstream loads both from Path(__file__).parent (no env override),
# so we symlink them into /app/src.
RUN ln -s /data/config.json /app/src/config.json \
    && ln -s /data/token.json /app/src/token.json

COPY ui /app/ui
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT}/healthz -o /dev/null || exit 1

CMD ["/entrypoint.sh"]
