"""API client with metadata-driven fetching — handles pagination, auth, and more."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Literal

import requests

from ._auth import resolve_auth
from ._endpoint import Endpoint
from ._errors import FetchError
from ._meta import fetch_meta, fetch_examples, _ZINGU_BASE, _get_api_key
from ._prune import PruneProfile, prune
from ._result import FetchResult
from ._strategies import get_next_url, _extract_items
from ._types import APIMeta, EndpointMeta, PaginationConfig

_DEFAULT_MAX_PAGES = 10
_DEFAULT_MAX_CHARS = 1_000_000
_DEFAULT_TRUNCATION = "trailer"
_DEFAULT_TRAILER = "[...truncated...]"
_DEFAULT_PAGE_DELAY_AUTH = 0.2  # seconds between pages for authenticated APIs
_DEFAULT_PAGE_DELAY_NOAUTH = 1.0  # seconds between pages for unauthenticated APIs
_DEFAULT_MAX_RETRIES = 2
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _smart_truncate(value: Any, max_chars: int, trailer: str) -> Any:
    """Truncate a value while preserving valid JSON structure."""
    if isinstance(value, dict):
        result = {}
        budget = max_chars - len(trailer) - 20
        used = 2
        for k, v in value.items():
            entry = json.dumps({k: v}, default=str)
            entry_len = len(entry) - 2
            if used + entry_len > budget:
                result["_truncated"] = trailer
                break
            result[k] = v
            used += entry_len + 2
        return result
    if isinstance(value, list):
        result = []
        budget = max_chars - len(trailer) - 10
        used = 2
        for item in value:
            entry = json.dumps(item, default=str)
            if used + len(entry) > budget:
                result.append(trailer)
                break
            result.append(item)
            used += len(entry) + 2
        return result
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    cut = max_chars - len(trailer)
    return text[:max(0, cut)] + trailer


def _truncate_value(value: Any, max_chars: int, mode: str, trailer: str) -> Any:
    """Truncate a string or serialized value if it exceeds max_chars."""
    if mode == "none":
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= max_chars:
        return value
    if mode == "hard":
        return text[:max_chars]
    if mode == "trailer":
        cut = max_chars - len(trailer)
        return text[:max(0, cut)] + trailer
    if mode == "smart":
        return _smart_truncate(value, max_chars, trailer)
    return value


def _retry_get(session: requests.Session, url: str, max_retries: int, timeout: int = 15, **kwargs) -> requests.Response:
    """GET with retry for transient errors. Respects Retry-After header."""
    last_exc = None
    for attempt in range(1 + max_retries):
        try:
            resp = session.get(url, timeout=timeout, **kwargs)
            if resp.status_code not in _RETRYABLE_STATUS_CODES or attempt >= max_retries:
                return resp
            # Retryable status — wait and try again
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = min(float(retry_after), 30.0)
                except ValueError:
                    wait = 2.0 * (attempt + 1)
            else:
                wait = 2.0 * (attempt + 1)  # exponential-ish: 2s, 4s
            time.sleep(wait)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            time.sleep(2.0 * (attempt + 1))
    raise last_exc or requests.RequestException("Max retries exceeded")


def _process_item(
    item: Any, max_chars: int, truncation: str, trailer: str, prune_profile: PruneProfile | str | None
) -> Any:
    """Apply truncation and pruning to a single item."""
    item = _truncate_value(item, max_chars, truncation, trailer)
    if prune_profile is not None:
        item = prune(item, prune_profile)
    return item


class APIClient:
    """A thin client for a single API, powered by Zingu metadata.

    Handles auth, pagination, response parsing, truncation, and pruning.
    """

    def __init__(
        self,
        slug: str,
        key: str | None = None,
        meta: APIMeta | None = None,
        parser: Any | None = None,
    ):
        self.meta = meta or fetch_meta(slug)
        self.slug = self.meta.slug  # canonical ID (resolved from short slug)
        self.base_url = self.meta.base_url.rstrip("/")
        self._session = requests.Session()
        self._auth = resolve_auth(self.slug, self.meta.auth_type, key=key)
        self._parser = parser  # callable(text) -> parsed data

    def _normalize_endpoint_name(self, path: str) -> str:
        """Convert endpoint path to valid Python identifier.

        Examples:
            "/events/{month}/{day}" -> "events_month_day"
            "/api/v1.0/users" -> "api_v1_0_users"
            "/data/csv,json" -> "data_csv_json"
        """
        import re

        # Remove path parameters (braces)
        name = path.replace("{", "").replace("}", "")

        # Replace any non-alphanumeric character with underscore
        name = re.sub(r'[^a-zA-Z0-9]+', '_', name)

        # Remove leading/trailing underscores
        name = name.strip("_")

        # Collapse multiple underscores
        name = re.sub(r'_+', '_', name)

        return name or "endpoint"

    def __getattr__(self, name: str):
        """Dynamically create endpoint methods.

        Enables calling endpoints as methods with parameters:
            api.events_month_day(month="july", day=4, max_items=5)
        """
        # Check if this name matches an endpoint short name
        for _key, ep in self.meta.endpoints.items():
            short = self._normalize_endpoint_name(ep.path) or ep.method.lower()
            if short == name:
                return self._make_endpoint_method(ep.path, ep.method)

        # Not a valid endpoint
        raise AttributeError(
            f"'{self.__class__.__name__}' has no attribute '{name}'. "
            f"Use .tools() to see available endpoints."
        )

    def _make_endpoint_method(self, path_template: str, method: str, endpoint_meta=None):
        """Create a bound method for an endpoint."""

        def endpoint_method(*args, **kwargs):
            # Extract fetch options from kwargs
            max_items = kwargs.pop('max_items', None)
            max_pages = kwargs.pop('max_pages', None)
            max_chars = kwargs.pop('max_chars', None)
            truncation = kwargs.pop('truncation', None)
            prune_profile = kwargs.pop('prune_profile', None)
            strict = kwargs.pop('strict', False)
            max_retries = kwargs.pop('max_retries', None)

            # Build path by substituting path parameters
            path = path_template
            for key, value in kwargs.items():
                placeholder = f'{{{key}}}'
                if placeholder in path:
                    path = path.replace(placeholder, str(value))

            # Call fetch with remaining params as query params
            fetch_kwargs = {}
            if max_items is not None:
                fetch_kwargs['max_items'] = max_items
            if max_pages is not None:
                fetch_kwargs['max_pages'] = max_pages
            if max_chars is not None:
                fetch_kwargs['max_chars'] = max_chars
            if truncation is not None:
                fetch_kwargs['truncation'] = truncation
            if prune_profile is not None:
                fetch_kwargs['prune_profile'] = prune_profile
            if strict:
                fetch_kwargs['strict'] = strict
            if max_retries is not None:
                fetch_kwargs['max_retries'] = max_retries

            return self.fetch(path, **fetch_kwargs)

        # Create clean method name without braces
        method_name = path_template.strip("/").replace("/", "_") or method.lower()
        method_name = method_name.replace("{", "").replace("}", "")
        endpoint_method.__name__ = self._normalize_endpoint_name(path_template)
        endpoint_method.__doc__ = f'Call {method} {path_template}'

        # Attach info function
        def info():
            """Return metadata about this endpoint."""
            ep = endpoint_meta
            if ep is None:
                # Find the endpoint meta
                for _k, e in self.meta.endpoints.items():
                    if e.path == path_template and e.method == method:
                        ep = e
                        break
            if ep is None:
                return {}

            return {
                'method': ep.method,
                'path': ep.path,
                'description': ep.description,
                'response_content_type': ep.response_content_type,
                'pagination': {
                    'style': ep.pagination.style if ep.pagination else None,
                    'results_key': ep.pagination.results_key if ep.pagination else None,
                } if ep.pagination else None,
                'parameters': ep.parameters,
            }

        endpoint_method.info = info
        return endpoint_method

    def tools(self) -> dict[str, dict[str, Any]]:
        """Return a dict of available endpoints keyed by short name.

        Each value contains 'method', 'path', 'description', and 'parameters'.
        The short name is derived from the endpoint path
        (e.g. "/today/events/" -> "today_events").
        """
        result: dict[str, dict[str, Any]] = {}
        for _key, ep in self.meta.endpoints.items():
            short = self._normalize_endpoint_name(ep.path) or ep.method.lower()
            entry: dict[str, Any] = {
                "method": ep.method,
                "path": ep.path,
            }
            if ep.description:
                entry["description"] = ep.description
            if ep.parameters:
                entry["parameters"] = ep.parameters
            result[short] = entry
        return result

    def help(self) -> str:
        """Return a help string showing available endpoints as methods."""
        lines = [f"Available endpoints for '{self.slug}':", ""]
        for name, info in self.tools().items():
            path = info["path"]
            method = info["method"]
            desc = info.get("description", "")
            # Show method signature
            params = []
            if "{" in path:
                # Extract path parameters
                import re
                params = re.findall(r'\{(\w+)\}', path)
            if params:
                param_str = ", ".join([f"{p}=..." for p in params])
                lines.append(f"  api.{name}({param_str})")
            else:
                lines.append(f"  api.{name}()")
            lines.append(f"    → {method} {path}")
            if desc:
                lines.append(f"    {desc}")
            lines.append("")
        return "\n".join(lines)

    def get_method_name(self, path: str) -> str | None:
        """Return the method name for a given endpoint path.

        Example:
            >>> api.get_method_name("/events/{month}/{day}")
            'events_month_day'
            >>> api.get_method_name("/today/events")
            'today_events'
        """
        # Normalize the input path
        normalized = self._normalize_endpoint_name(path)

        # Check if this matches any endpoint
        for _key, ep in self.meta.endpoints.items():
            if self._normalize_endpoint_name(ep.path) == normalized:
                return normalized
        return None

    def get_method(self, path: str):
        """Return the callable method for a given endpoint path.

        Example:
            >>> method = api.get_method("/events/{month}/{day}")
            >>> method(month="july", day=4, max_items=5)
        """
        normalized = self._normalize_endpoint_name(path)

        for _key, ep in self.meta.endpoints.items():
            if self._normalize_endpoint_name(ep.path) == normalized:
                return self._make_endpoint_method(ep.path, ep.method)

        raise ValueError(f"No endpoint found for path: {path}")

    def get_method_parameters(self, path: str) -> list[dict[str, Any]]:
        """Return the parameters for a given endpoint path.

        Extracts path parameters from the endpoint template and returns
