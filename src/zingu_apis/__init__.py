"""zingu-apis: Smart API client powered by Zingu metadata."""

from __future__ import annotations

import os
from importlib.metadata import version as _pkg_version
from typing import Any, Literal

__version__ = _pkg_version("zingu-apis")

from ._client import APIClient
from ._endpoint import Endpoint
from ._errors import FetchError
from ._types import Parameter
from ._meta import configure, fetch_meta, search
from ._prune import PRUNE_PRINT, PRUNE_COMPACT, PRUNE_SAFE, PRUNE_NONE, PruneProfile, prune

ZINGU_WEB_HOME_URL: str = os.environ.get("ZINGU_WEB_HOME_URL", "https://zingu.ai")
ZINGU_API_BASE_URL: str = os.environ.get("ZINGU_API_BASE_URL", "https://zingu.ai/api")

__all__ = [
    "__version__",
    "api", "call", "fetch", "search", "configure", "APIClient", "Endpoint", "Parameter", "FetchError",
    "prune", "PruneProfile", "PRUNE_PRINT", "PRUNE_COMPACT", "PRUNE_SAFE", "PRUNE_NONE",
    "ZINGU_WEB_HOME_URL", "ZINGU_API_BASE_URL",
]


def api(slug: str, key: str | None = None, parser: Any | None = None) -> APIClient:
    """Get a metadata-aware API client for the given Zingu slug.

    Args:
        slug: API slug from the Zingu database.
        key: Optional API key/secret. If not provided, checks env vars
            (ZINGU_KEY_{SLUG}) and ~/.config/zingu/auth.json.

    >>> client = zingu_apis.api("dayinhistory.dev:day-in-history-api")
    >>> result = client.call("/today/events/")
    >>> for event in result["data"]:
    ...     print(event["title"])
    """
    return APIClient(slug, key=key, parser=parser)


def call(
    slug: str,
    path: str,
    *,
    key: str | None = None,
    max_items: int | None = None,
    max_pages: int = 10,
    max_chars: int = 1_000_000,
    truncation: Literal["none", "hard", "trailer", "smart"] = "trailer",
    truncation_trailer: str = "[...truncated...]",
    prune_profile: PruneProfile | str | None = None,
    parser: Any | None = None,
    strict: bool = False,
    **params: Any,
) -> dict:
    """Convenience: call an API endpoint in one shot.

    Returns {"data": [...], "content": "...", "analytics": {...}, "warnings": [...], "errors": [...]}.

    >>> result = zingu_apis.call("dayinhistory.dev:day-in-history-api", "/today/events/")
    >>> for event in result["data"]:
    ...     print(event["title"])
    """
    client = APIClient(slug, key=key, parser=parser)
    return client.call(
        path,
        max_items=max_items,
        max_pages=max_pages,
        max_chars=max_chars,
        truncation=truncation,
        truncation_trailer=truncation_trailer,
        prune_profile=prune_profile,
        strict=strict,
        **params,
    )


# Backwards-compatible alias
fetch = call
