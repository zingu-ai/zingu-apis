"""Data types for Zingu API metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Parameter:
    """Metadata for a single API parameter."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None

    def __repr__(self) -> str:
        parts = [f"{self.name}: {self.type}"]
        if self.required:
            parts.append("required")
        if self.default is not None:
            parts.append(f"default={self.default!r}")
        if self.description:
            parts.append(f"— {self.description}")
        return f"Parameter({', '.join(parts)})"


@dataclass(frozen=True)
class PaginationConfig:
    """Pagination configuration for a single endpoint."""

    style: str | None = None  # page_number, offset_limit, cursor, link_header, token, keyset, none
    results_key: str | None = "results"  # JSON key containing the items list
    next_key: str | None = "next"  # JSON key or header containing next page pointer
    cursor_field: str | None = None  # field name for cursor/token value
    page_param: str = "page"  # query param name for page number
    limit_param: str = "limit"  # query param name for page size
    offset_param: str = "offset"  # query param name for offset
    in_header: bool = False  # whether pagination info is in response headers


@dataclass(frozen=True)
class EndpointMeta:
    """Metadata for a single API endpoint."""

    method: str
    path: str
    pagination: PaginationConfig | None = None
    response_content_type: str | None = None  # e.g. "application/json", "text/html"
    description: str | None = None
    parameters: dict | None = None


@dataclass
class APIMeta:
    """Metadata for an API, with all its endpoints."""

    slug: str
    base_url: str
    auth_type: str = "none"
    cors: str | None = None
    endpoints: dict[str, EndpointMeta] = field(default_factory=dict)

    def find_endpoint(self, path: str, method: str = "GET") -> EndpointMeta | None:
        """Find endpoint metadata by path and method.

        Leading/trailing slashes are optional — "users/{id}", "/users/{id}",
        "/users/{id}/", and "users/{id}/" all match the same endpoint.
        Parameterized segments like {id} match any concrete value.
        """
        normalized = path.strip("/")
        method_upper = method.upper()

        # Try exact key matches (stored keys may have leading slash)
        for candidate in (f"/{normalized}", f"/{normalized}/", normalized):
            key = f"{method_upper}:{candidate}"
            if key in self.endpoints:
                return self.endpoints[key]

        # Segment-based match for parameterized endpoints
        req_parts = normalized.split("/")
        for k, ep in self.endpoints.items():
            ep_method, ep_path = k.split(":", 1)
            if ep_method != method_upper:
                continue
            ep_parts = ep_path.strip("/").split("/")
            if len(ep_parts) != len(req_parts):
                continue
            if all(
                ep_seg.startswith("{") or ep_seg == req_seg
                for ep_seg, req_seg in zip(ep_parts, req_parts)
            ):
                return ep
        return None