them as a list of dicts with name and type information.

        Example:
            >>> api.get_method_parameters("/events/{month}/{day}")
            [{"name": "month", "type": "string"}, {"name": "day", "type": "string"}]
            >>> api.get_method_parameters("/today/events")
            []
        """
        import re

        normalized = self._normalize_endpoint_name(path)
        result: list[dict[str, Any]] = []

        for _key, ep in self.meta.endpoints.items():
            if self._normalize_endpoint_name(ep.path) == normalized:
                # Extract path parameters from template
                params = re.findall(r'\{(\w+)\}', ep.path)
                for param in params:
                    result.append({"name": param, "type": "string"})
                return result

        return []

    def info(self) -> dict[str, Any]:
        """Return a dict of API-level metadata.

        Keys include 'authentication', 'pagination', 'base_url', and any
        other metadata fields available from the Zingu registry.
        """
        pagination = None
        for ep in self.meta.endpoints.values():
            if ep.pagination and ep.pagination.style:
                pagination = ep.pagination.style
                break

        result: dict[str, Any] = {
            "authentication": self.meta.auth_type,
            "pagination": pagination,
            "base_url": self.meta.base_url,
        }
        if self.meta.cors is not None:
            result["cors"] = self.meta.cors
        return result

    def zingu(self) -> dict[str, Any]:
        """Return a dict of Zingu portal URLs and metadata for this API.

        Keys:
            home_url: Zingu portal home page
            api_base_url: Zingu API base URL
            web_url: This API's landing page on the Zingu portal
            tutorial_urls: List of tutorial URLs for this API
        """
        from . import ZINGU_WEB_HOME_URL, ZINGU_API_BASE_URL
        web_url = f"{ZINGU_WEB_HOME_URL}/apis/{self.slug}"
        tutorials_base = f"{web_url}/tutorials"

        # Fetch tutorial slugs from the metadata API
        tutorial_urls = [tutorials_base]
        try:
            url = f"{_ZINGU_BASE}/api/tutorials/{self.slug}"
            headers = {}
            key = _get_api_key()
            if key:
                headers["X-API-Key"] = key
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            tutorials = resp.json()
            if isinstance(tutorials, list) and tutorials:
                tutorial_urls = [
                    f"{tutorials_base}/{t['slug']}"
                    for t in tutorials
                    if isinstance(t, dict) and "slug" in t
                ]
        except Exception:
            pass

        return {
            "home_url": ZINGU_WEB_HOME_URL,
            "api_base_url": ZINGU_API_BASE_URL,
            "web_url": web_url,
            "tutorial_urls": tutorial_urls,
        }

    def get_url_template(self, contains: list[str] | None = None) -> str | None:
        """Find an endpoint whose path placeholders match the given names
        and return its full URL template.

        Args:
            contains: List of placeholder names to search for (e.g. ['country', 'id']).
                Returns the endpoint whose placeholders have the most overlap.
                If None, returns None.

        Returns:
            Full URL template string ready for str.format(), or None if no match.

        Example::

            tpl = api.get_url_template(contains=["country", "id"])
            # "https://api.example.com/v1/users/{country}/{id}"
            tpl.format(country="germany", id=123)
        """
        if not contains:
            return None

        wanted = set(contains)
        best_ep = None
        best_overlap = 0

        for ep in self.meta.endpoints.values():
            placeholders = set(re.findall(r"\{(\w+)\}", ep.path))
            overlap = len(wanted & placeholders)
            if overlap > best_overlap:
                best_overlap = overlap
                best_ep = ep

        if best_ep is None:
            return None
        return f"{self.base_url}/{best_ep.path.lstrip('/')}"

    def endpoint(self, path: str) -> Endpoint:
        """Return an Endpoint object for the given path.

        The Endpoint object has methods: parameters(), info(), examples(), fetch().
        """
        ep = self.meta.find_endpoint(path)
        if ep is None:
            ep = EndpointMeta(method="GET", path=path)
        return Endpoint(self.slug, ep, client=self)

    def examples(self, endpoint: str) -> list[dict[str, str]]:
        """Return example requests for an endpoint.

        Returns a (potentially empty) list of dicts with keys 'url' and 'description'.
        """
        return fetch_examples(self.slug, endpoint)

    def _parse_response(self, resp: requests.Response, ep: EndpointMeta | None, parser: Any | None = None) -> Any:
        """Parse response based on custom parser, known content type, or best guess."""
        # Custom parser takes priority
        parse_fn = parser or self._parser
        if parse_fn is not None:
            try:
                return parse_fn(resp.text)
            except Exception as exc:
                return {"_raw": resp.text, "_content_type": "parse_error", "_parse_error": str(exc)}

        ct = (ep.response_content_type if ep else None) or resp.headers.get("Content-Type", "")
        if "json" in ct or "javascript" in ct:
            return resp.json()
        if "yaml" in ct or "x-yaml" in ct:
            return {"_raw": resp.text, "_content_type": "yaml"}
        if "html" in ct:
            return {"_raw": resp.text, "_content_type": "html"}
        if "xml" in ct:
            return {"_raw": resp.text, "_content_type": "xml"}
        try:
            return resp.json()
        except (ValueError, TypeError):
            return {"_raw": resp.text, "_content_type": ct}

    def _prepare_request(self, params: dict) -> tuple[dict, dict]:
        """Apply auth to request params and headers."""
        headers = {}
        params = dict(params)  # copy to avoid mutating caller's dict
        self._auth.apply(params, headers)
        return params, headers

    def get(self, path: str, **params: Any) -> Any:
        """Make a single GET request (no pagination)."""
        ep = self.meta.find_endpoint(path)
        url = f"{self.base_url}/{path.lstrip('/')}"
        params, headers = self._prepare_request(params)
        resp = self._session.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        return self._parse_response(resp, ep)

    def get_bytes(self, path: str, timeout: int = 60, **params: Any) -> bytes:
        """Make a single GET request and return raw response bytes.

        Use for endpoints that return binary content (images, PDFs, etc.)
        instead of structured data.
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        params, headers = self._prepare_request(params)
        resp = self._session.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.content

    def fetch(
        self,
        path: str,
        *,
        params: dict[str, Any] | list[Any] | None = None,
        max_items: int | None = None,
        max_pages: int = _DEFAULT_MAX_PAGES,
        max_chars: int = _DEFAULT_MAX_CHARS,
        truncation: Literal["none", "hard", "trailer", "smart"] = _DEFAULT_TRUNCATION,
        truncation_trailer: str = _DEFAULT_TRAILER,
        prune_profile: PruneProfile | str | None = None,
        parser: Any | None = None,
        strict: bool = False,
        page_delay: float | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        **query_params: Any,
    ) -> FetchResult:
        """Fetch all items from an endpoint, handling pagination automatically.

        Returns a FetchResult (dict subclass) with:
            data: list of parsed items (post-truncation and pruning)
            content: raw response text (single string or list for multi-page)
            analytics: timing and pagination stats
            warnings: non-fatal issues encountered
            errors: errors encountered (empty if request succeeded)

        Iterate directly: for item in result: ...
        Pretty-print: print(result)
        Raw JSON: result.to_json()
        Full dict access: result["data"], result["analytics"]

        Args:
            path: Endpoint path (e.g. "/today/events/" or "/events/{month}/{day}").
            params: Optional dict of path parameters to substitute into the path
                (e.g. {"month": "july", "day": 4} for "/events/{month}/{day}").
            max_items: Stop after this many items. None = no item limit.
            max_pages: Stop after this many pages (default 10).
            max_chars: Truncate individual items exceeding this char count (default 1M).
            truncation: Truncation mode — "none", "hard", "trailer", or "smart".
            truncation_trailer: Trailer string appended when truncating.
            prune_profile: Optional pruning profile — PruneProfile, preset name, or None.
            parser: Optional callable(text) -> parsed data. Overrides default JSON parsing.
            strict: If True, raise FetchError when errors are encountered.
            page_delay: Seconds to pause between page requests. Default: 0.2s for
                authenticated APIs, 1.0s for unauthenticated (be polite to free APIs).
            max_retries: Retries for transient errors — 429, 5xx (default 2).
            **query_params: Extra query parameters passed to the API.
        """
        # Substitute path parameters if provided
        if params:
            if isinstance(params, (list, tuple)):
                # Positional params: extract placeholders in order
                import re
                placeholders = re.findall(r"\{(\w+)\}", path)
                for i, placeholder in enumerate(placeholders):
                    if i < len(params):
                        path = path.replace(f"{{{placeholder}}}", str(params[i]))
            else:
                # Dict params: named substitution
                for key, value in params.items():
                    path = path.replace(f"{{{key}}}", str(value))

        ep = self.meta.find_endpoint(path)
        config = ep.pagination if ep else None
        if config is None:
            config = PaginationConfig()

        # Default page delay: higher for unauthenticated APIs
        if page_delay is None:
            has_auth = self._auth.key is not None and self._auth.auth_type != "none"
            page_delay = _DEFAULT_PAGE_DELAY_AUTH if has_auth else _DEFAULT_PAGE_DELAY_NOAUTH

        data: list[Any] = []
        raw_pages: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []
        page_count = 0
        total_bytes = 0
        t_start = time.monotonic()
        page_timings: list[float] = []

        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            # First page
            t_page = time.monotonic()
            req_params, req_headers = self._prepare_request(query_params)
            resp = _retry_get(self._session, url, max_retries, params=req_params, headers=req_headers)
            resp.raise_for_status()
            page_timings.append(time.monotonic() - t_page)
            total_bytes += len(resp.content)
            raw_pages.append(resp.text)
            body = self._parse_response(resp, ep, parser)
            page_count = 1

            items, warn = _extract_items(body, config)
            if warn:
                warnings.append(warn)
            for item in items:
                item = _process_item(item, max_chars, truncation, truncation_trailer, prune_profile)
                data.append(item)
                if max_items and len(data) >= max_items:
                    break

            # Follow pagination
            if config.style and not (max_items and len(data) >= max_items):
                current_url = resp.url
                while page_count < max_pages:
                    next_url = get_next_url(config.style, resp, body, config, current_url)
                    if not next_url:
                        break

                    time.sleep(page_delay)
                    t_page = time.monotonic()
                    resp = _retry_get(self._session, next_url, max_retries)
                    resp.raise_for_status()
                    page_ms = time.monotonic() - t_page
                    page_timings.append(page_ms)
                    total_bytes += len(resp.content)
                    raw_pages.append(resp.text)
                    body = self._parse_response(resp, ep, parser)
                    current_url = resp.url
                    page_count += 1

                    if page_ms > 5.0:
                        warnings.append(f"Page {page_count} was slow ({page_ms:.1f}s)")

                    items, warn = _extract_items(body, config)
                    if warn:
                        warnings.append(warn)
                    if not items:
                        break
                    for item in items:
                        item = _process_item(item, max_chars, truncation, truncation_trailer, prune_profile)
                        data.append(item)
                        if max_items and len(data) >= max_items:
                            break
                    if max_items and len(data) >= max_items:
                        break

            if page_count >= max_pages and config.style:
                # Check if there would have been more
                next_url = get_next_url(config.style, resp, body, config, resp.url)
                if next_url:
                    warnings.append(f"Stopped at max_pages={max_pages} — more data available")

        except requests.HTTPError as exc:
            errors.append(f"HTTP {exc.response.status_code}: {exc.response.reason}")
        except requests.ConnectionError as exc:
            errors.append(f"Connection failed: {exc}")
        except requests.Timeout:
            errors.append("Request timed out")
        except requests.RequestException as exc:
            errors.append(str(exc))

        elapsed = time.monotonic() - t_start

        result = FetchResult({
            "data": data,
            "content": raw_pages[0] if len(raw_pages) == 1 else raw_pages,
            "analytics": {
                "elapsed_ms": round(elapsed * 1000),
                "pages_fetched": page_count,
                "items_total": len(data),
                "bytes_total": total_bytes,
                "avg_page_ms": round(sum(page_timings) / len(page_timings) * 1000) if page_timings else 0,
                "pagination_style": config.style,
                "response_content_type": ep.response_content_type if ep else None,
            },
            "warnings": warnings,
            "errors": errors,
        })

        if strict and errors:
            raise FetchError(errors, result)

        return result
