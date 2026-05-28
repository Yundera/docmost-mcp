"""Docmost MCP config UI + transparent proxy in front of mcp-proxy.

- Serves a static config page at `/` (form for Docmost creds + status + tool list).
- Exposes a small JSON API at `/api/*` for the page.
- Streams `/mcp`, `/sse`, `/messages` through to the in-container `mcp-proxy`
  on 127.0.0.1:8001 — so the hash-lock proxy still sees a single backend.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

CONFIG_PATH = Path("/data/config.json")
TOKEN_PATH = Path("/data/token.json")
STATIC_DIR = Path("/app/ui/static")
MCP_UPSTREAM = "http://127.0.0.1:8001"
PUBLIC_PORT = int(os.environ.get("PORT", "8000"))

PROXY_PATHS = ("/mcp", "/sse", "/messages")
HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
}

app = FastAPI(title="Docmost MCP", docs_url=None, redoc_url=None, openapi_url=None)


# ---------- helpers ----------


def _read_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _write_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    # Invalidate cached JWT so the MCP re-auths with whatever's now on disk.
    if TOKEN_PATH.exists():
        TOKEN_PATH.write_text("")


def _redact(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    out["password_set"] = bool(out.get("password"))
    out.pop("password", None)
    return out


# ---------- static UI ----------


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(status_code=204, content=None)


# ---------- config API ----------


@app.get("/api/config")
async def get_config():
    return _redact(_read_config())


@app.put("/api/config")
async def put_config(payload: dict[str, Any]):
    existing = _read_config()
    # Keep existing password if the form left it blank.
    if not payload.get("password"):
        payload["password"] = existing.get("password", "")
    # Sensible defaults so partial saves don't break the upstream config schema.
    payload.setdefault("base_url", "http://docmost")
    payload.setdefault("timeout", 30)
    payload.setdefault("page_content_format", "markdown")
    payload.setdefault("create_space_conflict_policy", "return_existing")
    payload.setdefault("duplicate_page_conflict_policy", "auto_suffix")
    payload.setdefault("clear_parent_on_space_move", True)
    _write_config(payload)
    return {"status": "saved"}


@app.post("/api/test")
async def test_connection(payload: dict[str, Any] | None = None):
    cfg = _read_config()
    if payload:
        # Test the supplied creds without saving; fall back to disk for password.
        base_url = payload.get("base_url") or cfg.get("base_url") or "http://docmost"
        email = payload.get("email") or cfg.get("email", "")
        password = payload.get("password") or cfg.get("password", "")
    else:
        base_url = cfg.get("base_url", "http://docmost")
        email = cfg.get("email", "")
        password = cfg.get("password", "")

    if not email or not password:
        return {"ok": False, "message": "Email and password are required."}

    url = base_url.rstrip("/") + "/api/auth/login"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(url, json={"email": email, "password": password})
    except httpx.RequestError as e:
        return {"ok": False, "message": f"Could not reach {base_url}: {e}"}

    if r.status_code == 200:
        return {"ok": True, "message": "Authenticated against Docmost successfully."}
    snippet = r.text[:160].replace("\n", " ")
    return {"ok": False, "message": f"Docmost returned HTTP {r.status_code}: {snippet}"}


@app.get("/api/status")
async def status():
    cfg = _read_config()
    config_complete = bool(cfg.get("email") and cfg.get("password"))

    mcp_ok = False
    tool_count = 0
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.post(
                f"{MCP_UPSTREAM}/mcp",
                headers={"Accept": "application/json, text/event-stream",
                         "Content-Type": "application/json"},
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "ui-status", "version": "1"},
                    },
                },
            )
            mcp_ok = r.status_code == 200
    except httpx.RequestError:
        pass

    # Pull tool count via a separate call (uses cached JWT — fast).
    if mcp_ok:
        try:
            from mcp import ClientSession  # type: ignore
            from mcp.client.streamable_http import streamablehttp_client  # type: ignore

            async with streamablehttp_client(f"{MCP_UPSTREAM}/mcp") as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    tool_count = len(tools.tools)
        except Exception:
            pass

    return {
        "config_exists": CONFIG_PATH.exists(),
        "config_complete": config_complete,
        "base_url": cfg.get("base_url", ""),
        "email": cfg.get("email", ""),
        "mcp_alive": mcp_ok,
        "tool_count": tool_count,
    }


@app.get("/api/tools")
async def list_tools():
    try:
        from mcp import ClientSession  # type: ignore
        from mcp.client.streamable_http import streamablehttp_client  # type: ignore

        async with streamablehttp_client(f"{MCP_UPSTREAM}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [
                    {"name": t.name, "description": (t.description or "").strip()}
                    for t in tools.tools
                ]
    except Exception as e:
        raise HTTPException(503, f"MCP not ready: {e}")


# ---------- MCP transparent proxy ----------


def _filter_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}


async def _proxy(request: Request) -> StreamingResponse:
    upstream_url = f"{MCP_UPSTREAM}{request.url.path}"
    body = await request.body()
    client = httpx.AsyncClient(timeout=None)
    req = client.build_request(
        method=request.method,
        url=upstream_url,
        headers=_filter_headers(dict(request.headers)),
        content=body,
        params=request.query_params,
    )
    upstream = await client.send(req, stream=True)

    async def stream():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=_filter_headers(dict(upstream.headers)),
        media_type=upstream.headers.get("content-type"),
    )


@app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
@app.api_route("/mcp/", methods=["GET", "POST", "DELETE", "OPTIONS"])
async def proxy_mcp(request: Request):
    return await _proxy(request)


@app.api_route("/sse", methods=["GET", "POST"])
@app.api_route("/messages", methods=["GET", "POST"])
@app.api_route("/messages/", methods=["GET", "POST"])
async def proxy_sse(request: Request):
    return await _proxy(request)


# ---------- entrypoint ----------


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PUBLIC_PORT, log_level="info")
