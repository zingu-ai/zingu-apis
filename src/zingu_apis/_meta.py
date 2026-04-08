"""Fetch and resolve API metadata from Zingu."""

from __future__ import annotations

import logging
import os

import requests

from . import _cache
from ._types import APIMeta, EndpointMeta, PaginationConfig

logger = logging.getLogger("zingu_apis")

# Default: production Zingu public API
_ZINGU_BASE = "https://zingu.ai/api"
_ZINGU_API_KEY: str | None = None


def configure(
    base_url: str | None = None,
    api_key: str | None = None,
) -> None:
    """Override the Zingu metadata base URL and/or API key.

    The API key can also be set via the ZINGU_API_KEY environment variable.
    """
    global _ZINGU_BASE, _ZINGU_API_KEY
    if base_url is not None:
        _ZINGU_BASE = base_url.rstrip("/")
    if api_key is not None:
        _ZINGU_API_KEY = api_key


def _get_api_key() -> str | None:
    return _ZINGU_API_KEY or os.environ.get("ZINGU_API_KEY")


def _parse_pagination(raw: dict | None) -> PaginationConfig | None:
    if not raw:
        return None
    style = raw.get("style") or raw.get("pagination_type")
    if not style or style == "none":
        return None
    # Normalize DB values to our style names
    style_map = {"page": "page_number", "offset": "offset_limit"}
    style = style_map.get(style, style)
    return PaginationConfig(
        style=style,
        results_key=raw.get("results_key", "results"),
        next_key=raw.get("next_key", "next"),
        cursor_field=raw.get("cursor_field") or raw.get("pagination_cursor_field"),
        page_param=raw.get("page_param", "page"),
        limit_param=raw.get("limit_param", "limit"),
        offset_param=raw.get("offset_param", "offset"),
        in_header=raw.get("in_header", False) or raw.get("pagination_in_header", False),
    )


def _parse_meta_response(slug: str, data: dict) -> APIMeta:
    """Parse the /api/meta/{slug} response into APIMeta.

    Response shape:
    {
        "slug": "...",
        "base_url": "...",
        "auth_type": "none",
        "endpoints": {
            "GET:/today/events/": {
                "method": "GET",
                "path": "/today/events/",
                "pagination": {"style": "page_number", ...},
                "response_content_type": "application/json"
            }
        }
    }
    """
    endpoints = {}
    for key, ep_raw in data.get("endpoints", {}).items():
        pagination = _parse_pagination(ep_raw.get("pagination"))
        endpoints[key] = EndpointMeta(
            method=ep_raw.get("method", "GET"),
            path=ep_raw.get("path", ""),
            pagination=pagination,
            response_content_type=ep_raw.get("response_content_type"),
            description=ep_raw.get("description"),
            parameters=ep_raw.get("parameters"),
        )
    return APIMeta(
        slug=data.get("id", data.get("slug", slug)),
        base_url=data.get("base_url", ""),
        auth_type=data.get("auth_type", "none"),
        cors=data.get("cors"),
        endpoints=endpoints,
    )


def search(query: str, limit: int = 10) -> list[dict]:
    """Search the Zingu API registry by keywords.

    Returns a list of dicts with keys like 'slug', 'name', 'description',
    'tags', and 'relevance_score', ordered by relevance (highest first).
    Returns an empty list on failure.
    """
    try:
        headers = {}
        key = _get_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

        url = f"{_ZINGU_BASE}/search"
        resp = requests.get(url, headers=headers, params={"q": query, "limit": limit}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        # Server may return {results: [], suggestions: [...], message: "..."}
        results = data.get("results", [])
        if not results and data.get("suggestions"):
            # Return suggestions with a marker so callers know these aren't verified
            return [{
                **s,
                "_suggestion": True,
                "_message": data.get("message", ""),
            } for s in data["suggestions"]]
        return results
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.debug("Zingu search failed for %r: %s", query, exc)
        return []


def fetch_examples(slug: str, endpoint: str) -> list[dict]:
    """Fetch example requests for an endpoint from Zingu.

    Returns a (potentially empty) list of dicts with keys 'url' and 'description'.
    """
    cache_key = f"examples:{slug}:{endpoint}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        headers = {}
        key = _get_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

        url = f"{_ZINGU_BASE}/examples/{slug}"
        resp = requests.get(url, headers=headers, params={"endpoint": endpoint}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        examples = [
            {"url": ex.get("url", ""), "description": ex.get("description", "")}
            for ex in data if isinstance(ex, dict)
        ]
        _cache.put(cache_key, examples)
        return examples
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.debug("Zingu examples fetch failed for %s %s: %s", slug, endpoint, exc)
        return []


def fetch_meta(slug: str) -> APIMeta:
    """Fetch API metadata from Zingu, with cache layer.

    Resolution: memory cache → disk cache → live metadata endpoint → bare APIMeta.
    The bare APIMeta still works — fetch() uses sensible defaults and the
    pagination inference heuristic on the server side fills in what it can.
    """
    cache_key = f"meta:{slug}"

    # Layer 1: cache
    cached = _cache.get(cache_key)
    if cached is not None:
        return _parse_meta_response(slug, cached)

    # Layer 2: live Zingu public dashboard
    try:
        headers = {}
        key = _get_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

        url = f"{_ZINGU_BASE}/meta/{slug}"
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        _cache.put(cache_key, data)
        return _parse_meta_response(slug, data)
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.debug("Zingu metadata fetch failed for %s: %s", slug, exc)

    # No metadata available — return bare APIMeta (fetch still works with defaults)
    logger.warning("No metadata found for %s — using defaults", slug)
    return APIMeta(slug=slug, base_url="")
