"""Pagination strategy implementations.

Each strategy takes a response + current config and returns the next URL
to fetch, or None if there are no more pages.
"""

from __future__ import annotations

import re
from typing import Any

import requests

from ._types import PaginationConfig


def _extract_items(body: Any, config: PaginationConfig) -> tuple[list, str | None]:
    """Extract the items list from a response body.

    Returns (items, warning). Warning is set if the body shape was unexpected.

    Handles:
    - Paginated: body is {"results": [...], "next": ...} → return the list
    - List response: body is [...] → return as-is
    - Single object: body is {...} with no results key → wrap in a list
    - Raw text: body is {"_raw": ..., "_content_type": ...} → wrap as-is
    - Primitives/None: → empty list + warning
    """
    if body is None:
        return [], "Response body is empty"
    if isinstance(body, (str, int, float, bool)):
        return [{"_value": body}], f"Response is a bare {type(body).__name__}, not JSON object/array"
    if config.results_key and isinstance(body, dict):
        items = body.get(config.results_key)
        if items is not None:
            if isinstance(items, list):
                return items, None
            return [items], f"Expected list at '{config.results_key}', got {type(items).__name__}"
        # No results key found — the dict itself is the result
        return [body], None
    if isinstance(body, list):
        return body, None
    if isinstance(body, dict):
        return [body], None
    return [], f"Unexpected response type: {type(body).__name__}"


def _next_page_number(
    response: requests.Response, body: Any, config: PaginationConfig, current_url: str
) -> str | None:
    """page_number: ?page=N, incrementing."""
    # If response body has a 'next' URL, use it directly
    if config.next_key and isinstance(body, dict):
        next_url = body.get(config.next_key)
        if next_url:
            return next_url
    return None


def _next_offset_limit(
    response: requests.Response, body: Any, config: PaginationConfig, current_url: str
) -> str | None:
    """offset_limit: ?offset=N&limit=N."""
    if config.next_key and isinstance(body, dict):
        next_url = body.get(config.next_key)
        if next_url:
            return next_url
    # Check if there are more items by looking at count vs offset
    if isinstance(body, dict):
        count = body.get("count") or body.get("total")
        items = _extract_items(body, config)
        if count is not None and items:
            from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            offset = int(params.get(config.offset_param, ["0"])[0])
            limit = int(params.get(config.limit_param, ["20"])[0])
            new_offset = offset + len(items)
            if new_offset < int(count):
                params[config.offset_param] = [str(new_offset)]
                params[config.limit_param] = [str(limit)]
                flat = {k: v[0] for k, v in params.items()}
                new_query = urlencode(flat)
                return urlunparse(parsed._replace(query=new_query))
    return None


def _next_cursor(
    response: requests.Response, body: Any, config: PaginationConfig, current_url: str
) -> str | None:
    """cursor: extract cursor from response body, pass as query param."""
    if not isinstance(body, dict):
        return None
    cursor_field = config.cursor_field or config.next_key or "cursor"
    cursor_value = body.get(cursor_field)
    if not cursor_value:
        return None
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(current_url)
    params = parse_qs(parsed.query)
    params[cursor_field] = [str(cursor_value)]
    flat = {k: v[0] for k, v in params.items()}
    return urlunparse(parsed._replace(query=urlencode(flat)))


def _next_link_header(
    response: requests.Response, body: Any, config: PaginationConfig, current_url: str
) -> str | None:
    """link_header: parse Link header for rel="next"."""
    link = response.headers.get("Link", "")
    match = re.search(r'<([^>]+)>;\s*rel="next"', link)
    return match.group(1) if match else None


def _next_token(
    response: requests.Response, body: Any, config: PaginationConfig, current_url: str
) -> str | None:
    """token: nextPageToken / nextToken in response body."""
    if not isinstance(body, dict):
        return None
    token_field = config.cursor_field or "nextPageToken"
    token = body.get(token_field) or body.get("nextToken")
    if not token:
        return None
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    param_name = "pageToken" if "pageToken" in token_field.lower() else "token"
    parsed = urlparse(current_url)
    params = parse_qs(parsed.query)
    params[param_name] = [str(token)]
    flat = {k: v[0] for k, v in params.items()}
    return urlunparse(parsed._replace(query=urlencode(flat)))


def _next_keyset(
    response: requests.Response, body: Any, config: PaginationConfig, current_url: str
) -> str | None:
    """keyset: use last item's ID/key as 'after' param."""
    items = _extract_items(body, config)
    if not items:
        return None
    last = items[-1]
    key_field = config.cursor_field or "id"
    key_value = last.get(key_field) if isinstance(last, dict) else None
    if not key_value:
        return None
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(current_url)
    params = parse_qs(parsed.query)
    params["after"] = [str(key_value)]
    flat = {k: v[0] for k, v in params.items()}
    return urlunparse(parsed._replace(query=urlencode(flat)))


STRATEGIES = {
    "page_number": _next_page_number,
    "offset_limit": _next_offset_limit,
    "cursor": _next_cursor,
    "link_header": _next_link_header,
    "token": _next_token,
    "keyset": _next_keyset,
}


def get_next_url(
    style: str,
    response: requests.Response,
    body: Any,
    config: PaginationConfig,
    current_url: str,
) -> str | None:
    """Dispatch to the appropriate pagination strategy."""
    fn = STRATEGIES.get(style)
    if fn is None:
        return None
    return fn(response, body, config, current_url)
