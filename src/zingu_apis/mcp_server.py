"""MCP server for Zingu API discovery and calling.

Exposes Zingu's API catalog and the zingu-apis SDK as MCP tools,
enabling AI agents to discover, explore, and call APIs.

Run directly:
    python -m zingu_apis.mcp_server

Or via entry point:
    zingu-mcp
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool as MCPTool

import zingu_apis

logger = logging.getLogger("zingu_apis.mcp")

TOOLS = [
    MCPTool(
        name="search_apis",
        description=(
            "Search the Zingu API catalog by keywords. Returns matching APIs with "
            "slugs, names, descriptions, and tags. Use this first to find APIs for a task."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Keywords to search for. Results match any word and rank by number of matches. "
                        "Prefix a word with + to require it (e.g. '+census demographics' requires 'census'). "
                        "Prefix with - to exclude (e.g. 'weather -aviation')."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    MCPTool(
        name="api_info",
        description=(
            "Get metadata for a specific API: base URL, authentication type, "
            "and a list of all available endpoints with their methods and paths. "
            "Use after search_apis to understand what an API offers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "API slug from search results (e.g. 'openweather', 'dayinhistory.dev:day-in-history-api')",
                },
            },
            "required": ["slug"],
        },
    ),
    MCPTool(
        name="endpoint_info",
        description=(
            "Get detailed information about a specific API endpoint: parameters, "
            "pagination style, response content type, and example requests."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "API slug",
                },
                "path": {
                    "type": "string",
                    "description": "Endpoint path (e.g. '/today/events/', '/users/{id}')",
                },
            },
            "required": ["slug", "path"],
        },
    ),
    MCPTool(
        name="call_api",
        description=(
            "Call an API endpoint and return the results. Handles pagination, "
            "auth, retries, and response parsing automatically. "
            "Provide the API slug and endpoint path. Optionally pass parameters "
            "and control pagination limits."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "API slug",
                },
                "path": {
                    "type": "string",
                    "description": "Endpoint path (e.g. '/today/events/', '/weather?q=Berlin')",
                },
                "params": {
                    "type": "object",
                    "description": "Path and query parameters as key-value pairs",
                    "additionalProperties": True,
                },
                "key": {
                    "type": "string",
                    "description": "API key/secret if required. Can also be set via ZINGU_KEY_{SLUG} env var.",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Maximum number of items to return (default: no limit)",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum pages to fetch (default 10)",
                    "default": 10,
                },
            },
            "required": ["slug", "path"],
        },
    ),
]


def _json_text(obj: Any) -> list[TextContent]:
    """Serialize an object to a TextContent JSON block."""
    return [TextContent(type="text", text=json.dumps(obj, indent=2, default=str, ensure_ascii=False))]


def _error_text(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}, indent=2))]


async def _handle_search_apis(arguments: dict) -> list[TextContent]:
    query = arguments["query"]
    limit = arguments.get("limit", 10)
    results = zingu_apis.search(query, limit=limit)
    if not results:
        return _json_text({"results": [], "message": f"No APIs found for '{query}'"})
    return _json_text({"results": results, "count": len(results)})


async def _handle_api_info(arguments: dict) -> list[TextContent]:
    slug = arguments["slug"]
    try:
        client = zingu_apis.api(slug)
    except Exception as exc:
        return _error_text(f"Could not load API '{slug}': {exc}")

    info = client.info()
    tools = client.tools()

    return _json_text({
        "slug": client.slug,
        "base_url": info.get("base_url", ""),
        "authentication": info.get("authentication", "none"),
        "cors": info.get("cors"),
        "endpoints": tools,
    })


async def _handle_endpoint_info(arguments: dict) -> list[TextContent]:
    slug = arguments["slug"]
    path = arguments["path"]
    try:
        client = zingu_apis.api(slug)
    except Exception as exc:
        return _error_text(f"Could not load API '{slug}': {exc}")

    ep = client.endpoint(path)
    info = ep.info()
    params = ep.parameters()
    examples = ep.examples()

    result = {**info}
    if params:
        result["parameters"] = [
            {
                "name": p.name,
                "type": p.type,
                "description": p.description,
                "required": p.required,
                "default": p.default,
            }
            for p in params
        ]
    if examples:
        result["examples"] = examples

    return _json_text(result)


async def _handle_call_api(arguments: dict) -> list[TextContent]:
    slug = arguments["slug"]
    path = arguments["path"]
    params = arguments.get("params")
    key = arguments.get("key")
    max_items = arguments.get("max_items")
    max_pages = arguments.get("max_pages", 10)

    try:
        client = zingu_apis.api(slug, key=key)
    except Exception as exc:
        return _error_text(f"Could not load API '{slug}': {exc}")

    try:
        import re
        placeholders = set(re.findall(r"\{(\w+)\}", path))

        kwargs: dict[str, Any] = {
            "max_pages": max_pages,
            "prune_profile": "llm",
        }
        if params:
            # Split: path placeholders go as params, everything else as query params
            path_params = {k: v for k, v in params.items() if k in placeholders}
            query_params = {k: v for k, v in params.items() if k not in placeholders}
            if path_params:
                kwargs["params"] = path_params
            kwargs.update(query_params)
        if max_items is not None:
            kwargs["max_items"] = max_items

        result = client.call(path, **kwargs)
        return _json_text({
            "data": result.get("data", []),
            "analytics": result.get("analytics", {}),
            "warnings": result.get("warnings", []),
            "errors": result.get("errors", []),
        })
    except Exception as exc:
        return _error_text(f"API call failed: {exc}")


_HANDLERS = {
    "search_apis": _handle_search_apis,
    "api_info": _handle_api_info,
    "endpoint_info": _handle_endpoint_info,
    "call_api": _handle_call_api,
}


def create_server() -> Server:
    """Create and configure the Zingu MCP server."""
    server = Server("zingu-apis")

    @server.list_tools()
    async def list_tools() -> list[MCPTool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        handler = _HANDLERS.get(name)
        if handler is None:
            return _error_text(f"Unknown tool: {name}")
        return await handler(arguments or {})

    return server


async def main() -> None:
    """Run the MCP server over stdio."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def cli_main() -> None:
    """Sync entry point for the zingu-mcp console script."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
