# Docmost MCP

A Yundera/CasaOS app and Docker image that exposes [Docmost](https://docmost.com)
as an MCP (Model Context Protocol) server — so AI assistants (Claude Desktop,
Claude Code, Cursor, VS Code, etc.) can read, search, create, and edit pages in
a self-hosted Docmost instance.

This image wraps the community
[`aleksvin8888/local-docmost-mcp`](https://github.com/aleksvin8888/local-docmost-mcp)
Python server with [`mcp-proxy`](https://github.com/sparfenyuk/mcp-proxy) to
expose it over streamable-HTTP / SSE on port `8000`.

> Docmost's own MCP server is Enterprise/paid-plan only. This image is a free,
> OSS alternative that works against any self-hosted Docmost instance via its
> REST API.

## Tools exposed

| Tool | Description |
|------|-------------|
| `list_spaces` | List all workspace spaces |
| `search_docs` | Full-text search across pages |
| `get_page` | Read page content as Markdown |
| `create_space` | Create a new space |
| `create_page` | Create a new page from Markdown |
| `update_page` | Update title/content (replace/append/prepend) |
| `duplicate_page` | Duplicate a page (recursive) |
| `move_page` | Move a page within the hierarchy |
| `move_page_to_space` | Move a page across spaces |
| `create_comment` | Add a comment to a page |
| `resolve_comment` | Resolve a comment with a note |

## Image

Pulled from GHCR — built and published by this repo's workflow:

```
ghcr.io/yundera/docmost-mcp:latest
ghcr.io/yundera/docmost-mcp:<version>
```

Multi-arch: `linux/amd64`, `linux/arm64`.

## Configuration

The container expects a `config.json` mounted at `/data/config.json`:

```json
{
  "base_url": "http://docmost",
  "email": "your-email@example.com",
  "password": "your-password",
  "timeout": 30,
  "page_content_format": "markdown",
  "create_space_conflict_policy": "return_existing",
  "duplicate_page_conflict_policy": "auto_suffix",
  "clear_parent_on_space_move": true
}
```

A JWT is cached at `/data/token.json` after first login.

**Security:** the account used here has access to whatever spaces it can see in
Docmost. For least-privilege, create a dedicated service user in Docmost rather
than reusing an admin account.

## Deploy on CasaOS / Yundera

Use the `docker-compose.yml` in this repo. It expects three Yundera
template variables to be substituted at install time:

- `${domain}` — your instance domain (e.g. `holyhorse.nsl.sh`)
- `${AUTH_HASH}` — auth hash for the `nginx-hash-lock` proxy
- `${default_pwd}` — bearer password for clients

Put your Docmost credentials in `/DATA/AppData/docmost-mcp/config.json`
before first start.

## Deploy standalone (plain Docker)

```bash
mkdir -p ./data
cp config.example.json ./data/config.json
# edit ./data/config.json with your Docmost URL + credentials

docker run -d --name docmost-mcp \
  -v $(pwd)/data:/data \
  -p 8000:8000 \
  ghcr.io/yundera/docmost-mcp:latest
```

Then connect any MCP client to `http://localhost:8000/mcp`.

## Connecting an MCP client

Public URL (behind the `nginx-hash-lock` proxy):

```json
{
  "mcpServers": {
    "docmost-mcp": {
      "type": "http",
      "url": "https://docmostmcp-<your-domain>/mcp",
      "headers": { "Authorization": "Bearer <YOUR_BEARER_TOKEN>" }
    }
  }
}
```

Internal Docker network (no auth, for containers on the `pcs` network):

```json
{
  "mcpServers": {
    "docmost-mcp": {
      "type": "http",
      "url": "http://docmost-mcp:8000/mcp"
    }
  }
}
```

## Build locally

```bash
docker build -t docmost-mcp:dev .
```

To pin to a different upstream commit:

```bash
docker build --build-arg DOCMOST_MCP_REF=<commit-sha> -t docmost-mcp:dev .
```

## Releasing

- Push to `main` → image published as `:latest` and `:main`
- Tag `vX.Y.Z` → image published as `:X.Y.Z`, `:X.Y`, `:X`

## License

MIT. See [LICENSE](LICENSE).

Upstream Python server (`aleksvin8888/local-docmost-mcp`) is licensed
separately — see that project for details.
