"""Endpoint object — rich accessor for a single API endpoint's metadata."""

from __future__ import annotations

import re
from urllib.parse import urlencode
from typing import TYPE_CHECKING, Any

from ._meta import fetch_examples
from ._types import EndpointMeta, Parameter

if TYPE_CHECKING:
    from ._client import APIClient


class Endpoint:
    """A single API endpoint with methods to inspect its metadata.

    Obtained via ``api.endpoint("/today/events/")``.
    """

    # Attributes that live on the instance itself (not treated as defaults)
    _RESERVED = frozenset({
        "_slug", "_meta", "_client", "_defaults", "_placeholders",
    })

    def __init__(self, slug: str, meta: EndpointMeta, client: APIClient | None = None):
        self._slug = slug
        self._meta = meta
        self._client = client
        self._defaults: dict[str, Any] = {}
        self._placeholders: set[str] = set(re.findall(r"\{(\w+)\}", meta.path))

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._RESERVED or name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._defaults[name] = value

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._defaults[name]
        except KeyError:
            raise AttributeError(f"No default set for '{name}'") from None

    def set(self, **kwargs: Any) -> Endpoint:
        """Set default query parameters. Returns self for chaining.

        Example::

            ep = api.endpoint("users/{country}/{id}").set(limit=10, format="json")
        """
        self._defaults.update(kwargs)
        return self

    def parameters(self) -> list[Parameter]:
        """Return the list of parameters accepted by this endpoint."""
        raw = self._meta.parameters
        if not raw:
            return []
        if isinstance(raw, list):
            return [
                Parameter(
                    name=p.get("name", ""),
                    type=p.get("type", "string"),
                    description=p.get("description", ""),
                    required=p.get("required", False),
                    default=p.get("default"),
                )
                for p in raw
                if isinstance(p, dict)
            ]
        if isinstance(raw, dict):
            return [
                Parameter(
                    name=name,
                    type=v.get("type", "string") if isinstance(v, dict) else "string",
                    description=v.get("description", "") if isinstance(v, dict) else str(v),
                    required=v.get("required", False) if isinstance(v, dict) else False,
                    default=v.get("default") if isinstance(v, dict) else None,
                )
                for name, v in raw.items()
            ]
        return []

    def info(self) -> dict[str, Any]:
        """Return a dict of metadata about this endpoint."""
        result: dict[str, Any] = {
            "method": self._meta.method,
            "path": self._meta.path,
        }
        if self._meta.description:
            result["description"] = self._meta.description
        if self._meta.response_content_type:
            result["response_content_type"] = self._meta.response_content_type
        if self._meta.pagination:
            result["pagination"] = self._meta.pagination.style
        return result

    def examples(self) -> list[dict[str, str]]:
        """Return example requests for this endpoint.

        Returns a (potentially empty) list of dicts with keys 'url' and 'description'.
        """
        return fetch_examples(self._slug, self._meta.path)

    def _resolve(self, api_params: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        """Merge defaults with explicit api_params, resolve path and query params.

        Returns (resolved_path, query_params).
        """
        # Defaults first, explicit params override
        merged = dict(self._defaults)
        if api_params:
            merged.update(api_params)

        # Separate path params from query params
        path = self._meta.path
        query_params = {}
        for key, value in merged.items():
            if key in self._placeholders:
                path = path.replace(f"{{{key}}}", str(value))
            else:
                query_params[key] = value
        return path, query_params

    def _require_client(self) -> None:
        if self._client is None:
            raise RuntimeError(
                "This Endpoint was created without a client reference. "
                "Use api.endpoint(...) to get a fetchable Endpoint."
            )

    def call(self, api_params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        """Call this endpoint.

        Args:
            api_params: Dict of API parameters — path placeholders are substituted,
                the rest become query parameters. Merged with defaults set via
                ``ep.limit = 10`` or ``ep.set(limit=10)``.
            **kwargs: zingu-apis controls only (max_items, max_pages,
                truncation, etc.).

        Example::

            ep = api.endpoint("users/{country}/{id}")
            ep.limit = 10
            result = ep.call({"country": "germany", "id": 123}, max_items=5)
        """
        self._require_client()
        path, query_params = self._resolve(api_params)
        return self._client.call(path, **kwargs, **query_params)

    # Backwards-compatible alias
    fetch = call

    def call_url(self, api_params: dict[str, Any] | None = None) -> str:
        """Build the full curl-ready URL for this endpoint.

        Same param merging as call(). Auth params are included automatically.

        Example::

            ep = api.endpoint("users/{country}/{id}")
            ep.limit = 10
            url = ep.call_url({"country": "germany", "id": 123})
            # "https://api.example.com/v1/users/germany/123?limit=10"
        """
        self._require_client()
        path, query_params = self._resolve(api_params)

        url = self._client._build_url(path)

        # Apply auth and merge query params
        req_params, _ = self._client._prepare_request(query_params)
        if req_params:
            url = f"{url}?{urlencode(req_params)}"
        return url

    # Backwards-compatible alias
    fetch_url = call_url

    @property
    def url_template(self) -> str:
        """Full URL template with {placeholders} preserved, ready for str.format().

        Example::

            ep = api.endpoint("users/{country}/{id}")
            ep.url_template
            # "https://api.example.com/v1/users/{country}/{id}"
            ep.url_template.format(country="germany", id=123)
            # "https://api.example.com/v1/users/germany/123"
        """
        if self._client is None:
            return self._meta.path
        return f"{self._client.base_url}/{self._meta.path.lstrip('/')}"

    def zingu(self) -> dict[str, Any]:
        """Return a dict of Zingu portal URLs for this endpoint.

        Keys:
            web_url: This endpoint's detail page on the Zingu portal
        """
        from . import ZINGU_WEB_HOME_URL
        safe_path = self._meta.path.replace("/", "_").replace("{", "").replace("}", "").replace(":", "_")
        endpoint_id = f"{self._slug}:{self._meta.method}:{safe_path}"
        return {
            "web_url": f"{ZINGU_WEB_HOME_URL}/endpoints/{endpoint_id}",
        }

    def __repr__(self) -> str:
        return f"Endpoint({self._meta.method} {self._meta.path})"
